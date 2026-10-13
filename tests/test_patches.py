from pathlib import Path
import hashlib
import json
import subprocess

import pytest

from aurix.tools.patches import (
    _workspace_operation_lock,
    apply_proposal,
    finalize_interrupted_recovery,
    inspect_transactions,
    plan_transaction_recovery,
    recover_transaction,
    revert_proposal,
    verify_recovery_histories,
)


def make_repo(tmp_path):
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
    proposal_dir = root / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal_id = "a1b2c3d4e5f6"
    patch = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 'old'\n+value = 'new'\n"
    (proposal_dir / f"{proposal_id}.diff").write_text(patch, encoding="utf-8")
    return root, proposal_id


def test_apply_requires_explicit_confirmation(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    with pytest.raises(PermissionError, match="confirmation"):
        apply_proposal(root, proposal_id)
    assert "old" in (root / "app.py").read_text(encoding="utf-8")


def test_apply_and_revert_reviewed_proposal(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    result = apply_proposal(root, proposal_id, confirm=True)
    assert result["status"] == "applied"
    assert "new" in (root / "app.py").read_text(encoding="utf-8")
    reverted = revert_proposal(root, proposal_id, confirm=True)
    assert reverted["status"] == "reverted"
    assert "old" in (root / "app.py").read_text(encoding="utf-8")


def test_revert_updates_transaction_journal_to_terminal_state(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"

    result = revert_proposal(root, proposal_id, confirm=True)

    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert result["transaction"] == "reverted_and_audited"
    assert journal["state"] == "reverted_and_audited"
    assert journal["recovery"] == "verified"
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"
    report = inspect_transactions(root)
    assert report["status"] == "inspected"
    assert report["transactions"][0]["status"] == "consistent_terminal_record"


def test_apply_refuses_dirty_tracked_worktree(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    (root / "app.py").write_text("user edit\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="tracked changes"):
        apply_proposal(root, proposal_id, confirm=True)


def test_apply_refuses_untracked_target(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    patch = "--- a/new.py\n+++ b/new.py\n@@ -1 +1 @@\n-old\n+new\n"
    (root / ".aurix" / "proposals" / f"{proposal_id}.diff").write_text(patch, encoding="utf-8")
    with pytest.raises(PermissionError, match="existing regular files"):
        apply_proposal(root, proposal_id, confirm=True)


def test_apply_refuses_path_traversal(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    patch = "--- a/../outside.py\n+++ b/../outside.py\n@@ -1 +1 @@\n-old\n+new\n"
    (root / ".aurix" / "proposals" / f"{proposal_id}.diff").write_text(patch, encoding="utf-8")
    with pytest.raises(PermissionError, match="Unsafe path"):
        apply_proposal(root, proposal_id, confirm=True)


def test_apply_refuses_git_metadata_headers(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    patch = (
        "diff --git a/app.py b/app.py\nindex 1234567..89abcde 100644\n"
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 'old'\n+value = 'new'\n"
    )
    (root / ".aurix" / "proposals" / f"{proposal_id}.diff").write_text(patch, encoding="utf-8")
    with pytest.raises(PermissionError, match="plain unified diffs"):
        apply_proposal(root, proposal_id, confirm=True)


def test_apply_with_audit_gate_rejects_missing_evidence(tmp_path):
    import pytest

    from aurix.tools.patches import apply_proposal

    root, proposal_id = make_repo(tmp_path)
    with pytest.raises(PermissionError, match="passing audit record"):
        apply_proposal(root, proposal_id, confirm=True, require_audit_gate=True)


def _write_passing_audit(root, proposal_id):
    import hashlib
    import json
    import subprocess

    proposal = root / ".aurix" / "proposals" / f"{proposal_id}.diff"
    patch_digest = hashlib.sha256(proposal.read_bytes()).hexdigest()
    base_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    verification = {
        "audit_id": "a" * 32,
        "verification_id": "b" * 32,
        "proposal_id": proposal_id,
        "proposal_sha256": patch_digest,
        "base_commit": base_commit,
        "target_state_sha256": hashlib.sha256(
            json.dumps(
                [
                    {
                        "path": "app.py",
                        "sha256": hashlib.sha256((root / "app.py").read_bytes()).hexdigest(),
                    }
                ],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
        "suite": "pytest",
        "requested_suite": "pytest",
        "test_selection": {"mode": "full_suite", "reason": "test fixture", "paths": []},
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
    verification["evidence_sha256"] = hashlib.sha256(
        json.dumps(
            verification,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    target_state = [
        {"path": "app.py", "sha256": hashlib.sha256((root / "app.py").read_bytes()).hexdigest()}
    ]
    target_state_sha256 = hashlib.sha256(
        json.dumps(target_state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    verification["target_state_sha256"] = target_state_sha256
    verification["evidence_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in verification.items() if key != "evidence_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    record = {
        "schema_version": 9,
        "audit_id": "a" * 32,
        "target_state": target_state,
        "target_state_sha256": target_state_sha256,
        "proposal_id": proposal_id,
        "proposal_sha256": patch_digest,
        "base_commit": base_commit,
        "status": "audit_passed",
        "review": {"risk_level": "low"},
        "review_tracks": {
            "security": {
                "proposal_sha256": patch_digest,
                "risk_level": "low",
                "evidence_schema": 1,
                "findings": [],
                "integrity": {"sha256": patch_digest},
            },
            "correctness": {
                "proposal_sha256": patch_digest,
                "risk_level": "low",
                "evidence_schema": 1,
                "findings": [],
            },
        },
        "verification": {**verification, "status": "verified_pass"},
    }
    audit_dir = root / ".aurix" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / f"{proposal_id}.json").write_text(json.dumps(record), encoding="utf-8")


def test_audit_gate_accepts_evidence_bound_to_current_head(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    _write_passing_audit(root, proposal_id)
    result = apply_proposal(root, proposal_id, confirm=True, require_audit_gate=True)
    assert result["status"] == "applied"


def test_audit_gate_rejects_evidence_for_previous_head(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    _write_passing_audit(root, proposal_id)
    (root / "app.py").write_text("value = 'another commit'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "advance head"], check=True, capture_output=True
    )
    with pytest.raises(PermissionError, match="exact patch"):
        apply_proposal(root, proposal_id, confirm=True, require_audit_gate=True)


def test_audit_gate_rejects_tampered_verification_evidence(tmp_path):
    import json

    root, proposal_id = make_repo(tmp_path)
    _write_passing_audit(root, proposal_id)
    path = root / ".aurix" / "audits" / f"{proposal_id}.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    audit["verification"]["test_result"]["passed"] = False
    path.write_text(json.dumps(audit), encoding="utf-8")
    with pytest.raises(PermissionError, match="exact patch"):
        apply_proposal(root, proposal_id, confirm=True, require_audit_gate=True)


def test_apply_rolls_back_when_audit_logging_fails(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)

    def fail_audit(*args, **kwargs):
        raise OSError("simulated audit storage failure")

    monkeypatch.setattr(patches, "append_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="rolled back"):
        apply_proposal(root, proposal_id, confirm=True)
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'" + chr(10)
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""


def test_apply_reports_transaction_state(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    result = apply_proposal(root, proposal_id, confirm=True)
    assert result["transaction"] == "applied_and_audited"


def test_apply_rollback_verifies_final_tracked_status(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    original_append = patches.append_audit_event

    def fail_audit(*args, **kwargs):
        raise OSError("simulated audit failure")

    monkeypatch.setattr(patches, "append_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="rolled back"):
        apply_proposal(root, proposal_id, confirm=True)
    assert patches._tracked_status(root) == ""
    monkeypatch.setattr(patches, "append_audit_event", original_append)


def test_revert_reports_verified_transaction(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    result = revert_proposal(root, proposal_id, confirm=True)
    assert result["transaction"] == "reverted_and_audited"
    assert result["recovery_status"] == "verified"
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


def test_revert_restores_patch_if_audit_logging_fails(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)

    def fail_audit(*args, **kwargs):
        raise OSError("simulated audit failure")

    monkeypatch.setattr(patches, "append_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="original patch was restored"):
        revert_proposal(root, proposal_id, confirm=True)
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'new'\n"
    assert patches._tracked_status(root) == "M app.py"


def test_patch_operation_refuses_existing_workspace_lock(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    lock = root / ".aurix" / "operation.lock"
    lock.write_text('{"pid": 999999, "created_at": 0}', encoding="utf-8")
    with pytest.raises(PermissionError, match="workspace lock"):
        apply_proposal(root, proposal_id, confirm=True)
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


def test_inspect_operation_lock_rejects_boolean_pid(tmp_path):
    from aurix.tools.patches import inspect_operation_lock

    root, _ = make_repo(tmp_path)
    lock = root / ".aurix" / "operation.lock"
    lock.write_text('{"pid": true, "created_at": 1}', encoding="utf-8")
    report = inspect_operation_lock(root)
    assert report["status"] == "invalid"
    assert "valid positive PID" in report["reason"]


def test_recovery_anchor_rejects_boolean_schema_version(tmp_path):
    from aurix.tools.patches import verify_recovery_histories

    root, _ = make_repo(tmp_path)
    outside = tmp_path / "recovery.json"
    outside.write_text(
        json.dumps({
            "schema_version": True,
            "algorithm": "sha256",
            "workspace": str(root.resolve()),
            "journals": {},
        }),
        encoding="utf-8",
    )
    report = verify_recovery_histories(root, outside)
    assert report["status"] == "invalid"
    assert report["anchor"]["status"] == "invalid"


def test_apply_detects_head_change_during_preflight(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    (root / "other.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "other.py"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "add unrelated file"],
        check=True,
        capture_output=True,
    )
    original_git = patches._git
    changed = False

    def race_git(workspace, args, *, patch=None):
        nonlocal changed
        result = original_git(workspace, args, patch=patch)
        if args[:2] == ["apply", "--check"] and not changed:
            changed = True
            (root / "other.py").write_text("value = 2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "other.py"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-m", "concurrent commit"],
                check=True,
                capture_output=True,
            )
        return result

    monkeypatch.setattr(patches, "_git", race_git)
    with pytest.raises(PermissionError, match="HEAD changed during preflight"):
        apply_proposal(root, proposal_id, confirm=True)
    assert "new" not in (root / "app.py").read_text(encoding="utf-8")
    assert patches._git_head(root) != ""


def test_audit_gate_rejects_finding_with_mismatched_line_evidence(tmp_path):
    import json

    root, proposal_id = make_repo(tmp_path)
    _write_passing_audit(root, proposal_id)
    path = root / ".aurix" / "audits" / f"{proposal_id}.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    patch = (root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_bytes()
    digest = hashlib.sha256(patch).hexdigest()
    audit["review_tracks"]["security"]["findings"] = [
        {
            "file": "app.py",
            "patch_line": 4,
            "evidence": {
                "file": "app.py",
                "patch_line": 4,
                "patch_sha256": digest,
                "line_sha256": "0" * 64,
                "source_line": 1,
                "hunk": "@@ -1 +1 @@",
            },
        }
    ]
    path.write_text(json.dumps(audit), encoding="utf-8")
    with pytest.raises(PermissionError, match="exact patch"):
        apply_proposal(root, proposal_id, confirm=True, require_audit_gate=True)


def test_audit_gate_rejects_cross_cycle_verification(tmp_path):
    import json

    root, proposal_id = make_repo(tmp_path)
    _write_passing_audit(root, proposal_id)
    path = root / ".aurix" / "audits" / f"{proposal_id}.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    audit["verification"]["audit_id"] = "c" * 32
    # Recompute the ordinary evidence digest to prove cycle identity is an independent gate.
    evidence = {
        key: audit["verification"].get(key)
        for key in (
            "audit_id",
            "verification_id",
            "proposal_id",
            "proposal_sha256",
            "base_commit",
            "target_state_sha256",
            "suite",
            "requested_suite",
            "test_selection",
            "isolation",
            "sandbox_image",
            "sandbox_image_id",
            "runtime_fingerprint",
            "baseline_result",
            "test_result",
            "regression_status",
        )
    }
    audit["verification"]["evidence_sha256"] = hashlib.sha256(
        __import__("json")
        .dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        .encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(audit), encoding="utf-8")
    with pytest.raises(PermissionError, match="exact patch"):
        apply_proposal(root, proposal_id, confirm=True, require_audit_gate=True)


def test_audit_gate_rejects_target_file_changed_after_audit(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    _write_passing_audit(root, proposal_id)
    (root / "app.py").write_text("value = 'externally changed'\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="changed since audit"):
        apply_proposal(root, proposal_id, confirm=True, require_audit_gate=True)
    assert "externally changed" in (root / "app.py").read_text(encoding="utf-8")


def test_apply_persists_durable_transaction_journal(tmp_path):
    import json

    root, proposal_id = make_repo(tmp_path)
    result = apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert result["journal"] == f".aurix/transactions/{proposal_id}.json"
    assert journal["state"] == "applied_and_audited"
    assert (
        journal["patch_sha256"]
        == hashlib.sha256(
            (root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_bytes()
        ).hexdigest()
    )
    assert journal["recovery"] == "verified"


def test_incomplete_transaction_journal_blocks_retry(tmp_path):
    import json

    root, proposal_id = make_repo(tmp_path)
    journal_dir = root / ".aurix" / "transactions"
    journal_dir.mkdir()
    (journal_dir / f"{proposal_id}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "proposal_id": proposal_id,
                "state": "patch_applied",
                "recovery": "pending_verification",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PermissionError, match="incomplete transaction journal"):
        apply_proposal(root, proposal_id, confirm=True)
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


def test_malformed_transaction_journal_fails_closed(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    journal_dir = root / ".aurix" / "transactions"
    journal_dir.mkdir()
    (journal_dir / f"{proposal_id}.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(PermissionError, match="journal is unreadable"):
        apply_proposal(root, proposal_id, confirm=True)
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


def test_inspect_transactions_is_read_only_and_reports_clean_workspace(tmp_path):
    root, _ = make_repo(tmp_path)
    before = (root / "app.py").read_bytes()
    report = inspect_transactions(root)
    assert report["status"] == "clean"
    assert report["count"] == 0
    assert report["read_only"] is True
    assert (root / "app.py").read_bytes() == before


def test_inspect_transactions_confirms_applied_patch_without_mutating(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    before_journal = journal.read_bytes()
    before_target = (root / "app.py").read_bytes()
    report = inspect_transactions(root)
    assert report["status"] == "inspected"
    assert report["transactions"][0]["status"] == "consistent_terminal_record"
    assert journal.read_bytes() == before_journal
    assert (root / "app.py").read_bytes() == before_target


def test_inspect_transactions_flags_external_edit_to_applied_patch(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    (root / "app.py").write_text("value = 'external'\n", encoding="utf-8")
    report = inspect_transactions(root)
    assert report["status"] == "manual_intervention_required"
    assert report["transactions"][0]["status"] == "manual_intervention_required"


def test_recovery_plan_proposes_rollback_without_mutating_workspace(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal.read_text(encoding="utf-8"))
    record.update(state="patch_applied", recovery="pending_verification")
    journal.write_text(json.dumps(record), encoding="utf-8")
    before_target = (root / "app.py").read_bytes()
    before_journal = journal.read_bytes()

    report = plan_transaction_recovery(root)

    assert report["read_only"] is True
    assert report["execution_performed"] is False
    assert report["plans"][0]["action"] == "propose_exact_patch_rollback"
    assert report["plans"][0]["safe_to_automate"] is False
    assert all(item["passed"] for item in report["plans"][0]["preconditions"])
    assert (root / "app.py").read_bytes() == before_target
    assert journal.read_bytes() == before_journal


def test_recovery_plan_requires_manual_review_after_external_edit(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal.read_text(encoding="utf-8"))
    record.update(state="patch_applied", recovery="pending_verification")
    journal.write_text(json.dumps(record), encoding="utf-8")
    (root / "app.py").write_text("value = 'external edit'\n", encoding="utf-8")

    report = plan_transaction_recovery(root)

    assert report["plans"][0]["action"] == "manual_review"
    assert report["plans"][0]["safe_to_automate"] is False
    assert report["plans"][0]["mutates_workspace"] is False


def test_explicit_transaction_recovery_rolls_back_exact_patch_and_records_history(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record.update(state="patch_applied", recovery="pending_verification")
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    from aurix.tools.patches import recover_transaction

    result = recover_transaction(root, proposal_id, confirm=True)

    assert result["status"] == "recovered"
    assert result["transaction"] == "rolled_back"
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"
    final = json.loads(journal_path.read_text(encoding="utf-8"))
    assert final["state"] == "rolled_back"
    assert final["recovery_history"][-1]["result"] == "verified"
    report = inspect_transactions(root)
    assert report["status"] == "inspected"
    assert report["transactions"][0]["status"] == "consistent_terminal_record"


def test_explicit_transaction_recovery_refuses_external_edit(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record.update(state="patch_applied", recovery="pending_verification")
    journal_path.write_text(json.dumps(record), encoding="utf-8")
    (root / "app.py").write_text("value = 'external edit'\n", encoding="utf-8")

    from aurix.tools.patches import recover_transaction

    with pytest.raises(
        PermissionError, match="Exact inverse patch no longer applies|Tracked diff differs"
    ):
        recover_transaction(root, proposal_id, confirm=True)
    assert "external edit" in (root / "app.py").read_text(encoding="utf-8")


def test_explicit_transaction_recovery_requires_confirmation(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    from aurix.tools.patches import recover_transaction

    with pytest.raises(PermissionError, match="Explicit confirmation"):
        recover_transaction(root, proposal_id, confirm=False)


def test_inspection_reconciles_interrupted_recovery_without_mutating_journal(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    from aurix.tools.patches import apply_proposal

    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.update(state="recovery_in_progress", recovery="pending_verification")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before = journal_path.read_bytes()

    report = inspect_transactions(root)

    row = report["transactions"][0]
    assert row["status"] == "manual_intervention_required"
    assert row["observed_state"] == "patch_still_applied_exactly"
    assert (
        row["suggested_action"]
        == "review transaction and rerun explicit recovery after fresh preflight"
    )
    assert journal_path.read_bytes() == before
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'new'\n"


def test_inspection_detects_rollback_done_but_journal_unfinalized(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    from aurix.tools.patches import apply_proposal

    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.update(state="recovery_interrupted", recovery="manual_intervention_required")
    # Simulate crash after exact reverse patch but before journal finalization.
    subprocess.run(
        ["git", "-C", str(root), "apply", "--reverse", "--whitespace=error", "-"],
        input=(root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=True,
    )
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before = journal_path.read_bytes()

    report = inspect_transactions(root)

    row = report["transactions"][0]
    assert row["observed_state"] == "rollback_effectively_completed_journal_unfinalized"
    assert row["status"] == "manual_intervention_required"
    assert journal_path.read_bytes() == before
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


def test_finalize_interrupted_recovery_only_updates_journal_after_verified_baseline(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.update(state="recovery_interrupted", recovery="manual_intervention_required")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "apply", "--reverse", "--whitespace=error", "-"],
        input=(root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=True,
    )
    before_source = (root / "app.py").read_bytes()

    with pytest.raises(PermissionError, match="Explicit confirmation"):
        finalize_interrupted_recovery(root, proposal_id, confirm=False)
    result = finalize_interrupted_recovery(root, proposal_id, confirm=True)

    assert result["status"] == "finalized"
    assert (root / "app.py").read_bytes() == before_source
    final = json.loads(journal_path.read_text(encoding="utf-8"))
    assert final["state"] == "rolled_back"
    assert final["recovery_history"][-1]["result"] == "baseline_verified"
    report = inspect_transactions(root)
    assert report["status"] == "inspected"
    assert report["transactions"][0]["status"] == "consistent_terminal_record"


def test_finalize_interrupted_recovery_reports_audit_failure_after_terminal_state(
    tmp_path, monkeypatch
):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.update(state="recovery_interrupted", recovery="manual_intervention_required")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "apply", "--reverse", "--whitespace=error", "-"],
        input=(root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=True,
    )

    def fail_audit(*args, **kwargs):
        raise OSError("simulated finalization audit failure")

    monkeypatch.setattr(patches, "append_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="finalization audit event could not be persisted"):
        patches.finalize_interrupted_recovery(root, proposal_id, confirm=True)

    final = json.loads(journal_path.read_text(encoding="utf-8"))
    assert final["state"] == "rolled_back"
    assert final["recovery"] == "verified"
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


def test_finalize_interrupted_recovery_refuses_dirty_worktree(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.update(state="recovery_interrupted", recovery="manual_intervention_required")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    (root / "app.py").write_text("value = 'external edit'\n", encoding="utf-8")

    with pytest.raises(PermissionError, match="not clean"):
        finalize_interrupted_recovery(root, proposal_id, confirm=True)
    assert json.loads(journal_path.read_text(encoding="utf-8"))["state"] == "recovery_interrupted"
    assert "external edit" in (root / "app.py").read_text(encoding="utf-8")


def test_finalize_interrupted_recovery_refuses_staged_index_change(tmp_path):
    """A clean-looking worktree is insufficient when the Git index diverges."""
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.update(state="recovery_interrupted", recovery="manual_intervention_required")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "apply", "--reverse", "--whitespace=error", "-"],
        input=(root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=True,
    )
    # Stage a divergent version, then restore the worktree file without staging
    # that restoration. The worktree looks like the baseline while the index does not.
    (root / "app.py").write_text("value = 'staged-only-change'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "app.py"], check=True, capture_output=True)
    (root / "app.py").write_text("value = 'old'\n", encoding="utf-8")
    before_journal = journal_path.read_bytes()
    before_index = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--binary"],
        check=True,
        capture_output=True,
    ).stdout

    with pytest.raises(PermissionError, match="not clean"):
        finalize_interrupted_recovery(root, proposal_id, confirm=True)

    assert journal_path.read_bytes() == before_journal
    assert (
        subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--binary"],
            check=True,
            capture_output=True,
        ).stdout
        == before_index
    )
    assert json.loads(journal_path.read_text(encoding="utf-8"))["state"] == "recovery_interrupted"


def test_recovery_history_hash_chain_detects_tampering_before_finalization(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.update(state="recovery_interrupted", recovery="manual_intervention_required")
    journal["recovery_history"] = [
        {
            "action": "fake_recovery",
            "result": "verified",
            "previous_hash": "0" * 64,
            "entry_hash": "f" * 64,
        }
    ]
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "apply", "--reverse", "--whitespace=error", "-"],
        input=(root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=True,
    )
    with pytest.raises(PermissionError, match="Recovery history integrity check failed"):
        finalize_interrupted_recovery(root, proposal_id, confirm=True)
    assert json.loads(journal_path.read_text(encoding="utf-8"))["state"] == "recovery_interrupted"


def test_independent_recovery_history_verifier_is_read_only_and_detects_tampering(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["recovery_history"] = [
        {"event": "recovery_test", "result": "verified", "previous_hash": "0" * 64}
    ]
    from aurix.tools.patches import _recovery_history_digest

    body = {"event": "recovery_test", "result": "verified"}
    journal["recovery_history"][0]["entry_hash"] = _recovery_history_digest(body, "0" * 64)
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before = journal_path.read_bytes()
    report = verify_recovery_histories(root)
    assert report["status"] == "valid"
    assert report["read_only"] is True
    assert journal_path.read_bytes() == before
    journal["recovery_history"][0]["result"] = "tampered"
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    report = verify_recovery_histories(root)
    assert report["status"] == "invalid"
    assert report["invalid"] == 1


def test_transaction_inspection_rejects_tampered_recovery_history(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["recovery_history"] = [
        {
            "action": "forged_recovery",
            "result": "verified",
            "previous_hash": "0" * 64,
            "entry_hash": "f" * 64,
        }
    ]
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before = journal_path.read_bytes()

    report = inspect_transactions(root)

    assert report["status"] == "manual_intervention_required"
    row = report["transactions"][0]
    assert row["status"] == "manual_intervention_required"
    assert row["reason"] == "recovery history is invalid: PermissionError"
    plan = plan_transaction_recovery(root)
    assert plan["status"] == "manual_intervention_required"
    assert plan["plans"][0]["action"] == "manual_review"
    assert journal_path.read_bytes() == before


def test_external_recovery_anchor_detects_journal_change_removal_and_addition(tmp_path):
    from aurix.tools.patches import (
        create_recovery_anchor,
        verify_recovery_histories,
    )

    root = tmp_path / "workspace"
    transactions = root / ".aurix" / "transactions"
    transactions.mkdir(parents=True)
    first = transactions / ("a" * 12 + ".json")
    first.write_text(
        json.dumps({"proposal_id": "a" * 12, "recovery_history": []}), encoding="utf-8"
    )
    anchor = tmp_path / "external" / "recovery-anchor.json"

    created = create_recovery_anchor(root, anchor)
    assert created["journals"] == 1
    assert verify_recovery_histories(root, anchor)["anchor"]["status"] == "valid"

    first.write_text(
        json.dumps({"proposal_id": "a" * 12, "recovery_history": [], "state": "changed"}),
        encoding="utf-8",
    )
    report = verify_recovery_histories(root, anchor)
    assert report["anchor"]["changed"] == [first.name]

    first.unlink()
    report = verify_recovery_histories(root, anchor)
    assert report["anchor"]["missing"] == [first.name]

    second = transactions / ("b" * 12 + ".json")
    second.write_text(
        json.dumps({"proposal_id": "b" * 12, "recovery_history": []}), encoding="utf-8"
    )
    report = verify_recovery_histories(root, anchor)
    assert report["anchor"]["added"] == [second.name]


def test_external_recovery_anchor_refuses_workspace_path_and_overwrite(tmp_path):
    from aurix.tools.patches import create_recovery_anchor

    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(PermissionError, match="outside the workspace"):
        create_recovery_anchor(root, root / "anchor.json")
    anchor = tmp_path / "anchor.json"
    create_recovery_anchor(root, anchor)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        create_recovery_anchor(root, anchor)


def test_external_recovery_anchor_rejects_malformed_anchor_and_workspace_mismatch(tmp_path):
    from aurix.tools.patches import verify_recovery_histories

    root = tmp_path / "workspace"
    root.mkdir()
    anchor = tmp_path / "anchor.json"
    anchor.write_text('{"schema_version": 99}', encoding="utf-8")
    report = verify_recovery_histories(root, anchor)
    assert report["status"] == "invalid"
    assert report["anchor"]["status"] == "invalid"


def test_external_recovery_anchor_refuses_to_snapshot_invalid_journal(tmp_path):
    from aurix.tools.patches import create_recovery_anchor

    root = tmp_path / "workspace"
    transactions = root / ".aurix" / "transactions"
    transactions.mkdir(parents=True)
    (transactions / ("c" * 12 + ".json")).write_text("{broken", encoding="utf-8")
    with pytest.raises(PermissionError, match="invalid recovery journals"):
        create_recovery_anchor(root, tmp_path / "anchor.json")
    assert not (tmp_path / "anchor.json").exists()


def test_external_recovery_anchor_refuses_symlink_anchor(tmp_path):
    from aurix.tools.patches import (
        create_recovery_anchor,
        verify_recovery_histories,
    )

    root = tmp_path / "workspace"
    root.mkdir()
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(PermissionError, match="symlink"):
        create_recovery_anchor(root, link)
    with pytest.raises(PermissionError, match="symlink"):
        verify_recovery_histories(root, link)


def test_external_recovery_anchor_detects_journal_added_after_empty_snapshot(tmp_path):
    from aurix.tools.patches import (
        create_recovery_anchor,
        verify_recovery_histories,
    )

    root = tmp_path / "workspace"
    root.mkdir()
    anchor = tmp_path / "anchor.json"
    assert create_recovery_anchor(root, anchor)["journals"] == 0
    transactions = root / ".aurix" / "transactions"
    transactions.mkdir(parents=True)
    journal = transactions / ("d" * 12 + ".json")
    journal.write_text(
        json.dumps({"proposal_id": "d" * 12, "recovery_history": []}), encoding="utf-8"
    )
    report = verify_recovery_histories(root, anchor)
    assert report["status"] == "invalid"
    assert report["anchor"]["added"] == [journal.name]


def test_external_recovery_anchor_rejects_duplicate_json_keys(tmp_path):
    from aurix.tools.patches import verify_recovery_histories

    root = tmp_path / "workspace"
    root.mkdir()
    anchor = tmp_path / "anchor.json"
    anchor.write_text(
        '{"schema_version":1,"schema_version":1,"algorithm":"sha256",'
        f'"workspace":"{root.resolve()}","journals":{{}}}}',
        encoding="utf-8",
    )
    report = verify_recovery_histories(root, anchor)
    assert report["status"] == "invalid"
    assert report["anchor"]["status"] == "invalid"
    assert "duplicate JSON key" in report["anchor"]["reason"]


def test_external_recovery_anchor_rejects_path_like_journal_names(tmp_path):
    from aurix.tools.patches import verify_recovery_histories

    root = tmp_path / "workspace"
    root.mkdir()
    anchor = tmp_path / "anchor.json"
    anchor.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "algorithm": "sha256",
                "workspace": str(root.resolve()),
                "journals": {"../escape.json": "0" * 64},
            }
        ),
        encoding="utf-8",
    )
    report = verify_recovery_histories(root, anchor)
    assert report["status"] == "invalid"
    assert report["anchor"]["status"] == "invalid"


def test_transaction_verifier_rejects_duplicate_journal_keys(tmp_path):
    from aurix.tools.patches import verify_recovery_histories

    root = tmp_path / "workspace"
    root.mkdir()
    transactions = root / ".aurix" / "transactions"
    transactions.mkdir(parents=True)
    proposal_id = "e" * 12
    (transactions / f"{proposal_id}.json").write_text(
        '{"proposal_id":"'
        + proposal_id
        + '","proposal_id":"'
        + proposal_id
        + '","recovery_history":[]}',
        encoding="utf-8",
    )
    report = verify_recovery_histories(root)
    assert report["status"] == "invalid"
    assert report["invalid"] == 1
    assert "duplicate JSON key" in report["results"][0]["reason"]


def test_transaction_inspection_fails_closed_on_duplicate_state_keys(tmp_path):
    from aurix.tools.patches import inspect_transactions

    root = tmp_path / "workspace"
    root.mkdir()
    transactions = root / ".aurix" / "transactions"
    transactions.mkdir(parents=True)
    proposal_id = "f" * 12
    (transactions / f"{proposal_id}.json").write_text(
        '{"proposal_id":"' + proposal_id + '","state":"applied_and_audited",'
        '"state":"patch_applied"}',
        encoding="utf-8",
    )
    report = inspect_transactions(root)
    row = report["transactions"][0]
    assert row["status"] == "manual_intervention_required"
    assert row["reason"] == "journal is unreadable"


def test_journal_replace_failure_preserves_previous_record_and_cleans_temp(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    original = {"schema_version": 1, "proposal_id": proposal_id, "state": "rolled_back"}
    patches._write_transaction_journal(root, proposal_id, original)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    before = journal_path.read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(patches.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated atomic replace failure"):
        patches._write_transaction_journal(
            root, proposal_id, {**original, "state": "recovery_in_progress"}
        )

    assert journal_path.read_bytes() == before
    assert not list(journal_path.parent.glob(journal_path.name + ".*.tmp"))


def test_recovery_replay_refuses_already_rolled_back_transaction(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record.update(state="patch_applied", recovery="pending_verification")
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    from aurix.tools.patches import recover_transaction

    first = recover_transaction(root, proposal_id, confirm=True)
    assert first["status"] == "recovered"
    baseline = (root / "app.py").read_bytes()
    terminal_journal = journal_path.read_bytes()

    with pytest.raises(PermissionError, match="Only an interrupted patch_applied transaction"):
        recover_transaction(root, proposal_id, confirm=True)

    assert (root / "app.py").read_bytes() == baseline
    assert journal_path.read_bytes() == terminal_journal



def test_recovery_accepts_applying_journal_when_exact_patch_is_present(tmp_path):
    """Recover a crash after git apply but before persisting patch_applied."""
    from aurix.tools.patches import recover_transaction

    root, proposal_id = make_repo(tmp_path)
    baseline = (root / "app.py").read_bytes()
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record.update(state="applying", recovery="manual_if_interrupted")
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    recovered = recover_transaction(root, proposal_id, confirm=True)

    assert recovered["status"] == "recovered"
    assert (root / "app.py").read_bytes() == baseline
    terminal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert terminal["state"] == "rolled_back"
    assert terminal["recovery"] == "verified"
    assert terminal["recovery_history"][-1]["result"] == "verified"


def test_recovery_terminal_journal_write_failure_can_be_finalized_safely(tmp_path, monkeypatch):
    """A crash after rollback but before terminal persistence is reconciled explicitly."""
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record.update(state="patch_applied", recovery="pending_verification")
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    original_write = patches._write_transaction_journal
    calls = 0

    def fail_terminal_write(workspace, pid, value):
        nonlocal calls
        calls += 1
        # First write persists recovery_in_progress; second would persist rolled_back.
        if calls == 2:
            raise OSError("simulated crash before terminal journal persistence")
        return original_write(workspace, pid, value)

    monkeypatch.setattr(patches, "_write_transaction_journal", fail_terminal_write)
    with pytest.raises(OSError, match="terminal journal persistence"):
        patches.recover_transaction(root, proposal_id, confirm=True)

    # The rollback reached baseline, but the journal remains non-terminal.
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"
    interrupted = json.loads(journal_path.read_text(encoding="utf-8"))
    assert interrupted["state"] == "recovery_in_progress"
    assert calls == 2

    # Restore normal durable writes and require explicit, independent verification.
    monkeypatch.setattr(patches, "_write_transaction_journal", original_write)
    finalized = patches.finalize_interrupted_recovery(root, proposal_id, confirm=True)
    assert finalized["status"] == "finalized"
    terminal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert terminal["state"] == "rolled_back"
    assert terminal["recovery"] == "verified"
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


def test_recovery_journal_failure_before_rollback_does_not_mutate_source(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record.update(state="patch_applied", recovery="pending_verification")
    journal_path.write_text(json.dumps(record), encoding="utf-8")
    before = (root / "app.py").read_bytes()

    def fail_write(*args, **kwargs):
        raise OSError("simulated failure persisting recovery intent")

    monkeypatch.setattr(patches, "_write_transaction_journal", fail_write)
    with pytest.raises(OSError, match="recovery intent"):
        patches.recover_transaction(root, proposal_id, confirm=True)
    assert (root / "app.py").read_bytes() == before
    # Intent persistence failed, so the original journal is unchanged and no patch was reversed.
    assert json.loads(journal_path.read_text(encoding="utf-8"))["state"] == "patch_applied"


def test_recovery_concurrent_edit_after_intent_fails_closed(tmp_path, monkeypatch):
    """An editor racing rollback must not be mistaken for a clean recovery."""
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record.update(state="patch_applied", recovery="pending_verification")
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    original_write = patches._write_transaction_journal
    injected = False

    def write_then_race(workspace, pid, value):
        nonlocal injected
        original_write(workspace, pid, value)
        if value.get("state") == "recovery_in_progress" and not injected:
            injected = True
            # Simulate an editor changing the tracked file after preflight and
            # after the recovery intent is durable, but before inverse patching.
            target = root / "app.py"
            target.write_text(
                target.read_text(encoding="utf-8") + "# concurrent edit\n", encoding="utf-8"
            )

    monkeypatch.setattr(patches, "_write_transaction_journal", write_then_race)
    with pytest.raises(RuntimeError, match="Exact rollback failed"):
        patches.recover_transaction(root, proposal_id, confirm=True)

    assert injected is True
    source = (root / "app.py").read_text(encoding="utf-8")
    # Inverse application is refused because the concurrent edit invalidated
    # its context; neither the new source nor the external edit is discarded.
    assert "value = 'new'" in source
    assert "# concurrent edit" in source
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["state"] == "recovery_interrupted"
    assert journal["recovery"] == "manual_intervention_required"


def test_recovery_concurrent_edit_after_inverse_apply_is_not_marked_success(tmp_path, monkeypatch):
    """An edit after inverse application but before verification must leave recovery interrupted."""
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record.update(state="patch_applied", recovery="pending_verification")
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    original_git = patches._git
    injected = False

    def git_then_race(workspace, args, **kwargs):
        nonlocal injected
        result = original_git(workspace, args, **kwargs)
        if (
            not injected
            and args[:2] == ["apply", "--reverse"]
            and result.returncode == 0
            and "--check" not in args
        ):
            injected = True
            target = root / "app.py"
            target.write_text(
                target.read_text(encoding="utf-8") + "# edit after inverse apply\n",
                encoding="utf-8",
            )
        return result

    monkeypatch.setattr(patches, "_git", git_then_race)
    with pytest.raises(RuntimeError, match="Rollback result could not be verified"):
        patches.recover_transaction(root, proposal_id, confirm=True)

    assert injected is True
    source = (root / "app.py").read_text(encoding="utf-8")
    assert "value = 'old'" in source
    assert "# edit after inverse apply" in source
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["state"] == "recovery_interrupted"
    assert journal["recovery"] == "manual_intervention_required"


def test_workspace_operation_lock_excludes_second_operation_and_preserves_owner(tmp_path):
    root, _ = make_repo(tmp_path)
    with _workspace_operation_lock(root):
        lock_path = root / ".aurix" / "operation.lock"
        assert lock_path.is_file()
        owner = json.loads(lock_path.read_text(encoding="utf-8"))
        assert owner["pid"] > 0
        with pytest.raises(PermissionError, match="Another AURIX patch operation"):
            with _workspace_operation_lock(root):
                pytest.fail("second operation must not enter while lock is held")
        assert json.loads(lock_path.read_text(encoding="utf-8")) == owner
    assert not lock_path.exists()


def test_workspace_operation_lock_does_not_follow_symlink(tmp_path):
    root, _ = make_repo(tmp_path)
    metadata = root / ".aurix"
    metadata.mkdir(exist_ok=True)
    target = tmp_path / "external-lock-target"
    target.write_text("do not touch", encoding="utf-8")
    lock_path = metadata / "operation.lock"
    lock_path.symlink_to(target)
    with pytest.raises(PermissionError, match="Another AURIX patch operation"):
        with _workspace_operation_lock(root):
            pytest.fail("symlink lock must be refused")
    assert target.read_text(encoding="utf-8") == "do not touch"
    assert lock_path.is_symlink()


def test_operation_lock_inspection_is_read_only_and_does_not_claim_stale(tmp_path):
    from aurix.tools.patches import inspect_operation_lock

    root = tmp_path / "repo"
    root.mkdir()
    absent = inspect_operation_lock(root)
    assert absent["status"] == "absent" and absent["read_only"] is True
    with _workspace_operation_lock(root):
        lock_path = root / ".aurix" / "operation.lock"
        before = lock_path.read_bytes()
        result = inspect_operation_lock(root)
        assert result["status"] == "present"
        assert result["owner_status"] in {"possibly_alive", "inaccessible", "unknown"}
        assert result["stale_not_proven"] is True
        assert lock_path.read_bytes() == before


def test_operation_lock_inspection_rejects_malformed_record_without_mutation(tmp_path):
    from aurix.tools.patches import inspect_operation_lock

    root = tmp_path / "repo"
    metadata = root / ".aurix"
    metadata.mkdir(parents=True)
    lock_path = metadata / "operation.lock"
    lock_path.write_text('{"pid": 1, "pid": 2, "created_at": 1}', encoding="utf-8")
    before = lock_path.read_bytes()
    result = inspect_operation_lock(root)
    assert result["status"] == "invalid"
    assert lock_path.read_bytes() == before


def test_workspace_operation_lock_excludes_a_separate_process(tmp_path):
    import os
    import sys
    import time
    from pathlib import Path

    root, _ = make_repo(tmp_path)
    ready = tmp_path / "lock-ready"
    release = tmp_path / "lock-release"
    script = r"""
import sys, time
from pathlib import Path
from aurix.tools.patches import _workspace_operation_lock
root = Path(sys.argv[1])
ready = Path(sys.argv[2])
release = Path(sys.argv[3])
with _workspace_operation_lock(root):
    ready.write_text('ready', encoding='utf-8')
    deadline = time.monotonic() + 10
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not release.exists():
        raise SystemExit('test release signal timed out')
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(root), str(ready), str(release)], env=env
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "child process did not acquire the lock"
        lock_path = root / ".aurix" / "operation.lock"
        owner = json.loads(lock_path.read_text(encoding="utf-8"))
        assert owner["pid"] == process.pid
        with pytest.raises(PermissionError, match="Another AURIX patch operation"):
            with _workspace_operation_lock(root):
                pytest.fail("parent must not enter while child process holds lock")
        assert json.loads(lock_path.read_text(encoding="utf-8")) == owner
    finally:
        release.write_text("release", encoding="utf-8")
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    assert process.returncode == 0
    assert not (root / ".aurix" / "operation.lock").exists()



@pytest.mark.parametrize("protected_path", [".GIT/config", ".AURIX/proposals/payload.diff"])
def test_apply_rejects_case_variant_protected_patch_paths(tmp_path, protected_path):
    root, proposal_id = make_repo(tmp_path)
    patch = (
        f"--- a/{protected_path}\n"
        f"+++ b/{protected_path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    (root / ".aurix" / "proposals" / f"{proposal_id}.diff").write_text(
        patch, encoding="utf-8"
    )
    with pytest.raises(PermissionError, match="Unsafe path"):
        apply_proposal(root, proposal_id, confirm=True)
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"



def test_apply_rejects_patch_target_through_symlinked_parent(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    alias = root / "alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this platform")
    patch = (
        "--- a/alias/app.py\n"
        "+++ b/alias/app.py\n"
        "@@ -1 +1 @@\n"
        "-value = 'old'\n"
        "+value = 'new'\n"
    )
    (root / ".aurix" / "proposals" / f"{proposal_id}.diff").write_text(
        patch, encoding="utf-8"
    )
    with pytest.raises(PermissionError, match="Symlink paths"):
        apply_proposal(root, proposal_id, confirm=True)
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


def test_apply_hashes_the_exact_proposal_bytes_it_decodes(tmp_path, monkeypatch):
    root, proposal_id = make_repo(tmp_path)
    proposal = root / ".aurix" / "proposals" / f"{proposal_id}.diff"
    original = proposal.read_bytes()
    replacement = (
        b"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n"
        b"-value = 'old'\n+value = 'unexpected'\n"
    )
    original_read_text = Path.read_text

    def race_proposal_read(path, *args, **kwargs):
        if path == proposal:
            proposal.write_bytes(replacement)
            return original.decode("utf-8")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", race_proposal_read)
    result = apply_proposal(root, proposal_id, confirm=True)
    assert result["status"] == "applied"
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'new'\n"
    assert proposal.read_bytes() == original



def test_recovery_history_rejects_symlink_journal(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    journal_dir = root / ".aurix" / "transactions"
    journal_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"proposal_id": proposal_id, "recovery_history": []}), encoding="utf-8")
    (journal_dir / f"{proposal_id}.json").symlink_to(outside)
    report = verify_recovery_histories(root)
    assert report["status"] == "invalid"
    assert report["invalid"] == 1
    assert report["results"][0]["status"] == "invalid"


def test_recovery_history_rejects_oversized_journal(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    journal_dir = root / ".aurix" / "transactions"
    journal_dir.mkdir()
    (journal_dir / f"{proposal_id}.json").write_bytes(b" " * 1_000_001)
    report = verify_recovery_histories(root)
    assert report["status"] == "invalid"
    assert report["invalid"] == 1
    assert "size limit" in report["results"][0]["reason"]


def test_recovery_anchor_rejects_oversized_file(tmp_path):
    root, _ = make_repo(tmp_path)
    anchor = tmp_path / "recovery.json"
    anchor.write_bytes(b" " * 5_000_001)
    report = verify_recovery_histories(root, anchor)
    assert report["status"] == "invalid"
    assert report["anchor"]["status"] == "invalid"
    assert "size limit" in report["anchor"]["reason"]

def test_recover_transaction_rejects_oversized_journal(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    journal_dir = root / ".aurix" / "transactions"
    journal_dir.mkdir()
    (journal_dir / f"{proposal_id}.json").write_bytes(b" " * 1_000_001)

    with pytest.raises(PermissionError, match="journal is unreadable"):
        recover_transaction(root, proposal_id, confirm=True)




def test_target_snapshot_hashes_regular_file_without_loading_entire_contents(tmp_path):
    from aurix.tools.patches import _hash_regular_file_snapshot

    target = tmp_path / "target.py"
    payload = b"value = 42\n" * 1000
    target.write_bytes(payload)
    assert _hash_regular_file_snapshot(target, label="Patch target") == hashlib.sha256(payload).hexdigest()


def test_target_snapshot_rejects_symlink(tmp_path):
    from aurix.tools.patches import _hash_regular_file_snapshot

    target = tmp_path / "target.py"
    outside = tmp_path / "outside.py"
    outside.write_text("secret\n", encoding="utf-8")
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(PermissionError, match="must not be a symlink"):
        _hash_regular_file_snapshot(target, label="Patch target")


def test_target_snapshot_detects_concurrent_file_change(tmp_path, monkeypatch):
    from aurix.tools import patches

    target = tmp_path / "target.py"
    target.write_bytes(b"x" * 100_000)
    original_read = patches.os.read
    changed = False

    def read_then_mutate(fd, size):
        nonlocal changed
        chunk = original_read(fd, size)
        if chunk and not changed:
            changed = True
            with target.open("ab") as stream:
                stream.write(b"concurrent change")
                stream.flush()
        return chunk

    monkeypatch.setattr(patches.os, "read", read_then_mutate)
    with pytest.raises(PermissionError, match="changed while"):
        patches._hash_regular_file_snapshot(target, label="Patch target")



def test_stale_journal_temp_does_not_block_atomic_update(tmp_path):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    journal_dir = root / ".aurix" / "transactions"
    journal_dir.mkdir(parents=True, exist_ok=True)
    stale = journal_dir / f"{proposal_id}.json.123.tmp"
    stale.write_text("left by an interrupted prior process", encoding="utf-8")

    record = {"schema_version": 1, "proposal_id": proposal_id, "state": "rolled_back"}
    patches._write_transaction_journal(root, proposal_id, record)

    journal = journal_dir / f"{proposal_id}.json"
    assert json.loads(journal.read_text(encoding="utf-8")) == record
    assert stale.read_text(encoding="utf-8") == "left by an interrupted prior process"
    assert not list(journal_dir.glob(f"{proposal_id}.json.*.tmp")) or list(
        journal_dir.glob(f"{proposal_id}.json.*.tmp")
    ) == [stale]



def test_apply_audit_failure_rolls_back_and_records_terminal_journal(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)

    def fail_audit(*args, **kwargs):
        raise OSError("simulated audit storage failure")

    monkeypatch.setattr(patches, "append_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="Audit logging failed"):
        patches.apply_proposal(root, proposal_id, confirm=True)

    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"
    journal = json.loads(
        (root / ".aurix" / "transactions" / f"{proposal_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["state"] == "rolled_back"
    assert journal["recovery"] == "verified"



def test_apply_detects_same_target_edit_racing_git_apply(tmp_path, monkeypatch):
    """Do not mark a patch audited if a concurrent edit is bundled into its target."""
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    original_git = patches._git
    injected = False

    def race_target_then_apply(workspace, args, **kwargs):
        nonlocal injected
        result = original_git(workspace, args, **kwargs)
        if (
            not injected
            and args == ["apply", "--whitespace=error", "-"]
            and kwargs.get("patch")
            and result.returncode == 0
        ):
            injected = True
            target = root / "app.py"
            target.write_text(
                target.read_text(encoding="utf-8") + "# concurrent edit\n",
                encoding="utf-8",
            )
        return result

    monkeypatch.setattr(patches, "_git", race_target_then_apply)
    with pytest.raises(RuntimeError, match="Applied target contents differ"):
        apply_proposal(root, proposal_id, confirm=True)

    assert injected is True
    # The inverse no longer applies exactly, so preserve both the proposal and
    # the concurrent edit for explicit manual recovery rather than risk data loss.
    assert (root / "app.py").read_text(encoding="utf-8") == (
        "value = 'new'\n# concurrent edit\n"
    )
    journal = json.loads(
        (root / ".aurix" / "transactions" / f"{proposal_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["state"] == "patch_applied"
    inventory = inspect_transactions(root)
    row = next(item for item in inventory["transactions"] if item["proposal_id"] == proposal_id)
    assert row["status"] == "manual_intervention_required"



def test_apply_detects_target_edit_during_audit_persistence(tmp_path, monkeypatch):
    """Do not mark a transaction terminal if a target changes during audit writing."""
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    original_audit = patches.append_audit_event
    injected = False

    def audit_then_race(workspace, event_type, current_id, details):
        nonlocal injected
        result = original_audit(workspace, event_type, current_id, details)
        if event_type == "proposal_applied" and not injected:
            injected = True
            target = root / "app.py"
            target.write_text(
                target.read_text(encoding="utf-8") + "# concurrent edit\n",
                encoding="utf-8",
            )
        return result

    monkeypatch.setattr(patches, "append_audit_event", audit_then_race)
    with pytest.raises(RuntimeError, match="after the application audit event"):
        apply_proposal(root, proposal_id, confirm=True)

    assert injected is True
    assert (root / "app.py").read_text(encoding="utf-8") == (
        "value = 'new'\n# concurrent edit\n"
    )
    journal = json.loads(
        (root / ".aurix" / "transactions" / f"{proposal_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["state"] == "patch_applied"
    inventory = inspect_transactions(root)
    row = next(item for item in inventory["transactions"] if item["proposal_id"] == proposal_id)
    assert row["status"] == "manual_intervention_required"


def test_apply_audit_failure_preserves_concurrent_unrelated_tracked_edit(tmp_path, monkeypatch):
    """Rollback may undo the exact proposal, but must never erase a concurrent edit."""
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    unrelated = root / "other.py"
    unrelated.write_text("value = 'baseline'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "other.py"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "add unrelated tracked file"],
        check=True,
        capture_output=True,
    )

    def edit_unrelated_then_fail(*args, **kwargs):
        unrelated.write_text("value = 'external edit'\n", encoding="utf-8")
        raise OSError("simulated audit storage failure after concurrent edit")

    monkeypatch.setattr(patches, "append_audit_event", edit_unrelated_then_fail)
    with pytest.raises(RuntimeError, match="final tracked status differs from expectation"):
        patches.apply_proposal(root, proposal_id, confirm=True)

    # The proposal's exact change was reversed, while the independent edit remains.
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"
    assert unrelated.read_text(encoding="utf-8") == "value = 'external edit'\n"
    journal = json.loads(
        (root / ".aurix" / "transactions" / f"{proposal_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["state"] == "patch_applied"
    inventory = patches.inspect_transactions(root)
    row = next(item for item in inventory["transactions"] if item["proposal_id"] == proposal_id)
    assert row["status"] == "manual_intervention_required"


def test_apply_terminal_journal_failure_is_reported_as_interrupted(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    original_write = patches._write_transaction_journal

    def fail_terminal_write(workspace, current_id, record):
        if record.get("state") == "applied_and_audited":
            raise OSError("simulated terminal journal write failure")
        return original_write(workspace, current_id, record)

    monkeypatch.setattr(patches, "_write_transaction_journal", fail_terminal_write)
    with pytest.raises(OSError, match="terminal journal write failure"):
        patches.apply_proposal(root, proposal_id, confirm=True)

    # The audit event and applied patch may already exist, but the journal remains
    # non-terminal. It must not be represented as a completed transaction.
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'new'\n"
    journal = json.loads(
        (root / ".aurix" / "transactions" / f"{proposal_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["state"] == "patch_applied"
    inventory = patches.inspect_transactions(root)
    row = next(item for item in inventory["transactions"] if item["proposal_id"] == proposal_id)
    assert row["status"] == "manual_intervention_required"


def test_audit_gate_rejects_non_boolean_passing_result(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    _write_passing_audit(root, proposal_id)
    path = root / ".aurix" / "audits" / f"{proposal_id}.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    audit["verification"]["test_result"]["passed"] = "false"
    verification = audit["verification"]
    evidence = {
        key: verification.get(key)
        for key in (
            "audit_id", "verification_id", "proposal_id", "proposal_sha256",
            "base_commit", "target_state_sha256", "suite", "requested_suite",
            "test_selection", "isolation", "sandbox_image", "sandbox_image_id",
            "runtime_fingerprint", "baseline_result", "test_result", "regression_status",
        )
    }
    verification["evidence_sha256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    path.write_text(json.dumps(audit), encoding="utf-8")

    with pytest.raises(PermissionError, match="exact patch"):
        apply_proposal(root, proposal_id, confirm=True, require_audit_gate=True)
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("baseline_result", {"passed": False, "returncode": 1}),
        ("test_result", {"passed": True, "returncode": 1}),
    ],
)
def test_audit_gate_rejects_failed_process_exit_codes(tmp_path, field, value):
    root, proposal_id = make_repo(tmp_path)
    _write_passing_audit(root, proposal_id)
    path = root / ".aurix" / "audits" / f"{proposal_id}.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    verification = audit["verification"]
    verification[field] = value
    evidence = {
        key: verification.get(key)
        for key in (
            "audit_id", "verification_id", "proposal_id", "proposal_sha256",
            "base_commit", "target_state_sha256", "suite", "requested_suite",
            "test_selection", "isolation", "sandbox_image", "sandbox_image_id",
            "runtime_fingerprint", "baseline_result", "test_result", "regression_status",
        )
    }
    verification["evidence_sha256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    path.write_text(json.dumps(audit), encoding="utf-8")

    with pytest.raises(PermissionError, match="exact patch"):
        apply_proposal(root, proposal_id, confirm=True, require_audit_gate=True)
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"



def test_inspection_cross_checks_applied_journal_with_verified_audit_event(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["state"] = "reverted_and_audited"
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    report = inspect_transactions(root)

    assert report["status"] == "manual_intervention_required"
    row = report["transactions"][0]
    assert row["status"] == "manual_intervention_required"
    assert "lifecycle audit event does not match" in row["reason"]


def test_inspection_rejects_corrupted_audit_chain_for_terminal_journal(tmp_path):
    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    audit_path = root / ".aurix" / "audit.jsonl"
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    events[-1]["event"] = "proposal_reverted"
    audit_path.write_text(
        "".join(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )

    report = inspect_transactions(root)

    assert report["status"] == "manual_intervention_required"
    row = report["transactions"][0]
    assert row["status"] == "manual_intervention_required"
    assert "audit log hash chain is invalid" in row["reason"]


def test_inspection_rejects_valid_chain_with_wrong_patch_digest(tmp_path):
    import hashlib

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    audit_path = root / ".aurix" / "audit.jsonl"
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    events[-1]["details"]["patch_sha256"] = "0" * 64
    event = dict(events[-1])
    event.pop("event_hash")
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    previous = event["previous_hash"]
    events[-1]["event_hash"] = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
    audit_path.write_text(
        "".join(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n" for item in events),
        encoding="utf-8",
    )

    report = inspect_transactions(root)

    assert report["status"] == "manual_intervention_required"
    row = report["transactions"][0]
    assert row["status"] == "manual_intervention_required"
    assert "lifecycle audit event does not match" in row["reason"]


def test_inspection_flags_audit_written_before_apply_journal_finalization_failure(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    original_write = patches._write_transaction_journal

    def fail_terminal_write(workspace, transaction_id, record):
        if record.get("state") == "applied_and_audited":
            raise OSError("simulated terminal journal write failure")
        return original_write(workspace, transaction_id, record)

    monkeypatch.setattr(patches, "_write_transaction_journal", fail_terminal_write)
    with pytest.raises(OSError, match="terminal journal write failure"):
        apply_proposal(root, proposal_id, confirm=True)

    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (root / ".aurix" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert journal["state"] == "patch_applied"
    assert events[-1]["event"] == "proposal_applied"
    report = inspect_transactions(root)
    assert report["status"] == "manual_intervention_required"
    assert report["transactions"][0]["status"] == "manual_intervention_required"


def test_inspection_flags_audit_written_before_revert_journal_finalization_failure(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    original_write = patches._write_transaction_journal

    def fail_terminal_write(workspace, transaction_id, record):
        if record.get("state") == "reverted_and_audited":
            raise OSError("simulated terminal journal write failure")
        return original_write(workspace, transaction_id, record)

    monkeypatch.setattr(patches, "_write_transaction_journal", fail_terminal_write)
    with pytest.raises(OSError, match="terminal journal write failure"):
        revert_proposal(root, proposal_id, confirm=True)

    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (root / ".aurix" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert journal["state"] == "reverting"
    assert events[-1]["event"] == "proposal_reverted"
    report = inspect_transactions(root)
    assert report["status"] == "manual_intervention_required"
    assert report["transactions"][0]["status"] == "manual_intervention_required"


def test_inspection_flags_recovery_finalized_without_recovery_audit_event(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.update(state="patch_applied", recovery="pending_verification")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    original_append = patches.append_audit_event

    def fail_recovery_event(workspace, event, transaction_id, details):
        if event == "transaction_recovered":
            raise OSError("simulated recovery audit failure")
        return original_append(workspace, event, transaction_id, details)

    monkeypatch.setattr(patches, "append_audit_event", fail_recovery_event)
    with pytest.raises(RuntimeError, match="recovery audit event could not be persisted"):
        recover_transaction(root, proposal_id, confirm=True)

    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["state"] == "rolled_back"
    report = inspect_transactions(root)
    row = report["transactions"][0]
    assert row["status"] == "manual_intervention_required"
    assert "recovery audit event does not match" in row["reason"]
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"


def test_inspection_flags_finalization_without_finalization_audit_event(tmp_path, monkeypatch):
    from aurix.tools import patches

    root, proposal_id = make_repo(tmp_path)
    apply_proposal(root, proposal_id, confirm=True)
    journal_path = root / ".aurix" / "transactions" / f"{proposal_id}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    patch = (root / ".aurix" / "proposals" / f"{proposal_id}.diff").read_text(encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "apply", "--reverse", "-"],
        input=patch,
        text=True,
        check=True,
        capture_output=True,
    )
    journal.update(state="recovery_interrupted", recovery="manual_intervention_required")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    original_append = patches.append_audit_event

    def fail_finalization_event(workspace, event, transaction_id, details):
        if event == "transaction_recovery_finalized":
            raise OSError("simulated finalization audit failure")
        return original_append(workspace, event, transaction_id, details)

    monkeypatch.setattr(patches, "append_audit_event", fail_finalization_event)
    with pytest.raises(RuntimeError, match="recovery-finalization audit event"):
        finalize_interrupted_recovery(root, proposal_id, confirm=True)

    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["state"] == "rolled_back"
    report = inspect_transactions(root)
    row = report["transactions"][0]
    assert row["status"] == "manual_intervention_required"
    assert "recovery audit event does not match" in row["reason"]
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"
