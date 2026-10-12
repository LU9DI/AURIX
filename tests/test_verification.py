import subprocess

import pytest

from aurix.tools.verification import verify_proposal


def make_repo(tmp_path, *, expected="new"):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "aurix-test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "AURIX tests"], check=True)
    (root / "app.py").write_text("value = 'old'\n", encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text(
        f"from app import value\n\ndef test_value():\n    assert value == '{expected}'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(root), "add", "app.py", "tests/test_app.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "initial"], check=True, capture_output=True)
    proposal_dir = root / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal_id = "a1b2c3d4e5f6"
    patch = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 'old'\n+value = 'new'\n"
    (proposal_dir / f"{proposal_id}.diff").write_text(patch, encoding="utf-8")
    return root, proposal_id


def test_verify_requires_explicit_confirmation(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    with pytest.raises(PermissionError, match="confirmation"):
        verify_proposal(root, proposal_id)


def test_verify_runs_in_worktree_and_preserves_primary_checkout(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    result = verify_proposal(root, proposal_id, confirm=True, suite="pytest")
    assert result["status"] == "verified_pass"
    assert result["test_result"]["passed"] is True
    assert result["proposal_sha256"]
    assert len(result["base_commit"]) == 40
    assert len(result["evidence_sha256"]) == 64
    assert result["primary_workspace_modified"] is False
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                            check=True, capture_output=True, text=True)
    assert status.stdout == ""
    worktrees = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain"],
                               check=True, capture_output=True, text=True)
    assert worktrees.stdout.count("worktree ") == 1


def test_verify_reports_failed_tests_without_changing_checkout(tmp_path):
    root, proposal_id = make_repo(tmp_path, expected="never-matches")
    result = verify_proposal(root, proposal_id, confirm=True, suite="pytest")
    assert result["status"] == "verified_fail"
    assert result["test_result"]["passed"] is False
    assert "old" in (root / "app.py").read_text(encoding="utf-8")


def test_verify_refuses_dirty_tracked_worktree(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    (root / "app.py").write_text("local changes\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="tracked changes"):
        verify_proposal(root, proposal_id, confirm=True)


def test_verify_compares_baseline_and_detects_improvement(tmp_path):
    root, proposal_id = make_repo(tmp_path, expected="new")
    result = verify_proposal(root, proposal_id, confirm=True, suite="pytest")
    assert result["baseline_result"]["passed"] is False
    assert result["test_result"]["passed"] is True
    assert result["regression_status"] == "improved"


def test_verify_detects_regression_against_passing_baseline(tmp_path):
    root, proposal_id = make_repo(tmp_path, expected="old")
    result = verify_proposal(root, proposal_id, confirm=True, suite="pytest")
    assert result["baseline_result"]["passed"] is True
    assert result["test_result"]["passed"] is False
    assert result["regression_status"] == "introduced_failure"


def test_verify_can_skip_baseline_comparison(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    result = verify_proposal(root, proposal_id, confirm=True, suite="pytest", compare_baseline=False)
    assert result["baseline_result"] is None
    assert result["regression_status"] == "not_compared"


def test_auto_suite_falls_back_to_full_suite_without_manifest(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    result = verify_proposal(root, proposal_id, confirm=True, suite="auto")
    assert result["status"] == "verified_pass"
    assert result["suite"] == "pytest"
    assert result["requested_suite"] == "auto"
    assert result["test_selection"]["mode"] == "full_suite"
    assert "fallback" in result["test_selection"]["reason"].lower()


def test_auto_suite_uses_only_explicit_complete_test_map(tmp_path):
    import json
    root, proposal_id = make_repo(tmp_path)
    metadata = root / ".aurix"
    (metadata / "test-map.json").write_text(json.dumps({
        "version": 1,
        "mappings": {"app.py": ["tests/test_app.py"]},
    }), encoding="utf-8")
    result = verify_proposal(root, proposal_id, confirm=True, suite="auto")
    assert result["status"] == "verified_pass"
    assert result["test_selection"]["mode"] == "mapped_subset"
    assert result["test_selection"]["paths"] == ["tests/test_app.py"]


def test_auto_suite_falls_back_when_any_changed_target_is_unmapped(tmp_path):
    import json
    root, proposal_id = make_repo(tmp_path)
    metadata = root / ".aurix"
    (metadata / "test-map.json").write_text(json.dumps({"version": 1, "mappings": {}}), encoding="utf-8")
    result = verify_proposal(root, proposal_id, confirm=True, suite="auto")
    assert result["test_selection"]["mode"] == "full_suite"
    assert "No explicit test mapping" in result["test_selection"]["reason"]
