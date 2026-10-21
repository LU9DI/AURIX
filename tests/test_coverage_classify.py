import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "research" / "coverage-study" / "classify.py"
SPEC = importlib.util.spec_from_file_location("coverage_classify", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CLASSIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLASSIFIER)


def test_classifier_can_be_imported_without_running_cli():
    assert callable(CLASSIFIER.classify)
    assert callable(CLASSIFIER.hunks)


def test_classifier_identifies_documentation_and_non_code():
    assert CLASSIFIER.classify("README.md", ["old"], ["new"]) == "docs"
    assert CLASSIFIER.classify("assets/logo.svg", ["old"], ["new"]) == "outro"


def test_classifier_identifies_simple_deterministic_shapes():
    assert CLASSIFIER.classify("src/app.py", ["import os"], ["import sys"]) == "import"
    assert CLASSIFIER.classify("src/app.py", ["# old note"], ["# new note"]) == "comentario"
    assert CLASSIFIER.classify("src/app.py", ["unused = 1"], []) == "remocao_pura"


def test_classifier_does_not_call_new_logic_deterministic():
    assert CLASSIFIER.classify("src/app.py", ["return old_value"], ["return calculate(value)"]) == "logica_nova"


def test_hunks_rejects_non_git_directory(tmp_path):
    import subprocess

    invalid_repo = tmp_path / "not-a-repository"
    invalid_repo.mkdir()
    try:
        list(CLASSIFIER.hunks(str(invalid_repo)))
    except subprocess.CalledProcessError as exc:
        assert exc.returncode != 0
    else:
        raise AssertionError("hunks() must not treat git failures as an empty history")


def test_hunks_preserves_removed_file_changes(tmp_path):
    import subprocess

    repo = tmp_path / "repo-delete"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "aurix-test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "AURIX test"], check=True)
    source = repo / "removed.py"
    source.write_text("def obsolete():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "removed.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    source.unlink()
    subprocess.run(["git", "-C", str(repo), "add", "-u"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "remove module"], check=True)

    rows = list(CLASSIFIER.hunks(str(repo)))
    removed = [row for row in rows if row[1] == "remove module"]
    assert len(removed) == 1
    _, message, path, deleted, added = removed[0]
    assert message == "remove module"
    assert path == "removed.py"
    assert deleted == ["def obsolete():", "    return True"]
    assert added == []


def test_hunks_extracts_changes_from_git_history(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "aurix-test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "AURIX test"], check=True)
    source = repo / "module.py"
    source.write_text("def before():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "module.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    source.write_text("def after():\n    return 2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-am", "change"], check=True, capture_output=True)

    rows = list(CLASSIFIER.hunks(str(repo)))

    # Git history includes the initial commit's file-addition hunk as well.
    changed = [row for row in rows if row[1] == "change"]
    assert len(changed) == 1
    _, message, path, deleted, added = changed[0]
    assert message == "change"
    assert path == "module.py"
    assert deleted == ["def before():", "    return 1"]
    assert added == ["def after():", "    return 2"]
