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



def test_mcp_request_does_not_accept_boolean_as_numeric_response_id():
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
    client._messages.put_nowait(json.dumps({"jsonrpc": "2.0", "id": True, "result": {"wrong": True}}))
    client._messages.put_nowait(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"accepted": True}}))

    assert client.request("initialize") == {"accepted": True}


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


@pytest.mark.parametrize(
    ("failing_tool", "expected_message"),
    [
        ("open_binary", "open_binary returned an error result"),
        ("binary_overview", "binary_overview returned an error result"),
    ],
)
def test_mcp_tool_call_errors_are_not_reported_as_success(
    monkeypatch, tmp_path, failing_tool, expected_message
):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"fixture")

    class Process:
        stdin = None
        pid = None

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    class Client:
        def __init__(self, process, timeout):
            self.stderr = ""
            self.calls = []
            self.closed = False

        def request(self, method, params=None):
            self.calls.append((method, params))
            if method == "initialize":
                return {"protocolVersion": "2025-03-26"}
            if method == "tools/list":
                return {"tools": [{"name": "open_binary"}, {"name": "binary_overview"}]}
            if method == "tools/call" and params["name"] == failing_tool:
                return {"isError": True, "content": [{"type": "text", "text": "fixture failure"}]}
            return {"content": [{"type": "text", "text": "ok"}]}

        def notify(self, method, params=None):
            pass

        def close(self):
            self.closed = True

    clients = []

    def fake_client(process, timeout):
        client = Client(process, timeout)
        clients.append(client)
        return client

    monkeypatch.setattr(rea_mcp, "_rea_executable", lambda: "/usr/bin/rea")
    monkeypatch.setattr(rea_mcp.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(rea_mcp, "_child_environment", lambda: {"PATH": "/usr/bin"})
    monkeypatch.setattr(rea_mcp, "_StdioMCP", fake_client)

    with pytest.raises(RuntimeError, match=expected_message):
        rea_mcp.investigate_binary_with_rea_mcp(tmp_path, "sample.bin")

    assert clients and clients[0].closed is True


def test_mcp_initialization_timeout_returns_timeout_and_closes_client(monkeypatch, tmp_path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"fixture")

    class Process:
        stdin = None
        pid = None

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    class Client:
        def __init__(self, process, timeout):
            self.stderr = "initialization stalled"
            self.closed = False

        def request(self, method, params=None):
            raise TimeoutError(f"REA MCP request timed out: {method}")

        def close(self):
            self.closed = True

    clients = []

    def fake_client(process, timeout):
        client = Client(process, timeout)
        clients.append(client)
        return client

    monkeypatch.setattr(rea_mcp, "_rea_executable", lambda: "/usr/bin/rea")
    monkeypatch.setattr(rea_mcp.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(rea_mcp, "_child_environment", lambda: {"PATH": "/usr/bin"})
    monkeypatch.setattr(rea_mcp, "_StdioMCP", fake_client)

    result = rea_mcp.investigate_binary_with_rea_mcp(tmp_path, "sample.bin")

    assert result["status"] == "timeout"
    assert result["target_executed"] is False
    assert result["stderr"] == "initialization stalled"
    assert clients and clients[0].closed is True


def test_mcp_rejects_invalid_provider_before_launch(monkeypatch, tmp_path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"fixture")

    def unexpected_launch(*args, **kwargs):
        raise AssertionError("invalid provider must be rejected before process launch")

    monkeypatch.setattr(rea_mcp.subprocess, "Popen", unexpected_launch)

    with pytest.raises(ValueError, match="Invalid REA provider ID"):
        rea_mcp.investigate_binary_with_rea_mcp(tmp_path, "sample.bin", provider="bad provider")


def test_mcp_real_stalled_server_times_out_and_is_reaped(monkeypatch, tmp_path):
    import os
    import subprocess

    target = tmp_path / "sample.bin"
    target.write_bytes(b"fixture")
    server = tmp_path / "stalled-rea-mcp"
    server.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "while True: time.sleep(0.1)\n",
        encoding="utf-8",
    )
    server.chmod(0o755)

    real_popen = subprocess.Popen
    launched = []

    def capture_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(rea_mcp, "_rea_executable", lambda: str(server))
    monkeypatch.setattr(rea_mcp, "_child_environment", lambda: {"PATH": os.environ.get("PATH", "")})
    monkeypatch.setattr(rea_mcp.subprocess, "Popen", capture_popen)

    result = rea_mcp.investigate_binary_with_rea_mcp(
        tmp_path, "sample.bin", timeout_seconds=1
    )

    assert result["status"] == "timeout"
    assert result["target_executed"] is False
    assert launched and launched[0].poll() is not None



def test_mcp_real_stderr_flood_retains_only_bounded_tail():
    import subprocess
    import sys

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('x' * 50000 + 'TAIL_SENTINEL'); sys.stderr.flush()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=(__import__("os").name == "posix"),
    )
    client = rea_mcp._StdioMCP(process, timeout=3)
    try:
        process.wait(timeout=3)
        client._stderr_reader.join(timeout=3)
        assert not client._stderr_reader.is_alive()
        assert len(client.stderr) <= rea_mcp.MAX_MCP_STDERR_CHARS
        assert client.stderr.endswith("TAIL_SENTINEL")
    finally:
        client.close()



def test_mcp_request_ignores_notifications_and_mismatched_response_ids():
    client = object.__new__(rea_mcp._StdioMCP)
    client.timeout = 1
    import time

    client.deadline = time.monotonic() + 1
    client._next_id = 1
    client._messages = queue.Queue(maxsize=4)

    class Stdin:
        def write(self, wire):
            request = json.loads(wire)
            client._messages.put_nowait(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}})
            )
            client._messages.put_nowait(
                json.dumps({"jsonrpc": "2.0", "id": 99, "result": {"wrong": True}})
            )
            client._messages.put_nowait(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "result": {"right": True},
                    }
                )
            )

        def flush(self):
            pass

    class Process:
        stdin = Stdin()

        def poll(self):
            return None

    client.process = Process()

    assert client.request("initialize") == {"right": True}



@pytest.mark.parametrize(
    "relative_path",
    [".env", ".ssh/id_rsa", ".git/config", ".aurix/transaction.json"],
)
def test_mcp_investigation_rejects_sensitive_or_ignored_targets(
    monkeypatch, tmp_path, relative_path
):
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"secret fixture")

    def unexpected_launch(*args, **kwargs):
        raise AssertionError("sensitive target must be rejected before process launch")

    monkeypatch.setattr(rea_mcp.subprocess, "Popen", unexpected_launch)

    with pytest.raises(PermissionError, match="ignored or sensitive"):
        rea_mcp.investigate_binary_with_rea_mcp(tmp_path, relative_path)



def test_mcp_rejects_unsupported_negotiated_protocol_version(monkeypatch, tmp_path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"fixture")

    class Process:
        stdin = None
        pid = None

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    class Client:
        def __init__(self, process, timeout):
            self.stderr = ""
            self.calls = []
            self.closed = False

        def request(self, method, params=None):
            self.calls.append(method)
            if method == "initialize":
                return {"protocolVersion": "unsupported-version"}
            raise AssertionError("no MCP requests should follow failed negotiation")

        def close(self):
            self.closed = True

        def notify(self, method, params=None):
            raise AssertionError("initialized notification must not follow failed negotiation")

    clients = []

    def fake_client(process, timeout):
        client = Client(process, timeout)
        clients.append(client)
        return client

    monkeypatch.setattr(rea_mcp, "_rea_executable", lambda: "/usr/bin/rea")
    monkeypatch.setattr(rea_mcp.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(rea_mcp, "_child_environment", lambda: {"PATH": "/usr/bin"})
    monkeypatch.setattr(rea_mcp, "_StdioMCP", fake_client)

    with pytest.raises(RuntimeError, match="unsupported protocol version"):
        rea_mcp.investigate_binary_with_rea_mcp(tmp_path, "sample.bin")

    assert clients and clients[0].calls == ["initialize"]
    assert clients[0].closed is True



def test_mcp_request_rejects_wrong_jsonrpc_version():
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
    client._messages.put_nowait(json.dumps({"jsonrpc": "1.0", "id": 1, "result": {}}))

    with pytest.raises(ValueError, match="invalid JSON-RPC version"):
        client.request("initialize")
