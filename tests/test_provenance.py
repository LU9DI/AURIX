import json

import pytest

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
