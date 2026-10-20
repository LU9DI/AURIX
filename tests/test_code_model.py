import json

import pytest

from aurix.orchestrator import Orchestrator
from aurix.tools.code_model import analyze_python_code


def test_python_code_model_extracts_symbols_imports_calls_and_hash(tmp_path):
    (tmp_path / "pkg").mkdir()
    source = "import json\n\ndef build(value):\n    return json.dumps(value)\n\nclass Worker:\n    pass\n"
    (tmp_path / "pkg" / "sample.py").write_text(source, encoding="utf-8")

    result = analyze_python_code(tmp_path)

    assert result["status"] == "completed"
    assert result["analysis_level"] == "python_ast_syntax"
    assert result["execution_performed"] is False
    assert result["files_analyzed"] == 1
    assert len(result["files"][0]["sha256"]) == 64
    assert {item["name"] for item in result["symbols"]} == {"build", "Worker"}
    assert any(edge["kind"] == "imports" and edge["target"] == "json" for edge in result["relations"])
    assert any(edge["kind"] == "calls" and edge["target"] == "json.dumps" for edge in result["relations"])
    assert "not resolved runtime edges" in result["limitations"][0]


def test_python_code_model_reports_syntax_error_without_execution(tmp_path):
    (tmp_path / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    result = analyze_python_code(tmp_path)

    assert result["files"][0]["status"] == "syntax_error"
    assert result["errors"][0]["kind"] == "syntax_error"
    assert result["execution_performed"] is False


def test_python_code_model_rejects_path_escape_and_bad_limit(tmp_path):
    with pytest.raises(PermissionError):
        analyze_python_code(tmp_path, path="../outside")
    with pytest.raises(ValueError):
        analyze_python_code(tmp_path, max_files=True)


def test_python_code_model_does_not_follow_symlinked_directory(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("def leaked(): pass\n", encoding="utf-8")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on this platform")

    result = analyze_python_code(root)

    assert result["files_analyzed"] == 0
    assert result["symbols"] == []


def test_python_code_model_marks_oversized_source_without_partial_parse(tmp_path):
    from aurix.tools.code_model import MAX_SOURCE_CHARS

    (tmp_path / "large.py").write_text("x = 1\n" * (MAX_SOURCE_CHARS // 6 + 2), encoding="utf-8")
    result = analyze_python_code(tmp_path)

    assert result["files"][0]["status"] == "source_limit_exceeded"
    assert result["errors"][0]["kind"] == "source_limit_exceeded"
    assert result["symbols"] == []


def test_orchestrator_can_call_python_code_model_and_continue(tmp_path):
    (tmp_path / "module.py").write_text("def greet(name):\n    return str(name)\n", encoding="utf-8")

    class SequenceProvider:
        def __init__(self):
            self.responses = [
                json.dumps({"status": "tool_call", "tool": "analyze_python_code", "arguments": {}}),
                json.dumps({"status": "final", "message": "The module defines greet."}),
            ]
            self.prompts = []

        def generate(self, prompt, *, system=""):
            self.prompts.append(prompt)
            return self.responses.pop(0)

    provider = SequenceProvider()
    result = Orchestrator(provider, workspace=tmp_path).run("Inspect Python structure")

    assert result.status == "completed"
    assert result.trace[0]["tool"] == "analyze_python_code"
    assert '"greet"' in provider.prompts[1]
