"""Safe, bounded adapter for REA's static JavaScript/Electron analysis CLI."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any

from aurix.tools.workspace import _is_ignored_target, _is_sensitive, safe_path

MAX_STDOUT_CHARS = 32_000
MAX_STDERR_CHARS = 4_000
MAX_TIMEOUT_SECONDS = 120


def _signal_process_group(process: subprocess.Popen[bytes], *, force: bool = False) -> None:
    """Stop the bounded REA child and its descendants on POSIX."""
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


def _rea_executable() -> str:
    configured = os.environ.get("AURIX_REA_BIN", "rea").strip()
    if not configured:
        raise ValueError("AURIX_REA_BIN must not be empty")
    executable = shutil.which(configured)
    if executable is None:
        raise FileNotFoundError(
            "REA CLI was not found. Install the upstream 'rea-agents' package and ensure 'rea' is on PATH, "
            "or set AURIX_REA_BIN to its executable path."
        )
    return executable


def _child_environment() -> dict[str, str]:
    """Pass only basic runtime variables; never forward API keys or the full environment."""
    allowed = (
        "PATH",
        "HOME",
        "USERPROFILE",
        "SYSTEMROOT",
        "WINDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
    )
    return {key: os.environ[key] for key in allowed if key in os.environ}




def _run_bounded(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int
) -> dict[str, Any]:
    """Capture process output incrementally; terminate on a combined byte budget.

    Each pipe is drained by a dedicated thread to avoid deadlocks. Retained
    output is bounded independently of the amount emitted by the child.
    """
    import threading
    import time

    limit_bytes = (MAX_STDOUT_CHARS + MAX_STDERR_CHARS) * 4
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    totals = {"stdout": 0, "stderr": 0}
    exceeded = threading.Event()
    failures: list[BaseException] = []
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        shell=False,
        start_new_session=(os.name == "posix"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
    )

    def drain(name: str, stream: Any, cap: int) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                totals[name] += len(chunk)
                remaining = cap - len(buffers[name])
                if remaining > 0:
                    buffers[name].extend(chunk[:remaining])
                if totals["stdout"] + totals["stderr"] > limit_bytes:
                    exceeded.set()
        except (OSError, ValueError) as exc:
            failures.append(exc)

    threads = [
        threading.Thread(target=drain, args=("stdout", process.stdout, MAX_STDOUT_CHARS * 4), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr, MAX_STDERR_CHARS * 4), daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    while process.poll() is None:
        if exceeded.is_set():
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break
        time.sleep(0.02)
    if process.poll() is None and (exceeded.is_set() or timed_out):
        _signal_process_group(process)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            _signal_process_group(process, force=True)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        _signal_process_group(process, force=True)
        process.wait()
    for thread in threads:
        thread.join(timeout=2)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    return {
        "returncode": process.returncode,
        "stdout": bytes(buffers["stdout"]).decode("utf-8", errors="replace"),
        "stderr": bytes(buffers["stderr"]).decode("utf-8", errors="replace"),
        "timed_out": timed_out,
        "output_limit_exceeded": exceeded.is_set(),
    }


def analyze_javascript_application(
    workspace: Path | str,
    relative_path: str = ".",
    *,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Run REA's read-only static JavaScript/Electron analysis on a workspace target.

    The target must be a directory or an ASAR file inside the configured workspace.
    No shell is used and application code is not launched.
    """
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("REA analysis requires a non-empty workspace-relative path")
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise PermissionError("REA target must be a relative path inside the configured workspace")

    root = Path(workspace).expanduser().resolve()
    target = safe_path(root, relative_path)
    if _is_ignored_target(root, target) or _is_sensitive(target):
        raise PermissionError("REA cannot inspect ignored or sensitive workspace targets")
    if not target.exists():
        raise FileNotFoundError(f"REA target does not exist: {relative_path}")
    if target.is_symlink():
        raise PermissionError("REA does not analyze symlink targets")
    if not (target.is_dir() or (target.is_file() and target.suffix.lower() == ".asar")):
        raise ValueError(
            "REA static JavaScript analysis accepts an application directory or .asar file"
        )

    timeout = max(1, min(int(timeout_seconds), MAX_TIMEOUT_SECONDS))
    executable = _rea_executable()
    argv = [executable, "analyze-javascript-application", str(target), "--json"]
    completed = _run_bounded(argv, cwd=root, env=_child_environment(), timeout=timeout)
    if completed["timed_out"] or completed["output_limit_exceeded"]:
        return {
            "status": "timeout" if completed["timed_out"] else "output_limit_exceeded",
            "tool": "rea",
            "target": target.relative_to(root).as_posix(),
            "timeout_seconds": timeout,
            "stdout": completed["stdout"][-MAX_STDOUT_CHARS:],
            "stderr": completed["stderr"][-MAX_STDERR_CHARS:],
            "output_limit_exceeded": completed["output_limit_exceeded"],
            "application_executed": False,
        }

    stdout = completed["stdout"][-MAX_STDOUT_CHARS:]
    stderr = completed["stderr"][-MAX_STDERR_CHARS:]
    result: dict[str, Any] = {
        "status": "completed" if completed["returncode"] == 0 else "failed",
        "tool": "rea",
        "target": target.relative_to(root).as_posix(),
        "returncode": completed["returncode"],
        "application_executed": False,
        "stderr": stderr,
    }
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        result["status"] = "invalid_output" if completed["returncode"] == 0 else result["status"]
        result["output"] = stdout
        result["output_format"] = "text"
    else:
        result["evidence"] = parsed
        result["output_format"] = "json"
    return result


REA_INVESTIGATION_COMMANDS = {
    "analyze",
    "search",
    "function",
    "decompile",
    "xrefs",
    "trace",
    "providers",
    "capabilities",
}
_MAX_QUERY_CHARS = 500


def investigate_with_rea(
    workspace: Path | str,
    command: str,
    *,
    path: str = ".",
    query: str = "",
    provider: str = "auto",
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Run one allowlisted REA CLI investigation and return bounded evidence.

    This never invokes a shell or launches the analyzed target. Native commands
    may contact configured analysis providers (for example Ghidra/Hopper).
    """
    if command not in REA_INVESTIGATION_COMMANDS:
        raise ValueError("Unsupported REA command")
    root = Path(workspace).expanduser().resolve(strict=True)
    timeout = max(1, min(int(timeout_seconds), MAX_TIMEOUT_SECONDS))
    if command in {"providers", "capabilities"}:
        argv_tail = [command, "--json"]
        target_label = None
    else:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("REA target path must be a non-empty relative path")
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise PermissionError("REA target must remain inside the workspace")
        target = safe_path(root, path)
        if _is_ignored_target(root, target) or _is_sensitive(target):
            raise PermissionError("REA cannot inspect ignored or sensitive workspace targets")
        if not target.exists() or target.is_symlink() or not (target.is_file() or target.is_dir()):
            raise ValueError(
                "REA target must be an existing regular file or directory, not a symlink"
            )
        argv_tail = [command, str(target)]
        if command in {"search", "trace"}:
            if not isinstance(query, str) or not query.strip() or len(query) > _MAX_QUERY_CHARS:
                raise ValueError(
                    f"REA {command} requires a query of 1-{_MAX_QUERY_CHARS} characters"
                )
            argv_tail.append(query.strip())
        elif command in {"function", "decompile", "xrefs"}:
            if not isinstance(query, str) or not query.strip() or len(query) > _MAX_QUERY_CHARS:
                raise ValueError(f"REA {command} requires a function name or address")
            argv_tail.append(query.strip())
        if command in {"analyze", "search", "function", "decompile", "xrefs", "trace"}:
            if provider != "auto":
                if (
                    not isinstance(provider, str)
                    or not provider
                    or len(provider) > 80
                    or not all(c.isalnum() or c in "-_" for c in provider)
                ):
                    raise ValueError("Invalid REA provider ID")
                argv_tail.extend(["--provider", provider])
        argv_tail.append("--json")
        target_label = target.relative_to(root).as_posix()
    executable = _rea_executable()
    argv = [executable, *argv_tail]
    completed = _run_bounded(argv, cwd=root, env=_child_environment(), timeout=timeout)
    if completed["timed_out"] or completed["output_limit_exceeded"]:
        return {
            "status": "timeout" if completed["timed_out"] else "output_limit_exceeded",
            "tool": "rea",
            "command": command,
            "target": target_label,
            "timeout_seconds": timeout,
            "stdout": completed["stdout"][-MAX_STDOUT_CHARS:],
            "stderr": completed["stderr"][-MAX_STDERR_CHARS:],
            "output_limit_exceeded": completed["output_limit_exceeded"],
            "target_executed": False,
        }
    stdout, stderr = completed["stdout"], completed["stderr"]
    result: dict[str, Any] = {
        "status": "completed" if completed["returncode"] == 0 else "failed",
        "tool": "rea",
        "command": command,
        "target": target_label,
        "returncode": completed["returncode"],
        "target_executed": False,
        "stderr": stderr[-MAX_STDERR_CHARS:],
        "output_truncated": len(stdout) > MAX_STDOUT_CHARS,
    }
    try:
        result["evidence"] = json.loads(stdout[-MAX_STDOUT_CHARS:])
        result["output_format"] = "json"
    except json.JSONDecodeError:
        result["output"] = stdout[-MAX_STDOUT_CHARS:]
        result["output_format"] = "text"
        if completed["returncode"] == 0:
            result["status"] = "invalid_output"
    return result
