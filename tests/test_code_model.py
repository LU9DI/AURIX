import json

import pytest

from aurix.orchestrator import Orchestrator
from aurix.tools.code_model import analyze_python_code
from aurix.tools.structural_graph import compare_graph_snapshots


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



def test_python_graph_resolves_local_imports_and_reports_cycles(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "a.py").write_text("from .b import run\ndef start(): return run()\n", encoding="utf-8")
    (package / "b.py").write_text("from .a import start\ndef run(): return start()\n", encoding="utf-8")
    (package / "external.py").write_text(
        "import package_not_in_workspace\\ndef helper(): return 1\\ndef caller(): return helper()\\n",
        encoding="utf-8",
    )

    result = analyze_python_code(tmp_path)
    graph = result["graph"]

    assert {(edge["source"], edge["target"]) for edge in graph["edges"]} == {
        ("pkg.a", "pkg.b"),
        ("pkg.b", "pkg.a"),
    }
    assert graph["cycles"] == [["pkg.a", "pkg.b"]]
    assert any(item["target"] == "package_not_in_workspace" for item in graph["unresolved_imports"])
    assert any(
        item["target_symbol"] == "pkg.external.helper"
        for item in graph["resolved_calls"]
    )


def test_incremental_graph_comparison_invalidates_transitive_dependents():
    previous = {
        "nodes": [
            {"module": "pkg.a", "path": "pkg/a.py", "sha256": "old-a"},
            {"module": "pkg.b", "path": "pkg/b.py", "sha256": "same-b"},
            {"module": "pkg.c", "path": "pkg/c.py", "sha256": "same-c"},
        ],
        "edges": [
            {"kind": "imports", "source": "pkg.b", "target": "pkg.a"},
            {"kind": "imports", "source": "pkg.c", "target": "pkg.b"},
        ],
    }
    current = {
        "nodes": [
            {"module": "pkg.a", "path": "pkg/a.py", "sha256": "new-a"},
            {"module": "pkg.b", "path": "pkg/b.py", "sha256": "same-b"},
            {"module": "pkg.c", "path": "pkg/c.py", "sha256": "same-c"},
        ],
        "edges": previous["edges"],
    }

    result = compare_graph_snapshots(previous, current)

    assert result["changed_files"] == ["pkg/a.py"]
    assert result["affected_modules"] == ["pkg.a", "pkg.b", "pkg.c"]
    assert result["invalidated_files"] == ["pkg/a.py", "pkg/b.py", "pkg/c.py"]



def test_incremental_graph_comparison_invalidates_deleted_modules():
    previous = {
        "nodes": [
            {"module": "pkg.a", "path": "pkg/a.py", "sha256": "old-a"},
            {"module": "pkg.b", "path": "pkg/b.py", "sha256": "same-b"},
        ],
        "edges": [{"kind": "imports", "source": "pkg.b", "target": "pkg.a"}],
    }
    current = {
        "nodes": [{"module": "pkg.b", "path": "pkg/b.py", "sha256": "same-b"}],
        "edges": [],
    }

    result = compare_graph_snapshots(previous, current)

    assert result["removed_files"] == ["pkg/a.py"]
    assert "pkg/a.py" in result["invalidated_files"]
    assert "pkg/b.py" in result["invalidated_files"]
