import json
import subprocess

import pytest

from aurix.tools import rea


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
    assert captured["argv"] == [
        "/usr/local/bin/rea",
        "analyze-javascript-application",
        str(app),
        "--json",
    ]
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
