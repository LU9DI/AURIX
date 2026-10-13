import json
from pathlib import Path

import pytest

from aurix.tools import rea, rea_mcp


def test_rea_runs_only_static_analysis_without_shell(monkeypatch, tmp_path):
    app = tmp_path / "desktop-app"
    app.mkdir()
    (app / "package.json").write_text('{"name":"desktop-app"}', encoding="utf-8")
    captured = {}

    class Completed:
        returncode = 0
        stdout = '{"status":"completed","modules":3,"evidence":[]}'
        stderr = ""

    monkeypatch.setattr(rea, "_rea_executable", lambda: "/usr/local/bin/rea")
    monkeypatch.setattr(rea, "_child_environment", lambda: {"PATH": "/usr/bin"})

    def fake_bounded(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return {
            "returncode": 0,
            "stdout": Completed.stdout,
            "stderr": "",
            "timed_out": False,
            "output_limit_exceeded": False,
        }

    monkeypatch.setattr(rea, "_run_bounded", fake_bounded)
    result = rea.analyze_javascript_application(tmp_path, "desktop-app")

    assert result["status"] == "completed"
    assert result["evidence"]["modules"] == 3
    assert captured["argv"][:2] == [
        "/usr/local/bin/rea",
        "analyze-javascript-application",
    ]
    staged = Path(captured["argv"][2])
    assert staged != app
    assert not staged.exists()  # temporary staging is removed after the child exits
    assert captured["timeout"] == 90
    assert captured["env"] == {"PATH": "/usr/bin"}
    assert result["application_executed"] is False


def test_rea_rejects_path_traversal_and_absolute_paths(tmp_path):
    with pytest.raises(PermissionError):
        rea.analyze_javascript_application(tmp_path, "../outside")
    with pytest.raises(PermissionError):
        rea.analyze_javascript_application(tmp_path, str(tmp_path))


def test_rea_requires_directory_or_asar(tmp_path):
    binary = tmp_path / "app.exe"
    binary.write_bytes(b"not executed")
    with pytest.raises(ValueError, match="directory or .asar"):
        rea.analyze_javascript_application(tmp_path, "app.exe")


def test_rea_caps_timeout_and_reports_timeout(monkeypatch, tmp_path):
    app = tmp_path / "app.asar"
    app.write_bytes(b"fixture")
    monkeypatch.setattr(rea, "_rea_executable", lambda: "rea")
    monkeypatch.setattr(rea, "_child_environment", dict)
    captured = {}

    def fake_bounded(argv, **kwargs):
        captured.update(kwargs)
        return {
            "returncode": -15,
            "stdout": "partial",
            "stderr": "",
            "timed_out": True,
            "output_limit_exceeded": False,
        }

    monkeypatch.setattr(rea, "_run_bounded", fake_bounded)
    result = rea.analyze_javascript_application(tmp_path, "app.asar", timeout_seconds=999)
    assert captured["timeout"] == 120
    assert result["status"] == "timeout"
    assert result["application_executed"] is False


def test_orchestrator_can_use_rea_static_analysis(monkeypatch, tmp_path):
    from aurix.orchestrator import Orchestrator

    app = tmp_path / "electron"
    app.mkdir()
    (app / "package.json").write_text('{"name":"electron"}', encoding="utf-8")
    monkeypatch.setattr(
        "aurix.orchestrator.analyze_javascript_application",
        lambda workspace, relative_path, timeout_seconds=90: {
            "status": "completed",
            "tool": "rea",
            "target": relative_path,
            "evidence": {"modules": 2, "imports": []},
            "application_executed": False,
        },
    )

    class SequenceProvider:
        def __init__(self):
            self.responses = [
                json.dumps(
                    {
                        "status": "tool_call",
                        "tool": "rea_analyze_app",
                        "arguments": {"path": "electron"},
                    }
                ),
                json.dumps({"status": "final", "message": "REA found two modules."}),
            ]
            self.prompts = []

        def generate(self, prompt, *, system=""):
            self.prompts.append(prompt)
            return self.responses.pop(0)

    provider = SequenceProvider()
    result = Orchestrator(provider, workspace=tmp_path).run("Inspect the Electron app")
    assert result.status == "completed"
    assert result.trace[0]["tool"] == "rea_analyze_app"
    assert '"modules": 2' in provider.prompts[1]


def test_rea_investigate_uses_allowlisted_command_and_returns_evidence(monkeypatch, tmp_path):
    app = tmp_path / "sample.bin"
    app.write_bytes(b"binary fixture")
    captured = {}

    class Completed:
        returncode = 0
        stdout = '{"functions":["main"],"evidence":[{"kind":"symbol"}]}'
        stderr = ""

    monkeypatch.setattr(rea, "_rea_executable", lambda: "/usr/bin/rea")
    monkeypatch.setattr(rea, "_child_environment", lambda: {"PATH": "/usr/bin"})

    def fake_bounded(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return {
            "returncode": 0,
            "stdout": Completed.stdout,
            "stderr": "",
            "timed_out": False,
            "output_limit_exceeded": False,
        }

    monkeypatch.setattr(rea, "_run_bounded", fake_bounded)
    result = rea.investigate_with_rea(
        tmp_path, "search", path="sample.bin", query="auth", provider="ghidra"
    )
    assert result["status"] == "completed"
    assert result["evidence"]["functions"] == ["main"]
    assert captured["argv"] == [
        "/usr/bin/rea",
        "search",
        str(app),
        "auth",
        "--provider",
        "ghidra",
        "--json",
    ]
    assert captured["timeout"] == 90
    assert result["target_executed"] is False


def test_rea_investigate_rejects_unknown_commands_and_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="Unsupported REA command"):
        rea.investigate_with_rea(tmp_path, "arbitrary-shell")
    with pytest.raises(PermissionError, match="inside the workspace"):
        rea.investigate_with_rea(tmp_path, "analyze", path="../outside")


def test_rea_investigate_requires_queries_for_search(tmp_path):
    (tmp_path / "binary.bin").write_bytes(b"fixture")
    with pytest.raises(ValueError, match="requires a query"):
        rea.investigate_with_rea(tmp_path, "search", path="binary.bin")


def test_orchestrator_can_call_rea_investigate(monkeypatch, tmp_path):
    from aurix.orchestrator import Orchestrator

    monkeypatch.setattr(
        "aurix.orchestrator.investigate_with_rea",
        lambda workspace, command, **kwargs: {
            "status": "completed",
            "tool": "rea",
            "command": command,
            "evidence": {"functions": ["main"]},
            "target_executed": False,
        },
    )

    class SequenceProvider:
        def __init__(self):
            self.responses = [
                json.dumps(
                    {
                        "status": "tool_call",
                        "tool": "rea_investigate",
                        "arguments": {"command": "function", "path": "app.bin", "query": "main"},
                    }
                ),
                json.dumps({"status": "final", "message": "REA identified main."}),
            ]
            self.prompts = []

        def generate(self, prompt, *, system=""):
            self.prompts.append(prompt)
            return self.responses.pop(0)

    provider = SequenceProvider()
    result = Orchestrator(provider, workspace=tmp_path).run("Inspect native app")
    assert result.status == "completed"
    assert result.trace[0]["tool"] == "rea_investigate"
    assert '"main"' in provider.prompts[1]



def test_rea_bounded_runner_terminates_on_output_budget(monkeypatch, tmp_path):
    class FakeStream:
        def __init__(self, chunks):
            self.chunks = iter(chunks)

        def read(self, size):
            return next(self.chunks, b"")

        def close(self):
            pass

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            self.stdout = FakeStream([b"x" * 4096, b""])
            self.stderr = FakeStream([b""])
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

        def kill(self):
            self.returncode = -9

    process = FakeProcess()
    monkeypatch.setattr(rea.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(rea, "MAX_STDOUT_CHARS", 100)
    monkeypatch.setattr(rea, "MAX_STDERR_CHARS", 10)
    result = rea._run_bounded(["rea"], cwd=tmp_path, env={}, timeout=1)
    assert len(result["stdout"]) <= 400
    assert result["output_limit_exceeded"] is True


def test_rea_static_analysis_reports_invalid_json_without_attribute_error(monkeypatch, tmp_path):
    (tmp_path / "app.asar").write_bytes(b"fixture")
    monkeypatch.setattr(rea, "_rea_executable", lambda: "rea")
    monkeypatch.setattr(rea, "_child_environment", dict)
    monkeypatch.setattr(
        rea,
        "_run_bounded",
        lambda *args, **kwargs: {
            "returncode": 0,
            "stdout": "not-json",
            "stderr": "",
            "timed_out": False,
            "output_limit_exceeded": False,
        },
    )

    result = rea.analyze_javascript_application(tmp_path, "app.asar")

    assert result["status"] == "invalid_output"
    assert result["output_format"] == "text"
    assert result["output"] == "not-json"


def test_rea_investigation_reports_invalid_json_without_attribute_error(monkeypatch, tmp_path):
    (tmp_path / "sample.bin").write_bytes(b"fixture")
    monkeypatch.setattr(rea, "_rea_executable", lambda: "rea")
    monkeypatch.setattr(rea, "_child_environment", dict)
    monkeypatch.setattr(
        rea,
        "_run_bounded",
        lambda *args, **kwargs: {
            "returncode": 0,
            "stdout": "not-json",
            "stderr": "",
            "timed_out": False,
            "output_limit_exceeded": False,
        },
    )

    result = rea.investigate_with_rea(tmp_path, "analyze", path="sample.bin")

    assert result["status"] == "invalid_output"
    assert result["output_format"] == "text"
    assert result["output"] == "not-json"


def test_rea_cli_reports_nonzero_exit_for_static_analysis(monkeypatch, tmp_path):
    (tmp_path / "app.asar").write_bytes(b"fixture")
    monkeypatch.setattr(rea, "_rea_executable", lambda: "rea")
    monkeypatch.setattr(rea, "_child_environment", dict)
    monkeypatch.setattr(
        rea,
        "_run_bounded",
        lambda *args, **kwargs: {
            "returncode": 7,
            "stdout": '{"partial":true}',
            "stderr": "provider failed",
            "timed_out": False,
            "output_limit_exceeded": False,
        },
    )

    result = rea.analyze_javascript_application(tmp_path, "app.asar")

    assert result["status"] == "failed"
    assert result["returncode"] == 7
    assert result["evidence"] == {"partial": True}
    assert result["stderr"] == "provider failed"


def test_rea_cli_reports_nonzero_exit_for_native_investigation(monkeypatch, tmp_path):
    (tmp_path / "sample.bin").write_bytes(b"fixture")
    monkeypatch.setattr(rea, "_rea_executable", lambda: "rea")
    monkeypatch.setattr(rea, "_child_environment", dict)
    monkeypatch.setattr(
        rea,
        "_run_bounded",
        lambda *args, **kwargs: {
            "returncode": 9,
            "stdout": '{"partial":true}',
            "stderr": "analysis failed",
            "timed_out": False,
            "output_limit_exceeded": False,
        },
    )

    result = rea.investigate_with_rea(tmp_path, "analyze", path="sample.bin")

    assert result["status"] == "failed"
    assert result["returncode"] == 9
    assert result["evidence"] == {"partial": True}
    assert result["stderr"] == "analysis failed"


def test_rea_cli_process_group_uses_posix_signals(monkeypatch):
    import os
    import signal

    if os.name != "posix":
        pytest.skip("POSIX process groups are not available")

    calls = []

    class Process:
        pid = 43211

        def terminate(self):
            raise AssertionError("process-group signaling should be used")

        def kill(self):
            raise AssertionError("process-group signaling should be used")

    monkeypatch.setattr(rea.os, "killpg", lambda pid, sig: calls.append((pid, sig)))

    rea._signal_process_group(Process())
    rea._signal_process_group(Process(), force=True)

    assert calls == [(43211, signal.SIGTERM), (43211, signal.SIGKILL)]


@pytest.mark.parametrize(
    "signal_tree",
    [rea._signal_process_group, rea_mcp._signal_process_tree],
    ids=["rea-cli-process-group", "rea-mcp-process-group"],
)
def test_posix_process_group_signal_reaches_real_descendant(signal_tree, tmp_path):
    import os
    import subprocess
    import sys
    import time

    if os.name != "posix":
        pytest.skip("POSIX process groups are not available")

    child_started = tmp_path / "child-started"
    child_terminated = tmp_path / "child-terminated"
    child_code = (
        "import signal,sys,time\n"
        "from pathlib import Path\n"
        f"marker=Path({str(child_terminated)!r})\n"
        "def stop(signum, frame):\n"
        " marker.write_text('received', encoding='utf-8')\n"
        " raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        f"Path({str(child_started)!r}).write_text('ready', encoding='utf-8')\n"
        "while True: time.sleep(0.05)\n"
    )
    parent_code = (
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        "while True: time.sleep(0.05)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        while not child_started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_started.exists(), "descendant did not start in time"

        signal_tree(process)

        process.wait(timeout=3)
        deadline = time.monotonic() + 3
        while not child_terminated.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_terminated.exists(), "SIGTERM did not reach the descendant process"
    finally:
        try:
            os.killpg(process.pid, __import__("signal").SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)



def test_rea_real_stdout_and_stderr_flood_is_bounded_and_reaped(monkeypatch, tmp_path):
    import subprocess
    import sys

    monkeypatch.setattr(rea, "MAX_STDOUT_CHARS", 128)
    monkeypatch.setattr(rea, "MAX_STDERR_CHARS", 64)
    real_popen = subprocess.Popen
    launched = []

    def capture_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(rea.subprocess, "Popen", capture_popen)
    script = "import os\nwhile True:\n os.write(1, b'O' * 4096)\n os.write(2, b'E' * 4096)\n"
    result = rea._run_bounded(
        [sys.executable, "-c", script], cwd=tmp_path, env={}, timeout=5
    )

    assert result["output_limit_exceeded"] is True
    assert result["timed_out"] is False
    assert len(result["stdout"].encode("utf-8")) <= 128 * 4
    assert len(result["stderr"].encode("utf-8")) <= 64 * 4
    assert launched and launched[0].poll() is not None


def test_rea_real_silent_process_times_out_and_is_reaped(monkeypatch, tmp_path):
    import subprocess
    import sys

    real_popen = subprocess.Popen
    launched = []

    def capture_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(rea.subprocess, "Popen", capture_popen)
    result = rea._run_bounded(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        env={},
        timeout=1,
    )

    assert result["timed_out"] is True
    assert result["output_limit_exceeded"] is False
    assert launched and launched[0].poll() is not None


@pytest.mark.parametrize("relative_path", [".env", ".git/config", ".ssh/id_rsa", ".aurix/transaction.json"])
def test_rea_static_analysis_rejects_ignored_or_sensitive_targets(tmp_path, relative_path):
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("sensitive fixture", encoding="utf-8")

    with pytest.raises(PermissionError, match="ignored or sensitive"):
        rea.analyze_javascript_application(tmp_path, relative_path)


@pytest.mark.parametrize("relative_path", [".env", ".git/config", ".ssh/id_rsa", ".aurix/transaction.json"])
def test_rea_investigation_rejects_ignored_or_sensitive_targets(tmp_path, relative_path):
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("sensitive fixture", encoding="utf-8")

    with pytest.raises(PermissionError, match="ignored or sensitive"):
        rea.investigate_with_rea(tmp_path, "analyze", path=relative_path)


def test_rea_directory_staging_excludes_secrets_ignored_dirs_and_symlinks(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "main.js").write_text("console.log('safe')", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("secret", encoding="utf-8")
    (root / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (root / ".aurix").mkdir()
    (root / ".aurix" / "transaction.json").write_text("private", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "package.js").write_text("ignored", encoding="utf-8")
    outside = tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    try:
        (root / "linked.js").symlink_to(outside)
    except (OSError, NotImplementedError):
        pass
    staged_temp, staged = rea._stage_safe_directory(root)
    try:
        assert (staged / "src" / "main.js").read_text(encoding="utf-8") == "console.log('safe')"
        assert not (staged / ".env").exists()
        assert not (staged / ".git").exists()
        assert not (staged / ".aurix").exists()
        assert not (staged / "node_modules").exists()
        assert not (staged / "linked.js").exists()
    finally:
        staged_temp.cleanup()


def test_rea_directory_staging_enforces_file_budget(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "one.js").write_text("x", encoding="utf-8")
    monkeypatch.setattr(rea, "MAX_STAGED_FILES", 0)
    with pytest.raises(ValueError, match="staging exceeded"):
        rea._stage_safe_directory(root)