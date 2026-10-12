import json

from aurix.orchestrator import Orchestrator
from aurix.tools.project_map import inspect_project


class SequenceProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt, *, system=""):
        self.prompts.append(prompt)
        return self.responses.pop(0)


def test_project_map_detects_ecosystem_tests_ci_and_script_names(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "node dangerous.js", "build": "echo x"}}), encoding="utf-8"
    )
    (tmp_path / "src" / "app.ts").write_text("export const x = 1", encoding="utf-8")
    (tmp_path / "tests" / "app.test.ts").write_text("", encoding="utf-8")
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("", encoding="utf-8")
    result = inspect_project(tmp_path)
    assert result["status"] == "completed"
    assert "javascript" in result["ecosystems"]
    assert "package.json" in result["manifests"]
    assert "tests/app.test.ts" in result["test_files"]
    assert ".github/workflows/ci.yml" in result["ci_configuration"]
    assert result["package_script_names"]["package.json"] == ["build", "test"]
    assert result["execution_performed"] is False
    assert "node dangerous.js" not in json.dumps(result)


def test_project_map_does_not_follow_symlinked_directory(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "package.json").write_text('{"scripts":{"test":"echo secret"}}', encoding="utf-8")
    (root / "vendor-link").symlink_to(outside, target_is_directory=True)
    result = inspect_project(root)
    assert result["manifests"] == []
    assert result["package_script_names"] == {}


def test_orchestrator_can_use_project_map_and_continue(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    provider = SequenceProvider(
        json.dumps({"status": "tool_call", "tool": "inspect_project", "arguments": {}}),
        json.dumps({"status": "final", "message": "The project uses Python."}),
    )
    result = Orchestrator(provider, workspace=tmp_path).run("Map the project")
    assert result.status == "completed"
    assert '"python"' in provider.prompts[1]
    assert result.trace[0]["tool"] == "inspect_project"
