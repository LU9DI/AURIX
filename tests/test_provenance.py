import json

import pytest

import aurix.tools.provenance as provenance
from aurix.tools.provenance import append_audit_event, register_proposal, verify_proposal_integrity
from aurix.tools.review import review_proposal


def test_manifest_detects_proposal_tampering(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_text("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8")
    register_proposal(tmp_path, proposal, "abcdef123456")
    assert verify_proposal_integrity(proposal, "abcdef123456")["integrity"] == "verified"
    proposal.write_text(proposal.read_text(encoding="utf-8") + "# altered\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="changed"):
        review_proposal(tmp_path, "abcdef123456")


def test_audit_log_rejects_non_object_event(tmp_path):
    log_dir = tmp_path / ".aurix"
    log_dir.mkdir()
    (log_dir / "audit.jsonl").write_text('[]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="integrity check"):
        append_audit_event(tmp_path, "proposal_reviewed", "abcdef123456")


def test_audit_log_rejects_duplicate_json_keys(tmp_path):
    log_dir = tmp_path / ".aurix"
    log_dir.mkdir()
    (log_dir / "audit.jsonl").write_text(
        '{"event":"one","event":"two","event_hash":"0"}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="integrity check"):
        append_audit_event(tmp_path, "proposal_reviewed", "abcdef123456")


def test_manifest_rejects_boolean_schema_version(tmp_path):
    import hashlib

    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_text("patch", encoding="utf-8")
    manifest = {
        "schema_version": True,
        "proposal_id": "abcdef123456",
        "sha256": hashlib.sha256(b"patch").hexdigest(),
        "size_bytes": 5,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    proposal.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        verify_proposal_integrity(proposal, "abcdef123456")


def test_manifest_rejects_boolean_size_bytes(tmp_path):
    import hashlib

    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_text("x", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "proposal_id": "abcdef123456",
        "sha256": hashlib.sha256(b"x").hexdigest(),
        "size_bytes": True,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    proposal.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PermissionError, match="changed"):
        verify_proposal_integrity(proposal, "abcdef123456")


def test_manifest_rejects_malformed_sha256(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_text("x", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "proposal_id": "abcdef123456",
        "sha256": "not-a-digest",
        "size_bytes": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    proposal.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PermissionError, match="changed"):
        verify_proposal_integrity(proposal, "abcdef123456")


def test_manifest_rejects_duplicate_json_keys(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_text("patch", encoding="utf-8")
    proposal.with_suffix(".json").write_text(
        '{"schema_version":1,"schema_version":1,"proposal_id":"abcdef123456"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unreadable"):
        verify_proposal_integrity(proposal, "abcdef123456")


def test_audit_hash_chain_detects_modified_event(tmp_path):
    append_audit_event(tmp_path, "proposal_created", "abcdef123456", {"sha256": "abc"})
    append_audit_event(tmp_path, "proposal_reviewed", "abcdef123456", {"risk_level": "low"})
    log = tmp_path / ".aurix" / "audit.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["event"] = "forged"
    lines[0] = json.dumps(event)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash chain"):
        append_audit_event(tmp_path, "proposal_reviewed", "abcdef123456")


def test_manifest_identity_mismatch_rejected(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_text("--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n", encoding="utf-8")
    register_proposal(tmp_path, proposal, "abcdef123456")
    with pytest.raises(ValueError, match="identity"):
        verify_proposal_integrity(proposal, "000000000000")



def test_audit_append_refuses_existing_lock_without_mutating_log(tmp_path):
    metadata = tmp_path / ".aurix"
    metadata.mkdir()
    lock = metadata / "audit.lock"
    lock.write_text('{"pid": 123, "created_at": 1}', encoding="utf-8")
    before = lock.read_bytes()

    with pytest.raises(PermissionError, match="Audit append is already running"):
        append_audit_event(tmp_path, "proposal_reviewed", "abcdef123456")

    assert lock.read_bytes() == before
    assert not (metadata / "audit.jsonl").exists()


def test_audit_append_lock_is_released_after_success(tmp_path):
    append_audit_event(tmp_path, "proposal_created", "abcdef123456")
    assert not (tmp_path / ".aurix" / "audit.lock").exists()
    append_audit_event(tmp_path, "proposal_reviewed", "abcdef123456")
    assert len((tmp_path / ".aurix" / "audit.jsonl").read_text(encoding="utf-8").splitlines()) == 2



def test_manifest_verification_checks_the_supplied_byte_snapshot(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_bytes(b"original")
    register_proposal(tmp_path, proposal, "abcdef123456")
    snapshot = proposal.read_bytes()
    proposal.write_bytes(b"tampered")

    with pytest.raises(PermissionError, match="changed"):
        verify_proposal_integrity(
            proposal, "abcdef123456", proposal_bytes=snapshot + b"extra"
        )



def test_manifest_dangling_symlink_is_not_treated_as_legacy(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_bytes(b"patch")
    manifest = proposal.with_suffix(".json")
    try:
        manifest.symlink_to(tmp_path / "missing-manifest-target")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    with pytest.raises(PermissionError, match="Unsafe proposal manifest"):
        verify_proposal_integrity(proposal, "abcdef123456")



def test_manifest_directory_is_rejected(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_bytes(b"patch")
    proposal.with_suffix(".json").mkdir()

    with pytest.raises(PermissionError, match="Unsafe proposal manifest"):
        verify_proposal_integrity(proposal, "abcdef123456")


def test_manifest_over_size_limit_is_rejected(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_bytes(b"patch")
    proposal.with_suffix(".json").write_bytes(b" " * 16_385)

    with pytest.raises(PermissionError, match="Unsafe proposal manifest"):
        verify_proposal_integrity(proposal, "abcdef123456")



def test_audit_log_symlink_is_rejected(tmp_path):
    metadata = tmp_path / ".aurix"
    metadata.mkdir()
    target = tmp_path / "audit-target.jsonl"
    target.write_text("", encoding="utf-8")
    log = metadata / "audit.jsonl"
    try:
        log.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    with pytest.raises(PermissionError, match="Audit log must not be a symlink"):
        append_audit_event(tmp_path, "proposal_reviewed", "abcdef123456")


def test_audit_log_directory_is_rejected(tmp_path):
    metadata = tmp_path / ".aurix"
    metadata.mkdir()
    (metadata / "audit.jsonl").mkdir()

    with pytest.raises(ValueError, match="bounded regular file"):
        append_audit_event(tmp_path, "proposal_reviewed", "abcdef123456")



def test_register_proposal_removes_unchanged_manifest_when_audit_fails(tmp_path, monkeypatch):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_text("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8")

    def fail_audit(*args, **kwargs):
        raise OSError("simulated audit failure")

    monkeypatch.setattr(provenance, "append_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="creation audit event failed"):
        register_proposal(tmp_path, proposal, "abcdef123456")
    assert not (proposal_dir / "abcdef123456.manifest.json").exists()


def test_register_proposal_preserves_manifest_replaced_during_audit_failure(
    tmp_path, monkeypatch
):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_text("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8")
    manifest_path = proposal_dir / "abcdef123456.manifest.json"
    replacement = b'{"replacement":true}\n'

    def replace_then_fail(*args, **kwargs):
        manifest_path.write_bytes(replacement)
        raise OSError("simulated audit failure after replacement")

    monkeypatch.setattr(provenance, "append_audit_event", replace_then_fail)
    with pytest.raises(RuntimeError, match="creation audit event failed"):
        register_proposal(tmp_path, proposal, "abcdef123456")
    assert manifest_path.read_bytes() == replacement



def test_register_proposal_rejects_symlink_input(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    outside = tmp_path / "outside.diff"
    outside.write_text("safe diff", encoding="utf-8")
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.symlink_to(outside)
    with pytest.raises(PermissionError, match="symlink"):
        register_proposal(tmp_path, proposal, "abcdef123456")


def test_register_proposal_rejects_oversized_input(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.write_bytes(b"x" * 100_001)
    with pytest.raises(ValueError, match="size limit"):
        register_proposal(tmp_path, proposal, "abcdef123456")


def test_verify_proposal_integrity_rejects_symlink_input(tmp_path):
    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True)
    outside = tmp_path / "outside.diff"
    outside.write_text("safe diff", encoding="utf-8")
    proposal = proposal_dir / "abcdef123456.diff"
    proposal.symlink_to(outside)
    with pytest.raises(PermissionError, match="symlink"):
        verify_proposal_integrity(proposal, "abcdef123456")

def test_atomic_write_uses_unique_temp_and_preserves_stale_temp(tmp_path):
    target = tmp_path / "manifest.json"
    stale_temp = tmp_path / "manifest.json.tmp"
    stale_temp.write_bytes(b"unrelated stale file")

    provenance._atomic_write(target, b'{"safe":true}\\n')

    assert target.read_bytes() == b'{"safe":true}\\n'
    assert stale_temp.read_bytes() == b"unrelated stale file"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "manifest.json",
        "manifest.json.tmp",
    ]

