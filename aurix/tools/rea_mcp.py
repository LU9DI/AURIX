"""Bounded stdio MCP client for REA's read-only native investigation workflow."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from aurix.tools.rea import MAX_STDOUT_CHARS, _child_environment, _rea_executable
from aurix.tools.workspace import safe_path

MAX_MCP_MESSAGE_CHARS = 1_000_000
MAX_MCP_STDERR_CHARS = 4_000
MAX_MCP_TIMEOUT_SECONDS = 240
_MAX_QUEUED_MCP_MESSAGES = 16
_OVERSIZED_MESSAGE = "__AURIX_REA_MCP_OVERSIZED_MESSAGE__"
READ_ONLY_MCP_TOOLS = {"binary_session", "binary_overview"}


def _signal_process_tree(process: subprocess.Popen[str], *, force: bool = False) -> None:
    """Stop the dedicated REA process group where supported; fall back to the child."""
    if os.name == "posix" and isinstance(getattr(process, "pid", None), int):
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    try:
        process.kill() if force else process.terminate()
    except (OSError, ProcessLookupError):
        pass


class _StdioMCP:
    """Small JSON-RPC stdio client. One server process is used per investigation."""

    def __init__(self, process: subprocess.Popen[str], timeout: int) -> None:
        self.process = process
        self.timeout = timeout
        self.deadline = time.monotonic() + timeout
        self._messages: queue.Queue[str | None] = queue.Queue(maxsize=_MAX_QUEUED_MCP_MESSAGES)
        self._stderr_parts: list[str] = []
        self._stderr_size = 0
        self._next_id = 1
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr_reader.start()

    def _enqueue_terminal(self, message: str | None) -> None:
        """Signal the reader outcome without blocking behind a full queue."""
        try:
            self._messages.put_nowait(message)
        except queue.Full:
            try:
                displaced = self._messages.get_nowait()
            except queue.Empty:
                displaced = None
            if message is None and displaced == _OVERSIZED_MESSAGE:
                try:
                    self._messages.put_nowait(displaced)
                except queue.Full:
                    pass
                return
            try:
                self._messages.put_nowait(message)
            except queue.Full:
                pass

    def _enqueue_frame(self, payload: str) -> bool:
        """Queue one frame without allowing a stalled consumer to block the reader."""
        try:
            self._messages.put(payload, timeout=0.1)
            return True
        except queue.Full:
            self._enqueue_terminal(_OVERSIZED_MESSAGE)
            _signal_process_tree(self.process)
            return False

    def _read_stdout(self) -> None:
        """Read bounded newline-delimited frames, rejecting oversized lines early."""
        assert self.process.stdout is not None
        try:
            while True:
                # The extra two characters cover a possible CRLF terminator.
                line = self.process.stdout.readline(MAX_MCP_MESSAGE_CHARS + 2)
                if not line:
                    break
                has_newline = line.endswith("\n")
                payload = line[:-1] if has_newline else line
                if payload.endswith("\r"):
                    payload = payload[:-1]
                if len(payload) > MAX_MCP_MESSAGE_CHARS or (
                    not has_newline and len(line) >= MAX_MCP_MESSAGE_CHARS + 2
                ):
                    self._enqueue_terminal(_OVERSIZED_MESSAGE)
                    _signal_process_tree(self.process)
                    return
                if not has_newline:
                    # EOF in the middle of a JSON-RPC frame is a protocol error.
                    self._enqueue_terminal(_OVERSIZED_MESSAGE)
                    _signal_process_tree(self.process)
                    return
                if not self._enqueue_frame(payload):
                    return
        except (OSError, ValueError):
            pass
        finally:
            self._enqueue_terminal(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for chunk in iter(lambda: self.process.stderr.read(512), ""):
            self._stderr_parts.append(chunk)
            self._stderr_size += len(chunk)
            while self._stderr_size > MAX_MCP_STDERR_CHARS and self._stderr_parts:
                removed = self._stderr_parts.pop(0)
                self._stderr_size -= len(removed)

    @property
    def stderr(self) -> str:
        return "".join(self._stderr_parts)[-MAX_MCP_STDERR_CHARS:]

    def _send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None or self.process.poll() is not None:
            raise RuntimeError("REA MCP server exited before completing the request")
        wire = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        self.process.stdin.write(wire + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        while True:
            remaining = min(self.timeout, self.deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError(f"REA MCP request timed out: {method}")
            try:
                line = self._messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"REA MCP request timed out: {method}") from exc
            if line is None:
                raise RuntimeError("REA MCP server closed stdout before replying")
            if line == _OVERSIZED_MESSAGE:
                raise ValueError("REA MCP response exceeded the message-size limit")
            if len(line) > MAX_MCP_MESSAGE_CHARS:
                raise ValueError("REA MCP response exceeded the message-size limit")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                # MCP stdout is protocol-only; diagnostics belong on stderr.
                raise ValueError("REA MCP emitted malformed JSON-RPC on stdout") from exc
            if not isinstance(response, dict) or response.get("id") != request_id:
                continue
            if "error" in response:
                error = response["error"]
                raise RuntimeError(f"REA MCP {method} failed: {json.dumps(error)[:1000]}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise ValueError(f"REA MCP {method} returned a non-object result")
            return result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def close(self) -> None:
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        _signal_process_tree(self.process)
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _signal_process_tree(self.process, force=True)
            self.process.wait(timeout=2)


def investigate_binary_with_rea_mcp(
    workspace: Path | str,
    relative_path: str,
    *,
    provider: str = "auto",
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Open a workspace-local binary with REA MCP and request its binary overview.

    Only `open_binary` (to bind a target) and `binary_overview` are called. The
    server is launched as `rea mcp`, never via a shell or `npx`, and is stopped
    after the bounded workflow. This does not execute the target binary.
    """
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("REA MCP requires a non-empty workspace-relative target")
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise PermissionError("REA MCP target must be inside the configured workspace")
    if (
        not isinstance(provider, str)
        or not provider
        or len(provider) > 80
        or not all(c.isalnum() or c in "-_" for c in provider)
    ):
        raise ValueError("Invalid REA provider ID")
    root = Path(workspace).expanduser().resolve(strict=True)
    target = safe_path(root, relative_path)
    if not target.is_file() or target.is_symlink():
        raise ValueError("REA MCP target must be an existing regular file, not a symlink")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise ValueError("timeout_seconds must be an integer")
    timeout = max(1, min(timeout_seconds, MAX_MCP_TIMEOUT_SECONDS))
    executable = _rea_executable()
    process = subprocess.Popen(
        [executable, "mcp"],
        cwd=root,
        env=_child_environment(),
        shell=False,
        start_new_session=(os.name == "posix"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    client = _StdioMCP(process, timeout)
    try:
        initialized = client.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "aurix", "version": "0.28.0"},
            },
        )
        client.notify("notifications/initialized")
        catalog = client.request("tools/list")
        tools = catalog.get("tools")
        if not isinstance(tools, list):
            raise ValueError("REA MCP tools/list response did not contain a tool catalog")
        by_name = {
            item.get("name"): item
            for item in tools
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        if "open_binary" not in by_name or "binary_overview" not in by_name:
            raise RuntimeError(
                "This REA MCP catalog does not expose open_binary and binary_overview"
            )
        opened = client.request(
            "tools/call",
            {
                "name": "open_binary",
                "arguments": {
                    "path": str(target),
                    "provider_id": provider,
                },
            },
        )
        if opened.get("isError") is True:
            raise RuntimeError("REA MCP open_binary returned an error result")
        overview = client.request("tools/call", {"name": "binary_overview", "arguments": {}})
        if overview.get("isError") is True:
            raise RuntimeError("REA MCP binary_overview returned an error result")
        payload = json.dumps({"opened": opened, "overview": overview}, ensure_ascii=False)
        return {
            "status": "completed",
            "tool": "rea_mcp",
            "target": target.relative_to(root).as_posix(),
            "provider": provider,
            "protocol_version": initialized.get("protocolVersion"),
            "catalog_tool_count": len(tools),
            "evidence": payload[:MAX_STDOUT_CHARS],
            "evidence_truncated": len(payload) > MAX_STDOUT_CHARS,
            "target_executed": False,
            "transport": "stdio-jsonrpc",
        }
    except TimeoutError as exc:
        return {
            "status": "timeout",
            "tool": "rea_mcp",
            "target": target.relative_to(root).as_posix(),
            "timeout_seconds": timeout,
            "message": str(exc)[:500],
            "stderr": client.stderr,
            "target_executed": False,
            "transport": "stdio-jsonrpc",
        }
    finally:
        client.close()
