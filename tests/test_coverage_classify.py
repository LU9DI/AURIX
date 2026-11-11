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


def test_safe_origin_removes_embedded_credentials():
    runner_path = Path(__file__).resolve().parents[1] / "research" / "coverage-study" / "run_study.py"
    runner_spec = importlib.util.spec_from_file_location("coverage_run_study_safe_origin", runner_path)
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)

    assert runner.safe_origin("https://user:secret@github.com/org/repo.git") == "https://github.com/org/repo.git"
    assert runner.safe_origin("https://github.com/org/repo.git") == "https://github.com/org/repo.git"
    assert runner.safe_origin("https://github.com/org/repo.git?token=secret#fragment") == "https://github.com/org/repo.git"
    assert runner.safe_origin("https://user:secret@[2001:db8::1]:8443/org/repo.git") == "https://[2001:db8::1]:8443/org/repo.git"
    assert runner.safe_origin("git@github.com:org/repo.git") == "git@github.com:org/repo.git"


def test_study_runner_records_snapshot_provenance(tmp_path):
    import importlib.util
    import json
    import subprocess

    runner_path = Path(__file__).resolve().parents[1] / "research" / "coverage-study" / "run_study.py"
    runner_spec = importlib.util.spec_from_file_location("coverage_run_study", runner_path)
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)

    repo = tmp_path / "repo-provenance"
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

    output = tmp_path / "results.jsonl"
    runner.main(["run_study.py", str(output), str(repo)])
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 1
    row = rows[0]
    expected_commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert row["snapshot_commit"] == expected_commit
    assert row["origin_url"] is None
    assert row["is_shallow"] is False
    assert row["history_depth_commits"] == 2
    assert len(row["classifier_sha256"]) == 64
    assert row["hunks"] > 0


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


def test_study_runner_preserves_existing_output_on_invalid_snapshot(tmp_path):
    import subprocess
    import pytest

    runner_path = Path(__file__).resolve().parents[1] / "research" / "coverage-study" / "run_study.py"
    runner_spec = importlib.util.spec_from_file_location("coverage_run_study_atomic", runner_path)
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)

    output = tmp_path / "results.jsonl"
    output.write_text("previous valid results\\n", encoding="utf-8")
    invalid_repo = tmp_path / "not-a-repository"
    invalid_repo.mkdir()

    with pytest.raises(subprocess.CalledProcessError):
        runner.main(["run_study.py", str(output), str(invalid_repo)])
    assert output.read_text(encoding="utf-8") == "previous valid results\\n"
