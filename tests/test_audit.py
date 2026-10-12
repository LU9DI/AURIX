from __future__ import annotations

import hashlib
import json
import subprocess

from aurix import audit as audit_module
from aurix.audit import audit_proposal


def _repo_with_proposal(tmp_path, added_line="value = 'new'"):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "aurix-test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "AURIX tests"], check=True)
    (root / "app.py").write_text("value = 'old'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "initial"], check=True, capture_output=True
    )
    proposal_id = "a1b2c3d4e5f6"
    proposal_dir = root / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    patch = f"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 'old'\n+{added_line}\n"
    (proposal_dir / f"{proposal_id}.diff").write_text(patch, encoding="utf-8")
    return root, proposal_id


def _mock_verification(root, proposal_id):
    patch = (root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_bytes()
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    evidence = {
        "proposal_id": proposal_id,
        "proposal_sha256": hashlib.sha256(patch).hexdigest(),
        "base_commit": head,
        "target_state_sha256": __import__(
            "aurix.tools.patches", fromlist=["_target_state_digest"]
        )._target_state_digest(
            __import__(
                "aurix.tools.patches", fromlist=["_target_state_snapshot"]
            )._target_state_snapshot(root, ["app.py"])
        ),
        "suite": "pytest",
        "isolation": "trusted",
        "sandbox_image": None,
        "sandbox_image_id": None,
        "runtime_fingerprint": {
            "python_version": "3.test",
            "python_implementation": "CPython",
            "system": "TestOS",
            "release": "1",
            "machine": "test",
        },
        "baseline_result": {"passed": True, "returncode": 0},
        "test_result": {"passed": True, "returncode": 0},
        "regression_status": "clean",
    }
    return {
        **evidence,
        "status": "verified_pass",
        "primary_workspace_modified": False,
        "evidence_sha256": hashlib.sha256(
            json.dumps(
                evidence,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }


def test_audit_does_not_run_verification_without_confirmation(tmp_path, monkeypatch):
    root, proposal_id = _repo_with_proposal(tmp_path)

    def forbidden_verify(*args, **kwargs):
        raise AssertionError("verification must not run without confirmation")

    monkeypatch.setattr(audit_module, "verify_proposal", forbidden_verify)
    result = audit_proposal(root, proposal_id)
    assert result["status"] == "reviewed_verification_not_run"
    assert result["verification"]["status"] == "not_run"
    assert result["application"] == {"performed": False, "permitted_by_review": False}
    assert len(result["proposal_sha256"]) == 64
    assert result["audited_at"]


def test_audit_reports_pass_only_for_low_risk_and_passing_verification(tmp_path, monkeypatch):
    root, proposal_id = _repo_with_proposal(tmp_path)
    monkeypatch.setattr(
        audit_module, "verify_proposal", lambda *a, **kw: _mock_verification(root, proposal_id)
    )
    result = audit_proposal(root, proposal_id, confirm_verify=True)
    assert result["status"] == "audit_passed"
    assert result["verification"]["status"] == "verified_pass"
    assert result["application"]["performed"] is False


def test_audit_high_risk_never_reports_audit_passed(tmp_path, monkeypatch):
    root, proposal_id = _repo_with_proposal(tmp_path, "result = eval(user_input)")
    monkeypatch.setattr(
        audit_module, "verify_proposal", lambda *a, **kw: _mock_verification(root, proposal_id)
    )
    result = audit_proposal(root, proposal_id, confirm_verify=True)
    assert result["review"]["risk_level"] == "high"
    assert result["status"] == "audit_needs_attention"


def test_audit_record_is_bound_to_exact_patch_digest(tmp_path, monkeypatch):
    import hashlib
    import json

    root, proposal_id = _repo_with_proposal(tmp_path)
    monkeypatch.setattr(
        audit_module, "verify_proposal", lambda *a, **kw: _mock_verification(root, proposal_id)
    )
    result = audit_proposal(root, proposal_id, confirm_verify=True)
    saved = json.loads((root / ".aurix" / "audits" / f"{proposal_id}.json").read_text())
    actual = hashlib.sha256(
        (root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_bytes()
    ).hexdigest()
    assert result["status"] == "audit_passed"
    assert saved["proposal_sha256"] == actual
    assert saved["status"] == "audit_passed"


def test_audit_refuses_to_record_if_patch_changes_during_review(tmp_path, monkeypatch):
    root, proposal_id = _repo_with_proposal(tmp_path)
    original_review = audit_module.review_proposal

    def mutate_after_review(workspace, pid):
        result = original_review(workspace, pid)
        patch = root / ".aurix" / "proposals" / f"{pid}.diff"
        patch.write_text(patch.read_text() + "# changed\n", encoding="utf-8")
        return result

    monkeypatch.setattr(audit_module, "review_proposal", mutate_after_review)
    try:
        audit_proposal(root, proposal_id)
    except PermissionError as exc:
        assert "changed during audit" in str(exc)
    else:
        raise AssertionError("stale audit evidence must be refused")
    assert not (root / ".aurix" / "audits" / f"{proposal_id}.json").exists()


def test_audit_contains_independent_digest_bound_review_tracks(tmp_path, monkeypatch):
    import hashlib

    root, proposal_id = _repo_with_proposal(tmp_path)
    monkeypatch.setattr(
        audit_module, "verify_proposal", lambda *a, **kw: _mock_verification(root, proposal_id)
    )
    result = audit_proposal(root, proposal_id, confirm_verify=True)
    digest = hashlib.sha256(
        (root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_bytes()
    ).hexdigest()
    assert result["schema_version"] == 9
    assert result["target_state"][0]["path"] == "app.py"
    assert result["target_state_sha256"] == result["verification"].get(
        "target_state_sha256", result["target_state_sha256"]
    )
    assert result["review_tracks"]["security"]["integrity"]["sha256"] == digest
    assert result["review_tracks"]["correctness"]["proposal_sha256"] == digest
    assert result["status"] == "audit_passed"


def test_correctness_findings_prevent_passing_audit(tmp_path, monkeypatch):
    root, proposal_id = _repo_with_proposal(tmp_path, "except Exception:\n    pass")
    monkeypatch.setattr(
        audit_module, "verify_proposal", lambda *a, **kw: _mock_verification(root, proposal_id)
    )
    result = audit_proposal(root, proposal_id, confirm_verify=True)
    assert result["review_tracks"]["correctness"]["finding_count"] > 0
    assert result["review_tracks"]["correctness"]["risk_level"] == "medium"
    assert result["status"] == "audit_needs_attention"


def test_review_findings_are_bound_to_exact_added_line_evidence(tmp_path):
    from aurix.tools.review import review_proposal

    root, proposal_id = _repo_with_proposal(tmp_path, "result = eval(user_input)")
    result = review_proposal(root, proposal_id)
    finding = next(item for item in result["findings"] if item["rule"] == "dynamic-code")
    evidence = finding["evidence"]
    patch = (
        (root / ".aurix" / "proposals" / f"{proposal_id}.diff")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    import hashlib

    assert result["evidence_schema"] == 1
    assert evidence["patch_sha256"] == result["proposal_sha256"]
    assert patch[evidence["patch_line"] - 1][1:] == finding["sample"]
    assert (
        evidence["line_sha256"]
        == hashlib.sha256(patch[evidence["patch_line"] - 1][1:].encode()).hexdigest()
    )
    assert evidence["source_line"] == 1


def test_audit_refuses_to_record_if_target_changes_during_review(tmp_path, monkeypatch):
    root, proposal_id = _repo_with_proposal(tmp_path)
    original_review = audit_module.review_proposal

    def mutate_target_during_review(workspace, pid):
        result = original_review(workspace, pid)
        (root / "app.py").write_text("value = 'external edit'\n", encoding="utf-8")
        return result

    monkeypatch.setattr(audit_module, "review_proposal", mutate_target_during_review)
    try:
        audit_proposal(root, proposal_id)
    except PermissionError as exc:
        assert "target files changed during audit" in str(exc)
    else:
        raise AssertionError("stale target-state evidence must be refused")
    assert not (root / ".aurix" / "audits" / f"{proposal_id}.json").exists()
