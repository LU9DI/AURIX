import subprocess

from aurix.tools.review import review_proposal


def make_repo(tmp_path, added_line):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "aurix-test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "AURIX tests"], check=True)
    (root / "app.py").write_text("value = 'old'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "initial"], check=True, capture_output=True)
    proposal_id = "a1b2c3d4e5f6"
    proposal_dir = root / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    patch = f"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 'old'\n+{added_line}\n"
    (proposal_dir / f"{proposal_id}.diff").write_text(patch, encoding="utf-8")
    return root, proposal_id


def test_review_flags_dynamic_execution(tmp_path):
    root, proposal_id = make_repo(tmp_path, "result = eval(user_input)")
    result = review_proposal(root, proposal_id)
    assert result["risk_level"] == "high"
    assert result["apply_permitted_by_review"] is False
    assert any(item["rule"] == "dynamic-code" for item in result["findings"])


def test_review_reports_low_risk_but_keeps_manual_review_required(tmp_path):
    root, proposal_id = make_repo(tmp_path, "value = 'new'")
    result = review_proposal(root, proposal_id)
    assert result["risk_level"] == "low"
    assert result["finding_count"] == 0
    assert result["status"] == "review_required"


def test_review_does_not_scan_removed_lines(tmp_path):
    root, proposal_id = make_repo(tmp_path, "value = 'new'")
    patch = ("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-thing = eval(user_input)\n+value = 'new'\n")
    (root / ".aurix" / "proposals" / f"{proposal_id}.diff").write_text(patch, encoding="utf-8")
    result = review_proposal(root, proposal_id)
    assert result["finding_count"] == 0


def test_review_rejects_unknown_proposal(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        review_proposal(tmp_path, "a1b2c3d4e5f6")
