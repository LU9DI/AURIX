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

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr(rea.subprocess, "run", fake_run)
    result = rea.analyze_javascript_application(tmp_path, "desktop-app")

    assert result["status"] == "completed"
    assert result["evidence"]["modules"] == 3
    assert captured["argv"] == ["/usr/local/bin/rea", "analyze-javascript-application", str(app), "--json"]
    assert captured["shell"] is False
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
    monkeypatch.setattr(rea, "_child_environment", lambda: {})
    captured = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output="partial")

    monkeypatch.setattr(rea.subprocess, "run", fake_run)
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
            "status": "completed", "tool": "rea", "target": relative_path,
            "evidence": {"modules": 2, "imports": []}, "application_executed": False,
        },
    )

    class SequenceProvider:
        def __init__(self):
            self.responses = [
                json.dumps({"status": "tool_call", "tool": "rea_analyze_app", "arguments": {"path": "electron"}}),
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
    assert "\"modules\": 2" in provider.prompts[1]


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

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr(rea.subprocess, "run", fake_run)
    result = rea.investigate_with_rea(tmp_path, "search", path="sample.bin", query="auth", provider="ghidra")
    assert result["status"] == "completed"
    assert result["evidence"]["functions"] == ["main"]
    assert captured["argv"] == ["/usr/bin/rea", "search", str(app), "auth", "--provider", "ghidra", "--json"]
    assert captured["shell"] is False
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
            "status": "completed", "tool": "rea", "command": command,
            "evidence": {"functions": ["main"]}, "target_executed": False,
        },
    )

    class SequenceProvider:
        def __init__(self):
            self.responses = [
                json.dumps({"status": "tool_call", "tool": "rea_investigate", "arguments": {
                    "command": "function", "path": "app.bin", "query": "main"}}),
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
