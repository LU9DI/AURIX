import json
import subprocess

import pytest

from aurix.orchestrator import Orchestrator
from aurix.tools.git_inspection import git_diff, git_status


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(path):
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "aurix-test@example.invalid")
    _git(path, "config", "user.name", "AURIX Test")
    (path / "app.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
    _git(path, "add", "app.py")
    _git(path, "commit", "-qm", "initial")
    return path


def test_git_status_reports_tracked_and_untracked_changes(tmp_path):
    repo = _repo(tmp_path / "repo")
    (repo / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    (repo / "new.py").write_text("pass\n", encoding="utf-8")
    result = git_status(repo)
    assert result["status"] == "completed"
    assert "app.py" in result["output"]
    assert "new.py" in result["output"]


def test_git_diff_reads_only_diff_and_supports_staged(tmp_path):
    repo = _repo(tmp_path / "repo")
    (repo / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    unstaged = git_diff(repo)
    assert "-    return 'hello'" in unstaged["output"]
    assert "+    return 'hi'" in unstaged["output"]
    _git(repo, "add", "app.py")
    staged = git_diff(repo, staged=True)
    assert staged["staged"] is True
    assert "return 'hi'" in staged["output"]


def test_git_tools_refuse_workspace_nested_inside_another_repo(tmp_path):
    outer = _repo(tmp_path / "outer")
    nested = outer / "nested"
    nested.mkdir()
    with pytest.raises(PermissionError, match="repository root"):
        git_status(nested)


def test_orchestrator_can_request_git_status(tmp_path):
    repo = _repo(tmp_path / "repo")

    class Provider:
        def __init__(self):
            self.responses = [
                json.dumps({"status": "tool_call", "tool": "git_status", "arguments": {}}),
                json.dumps({"status": "final", "message": "Inspected Git status."}),
            ]
            self.prompts = []

        def generate(self, prompt, *, system=""):
            self.prompts.append(prompt)
            return self.responses.pop(0)

    provider = Provider()
    result = Orchestrator(provider, workspace=repo).run("Check the repository status")
    assert result.status == "completed"
    assert result.trace[0]["tool"] == "git_status"
    assert "## No commits yet" not in provider.prompts[1]
    assert '"tool": "git_status"' in provider.prompts[1]
