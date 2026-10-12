import json
import queue
from io import StringIO

import pytest

from aurix.tools import rea_mcp


class _FakeStdout:
    def __init__(self, messages):
        self.messages = messages

    def readline(self, size):
        item = self.messages.get()
        if item is None:
            return ""
        if len(item) <= size:
            return item
        self.messages.put(item[size:])
        return item[:size]


class _FakeStdin:
    def __init__(self, process):
        self.process = process

    def write(self, wire):
        request = json.loads(wire)
        method = request["method"]
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "serverInfo": {"name": "rea"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": "open_binary"},
                    {"name": "binary_overview"},
                    {"name": "delete_file"},
                ]
            }
        elif method == "tools/call" and request["params"]["name"] == "open_binary":
            self.process.calls.append(request)
            result = {"content": [{"type": "text", "text": "opened"}]}
        elif method == "tools/call" and request["params"]["name"] == "binary_overview":
            self.process.calls.append(request)
            result = {"content": [{"type": "text", "text": "overview evidence"}]}
        else:
            result = {}
        if "id" in request:
            self.process.messages.put(
                json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\n"
            )

    def flush(self):
        pass

    def close(self):
        self.process.closed_stdin = True


class _FakeProcess:
    def __init__(self, *args, **kwargs):
        self.messages = queue.Queue()
        self.stdout = _FakeStdout(self.messages)
        self.stderr = StringIO("")
        self.stdin = _FakeStdin(self)
        self.calls = []
        self.returncode = None
        self.closed_stdin = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        self.messages.put(None)
        return 0

    def terminate(self):
        self.returncode = -15
        self.messages.put(None)

    def kill(self):
        self.returncode = -9
        self.messages.put(None)


def test_mcp_investigation_uses_jsonrpc_and_only_expected_tools(monkeypatch, tmp_path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"fixture")
    captured = {}
    process = _FakeProcess()

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return process

    monkeypatch.setattr(rea_mcp, "_rea_executable", lambda: "/usr/bin/rea")
    monkeypatch.setattr(rea_mcp.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rea_mcp, "_child_environment", lambda: {"PATH": "/usr/bin"})

    result = rea_mcp.investigate_binary_with_rea_mcp(tmp_path, "sample.bin", provider="ghidra")

    assert result["status"] == "completed"
    assert result["transport"] == "stdio-jsonrpc"
    assert result["target_executed"] is False
    assert result["catalog_tool_count"] == 3
    assert captured["argv"] == ["/usr/bin/rea", "mcp"]
    assert captured["shell"] is False
    assert captured["env"] == {"PATH": "/usr/bin"}
    assert [call["params"]["name"] for call in process.calls] == ["open_binary", "binary_overview"]
    assert process.calls[0]["params"]["arguments"] == {"path": str(target), "provider_id": "ghidra"}


def test_mcp_investigation_rejects_path_traversal_and_symlink(tmp_path):
    outside = tmp_path.parent / "rea-outside.bin"
    outside.write_bytes(b"x")
    with pytest.raises(PermissionError):
        rea_mcp.investigate_binary_with_rea_mcp(tmp_path, "../rea-outside.bin")
    link = tmp_path / "link.bin"
    link.symlink_to(outside)
    with pytest.raises(PermissionError):
        rea_mcp.investigate_binary_with_rea_mcp(tmp_path, "link.bin")


def test_mcp_investigation_requires_existing_regular_file(tmp_path):
    with pytest.raises(ValueError, match="regular file"):
        rea_mcp.investigate_binary_with_rea_mcp(tmp_path, ".")


def test_mcp_tool_is_available_to_orchestrator(monkeypatch, tmp_path):
    from aurix.orchestrator import Orchestrator

    monkeypatch.setattr(
        "aurix.orchestrator.investigate_binary_with_rea_mcp",
        lambda workspace, path, **kwargs: {"status": "completed", "evidence": "binary overview"},
    )

    class Provider:
        def __init__(self):
            self.responses = [
                json.dumps(
                    {
                        "status": "tool_call",
                        "tool": "rea_mcp_investigate",
                        "arguments": {"path": "sample.bin"},
                    }
                ),
                json.dumps({"status": "final", "message": "Inspected binary."}),
            ]
            self.prompts = []

        def generate(self, prompt, *, system=""):
            self.prompts.append(prompt)
            return self.responses.pop(0)

    (tmp_path / "sample.bin").write_bytes(b"fixture")
    provider = Provider()
    result = Orchestrator(provider, workspace=tmp_path).run("Inspect binary")
    assert result.status == "completed"
    assert result.trace[0]["tool"] == "rea_mcp_investigate"
    assert "binary overview" in provider.prompts[1]


def test_mcp_stdout_rejects_oversized_line_before_json_parse(monkeypatch):
    class Stream:
        def __init__(self):
            self.sent = False

        def readline(self, size):
            if self.sent:
                return ""
            self.sent = True
            return "x" * size

    class Process:
        def __init__(self):
            self.stdout = Stream()
            self.terminated = False

        def terminate(self):
            self.terminated = True

    process = Process()
    client = object.__new__(rea_mcp._StdioMCP)
    client.process = process
    client._messages = queue.Queue(maxsize=rea_mcp._MAX_QUEUED_MCP_MESSAGES)
    client._read_stdout()
    assert client._messages.get_nowait() == rea_mcp._OVERSIZED_MESSAGE
    assert process.terminated is True


def test_mcp_stdout_accepts_frame_at_exact_payload_limit(monkeypatch):
    monkeypatch.setattr(rea_mcp, "MAX_MCP_MESSAGE_CHARS", 4)

    class Stream:
        def __init__(self):
            self.items = iter(["1234\n", ""])

        def readline(self, size):
            return next(self.items)

    class Process:
        stdout = Stream()

        def terminate(self):
            raise AssertionError("valid frame must not terminate the process")

    client = object.__new__(rea_mcp._StdioMCP)
    client.process = Process()
    client._messages = queue.Queue(maxsize=2)
    client._read_stdout()

    assert client._messages.get_nowait() == "1234"
    assert client._messages.get_nowait() is None


def test_mcp_stdout_preserves_oversized_error_when_queue_is_full(monkeypatch):
    monkeypatch.setattr(rea_mcp, "MAX_MCP_MESSAGE_CHARS", 4)

    class Stream:
        def readline(self, size):
            return "12345\n"

    class Process:
        stdout = Stream()
        terminated = False

        def terminate(self):
            self.terminated = True

    process = Process()
    client = object.__new__(rea_mcp._StdioMCP)
    client.process = process
    client._messages = queue.Queue(maxsize=1)
    client._messages.put_nowait("stale")

    client._read_stdout()

    assert process.terminated is True
    assert client._messages.get_nowait() == rea_mcp._OVERSIZED_MESSAGE


def test_mcp_stdout_rejects_truncated_frame_at_eof(monkeypatch):
    monkeypatch.setattr(rea_mcp, "MAX_MCP_MESSAGE_CHARS", 64)

    class Stream:
        def __init__(self):
            self.items = iter(['{"jsonrpc": "2.0"}', ""])

        def readline(self, size):
            return next(self.items)

    class Process:
        stdout = Stream()
        terminated = False

        def terminate(self):
            self.terminated = True

    process = Process()
    client = object.__new__(rea_mcp._StdioMCP)
    client.process = process
    client._messages = queue.Queue(maxsize=2)

    client._read_stdout()

    assert process.terminated is True
    assert client._messages.get_nowait() == rea_mcp._OVERSIZED_MESSAGE


def test_mcp_stdout_does_not_block_when_message_queue_is_full(monkeypatch):
    monkeypatch.setattr(rea_mcp, "MAX_MCP_MESSAGE_CHARS", 64)

    class Stream:
        def __init__(self):
            self.items = iter(['{"jsonrpc":"2.0","id":1}\n', ""])

        def readline(self, size):
            return next(self.items)

    class Process:
        stdout = Stream()
        terminated = False

        def terminate(self):
            self.terminated = True

    process = Process()
    client = object.__new__(rea_mcp._StdioMCP)
    client.process = process
    client._messages = queue.Queue(maxsize=1)
    client._messages.put_nowait("already queued")

    client._read_stdout()

    assert process.terminated is True
    assert client._messages.get_nowait() == rea_mcp._OVERSIZED_MESSAGE


def test_mcp_request_fails_fast_on_malformed_jsonrpc_stdout():
    class Stdin:
        def write(self, wire):
            pass

        def flush(self):
            pass

    class Process:
        stdin = Stdin()

        def poll(self):
            return None

    client = object.__new__(rea_mcp._StdioMCP)
    client.process = Process()
    client.timeout = 1
    import time

    client.deadline = time.monotonic() + 1
    client._next_id = 1
    client._messages = queue.Queue(maxsize=2)
    client._messages.put_nowait("not-json")

    with pytest.raises(ValueError, match="malformed JSON-RPC"):
        client.request("initialize")


def test_mcp_process_tree_uses_dedicated_posix_process_group(monkeypatch):
    import os
    import signal

    if os.name != "posix":
        pytest.skip("POSIX process groups are not available")

    calls = []

    class Process:
        pid = 43210

        def terminate(self):
            raise AssertionError("process-group signaling should be used")

        def kill(self):
            raise AssertionError("process-group signaling should be used")

    monkeypatch.setattr(rea_mcp.os, "killpg", lambda pid, sig: calls.append((pid, sig)))

    rea_mcp._signal_process_tree(Process())
    rea_mcp._signal_process_tree(Process(), force=True)

    assert calls == [(43210, signal.SIGTERM), (43210, signal.SIGKILL)]


def test_mcp_stderr_capture_is_bounded(monkeypatch):
    monkeypatch.setattr(rea_mcp, "MAX_MCP_STDERR_CHARS", 32)

    class Process:
        stderr = StringIO("diagnostic-" * 100)

    client = object.__new__(rea_mcp._StdioMCP)
    client.process = Process()
    client._stderr_parts = []
    client._stderr_size = 0

    client._read_stderr()

    assert len(client.stderr) <= 32
    assert client.stderr == ("diagnostic-" * 100)[-32:]
