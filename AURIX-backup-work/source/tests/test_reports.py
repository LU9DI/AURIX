import json

import pytest

from aurix.orchestrator import TaskResult
from aurix.reports import attach_audit_to_run_report, write_run_report


def _valid_audit(tmp_path, *, proposal_id="a1b2c3d4e5f6", **overrides):
    import hashlib

    proposal_dir = tmp_path / ".aurix" / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    proposal_path = proposal_dir / f"{proposal_id}.diff"
    proposal_path.write_text("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8")
    audit = {
        "proposal_id": proposal_id,
        "proposal_sha256": hashlib.sha256(proposal_path.read_bytes()).hexdigest(),
        "audited_at": "2026-10-08T12:00:00+00:00",
        "status": "audit_needs_attention",
        "review": {"risk_level": "medium", "finding_count": 1},
        "verification": {"status": "not_run"},
        "application": {"performed": False},
    }
    audit.update(overrides)
    return audit


def test_write_run_report_contains_metadata_not_raw_tool_results(tmp_path):
    result = TaskResult("completed", "Inspected files.", 1, [{"step": 1, "tool": "list_files", "tool_result_chars": 42}])
    saved = write_run_report(tmp_path, "reports/run.json", task="Inspect source", result=result, provider="FakeProvider")
    data = json.loads((tmp_path / "reports/run.json").read_text(encoding="utf-8"))
    assert saved["status"] == "written"
    assert data["schema_version"] == 2
    assert data["artifacts"]["proposals"] == []
    assert data["task"] == "Inspect source"
    assert data["result"]["status"] == "completed"
    assert "message" not in data["result"]
    assert data["safety"]["contains_raw_prompts_or_completions"] is False
    assert "actual tool-result body" not in json.dumps(data)


def test_run_report_persists_memory_provenance_without_memory_text(tmp_path):
    evidence = [{
        "id": 7, "scope": "repo:alpha", "kind": "fact",
        "relevance_score": 0.82, "retrieval_mode": "lexical",
        "matched_terms": ["auth", "token"],
    }]
    result = TaskResult("completed", "Inspected files.", 1, [], evidence)
    write_run_report(tmp_path, "reports/memory.json", task="Inspect auth", result=result, provider="Fake")
    data = json.loads((tmp_path / "reports/memory.json").read_text(encoding="utf-8"))
    assert data["memory_evidence"] == evidence
    assert "content" not in data["memory_evidence"][0]
    assert data["integrity"]["digest"]


def test_report_rejects_absolute_and_traversal_paths(tmp_path):
    result = TaskResult("completed", "ok", 1, [])
    with pytest.raises(ValueError):
        write_run_report(tmp_path, tmp_path / "outside.json", task="x", result=result, provider="P")
    with pytest.raises(PermissionError):
        write_run_report(tmp_path, "../outside.json", task="x", result=result, provider="P")


def test_report_rejects_symlink_destination(tmp_path):
    result = TaskResult("completed", "ok", 1, [])
    outside = tmp_path.parent / (tmp_path.name + "-outside.json")
    outside.write_text("keep", encoding="utf-8")
    (tmp_path / "report.json").symlink_to(outside)
    with pytest.raises(PermissionError):
        write_run_report(tmp_path, "report.json", task="x", result=result, provider="P")
    assert outside.read_text(encoding="utf-8") == "keep"


def test_report_rejects_internal_metadata_path(tmp_path):
    result = TaskResult("completed", "ok", 1, [])
    with pytest.raises(PermissionError):
        write_run_report(tmp_path, ".aurix/runs.jsonl", task="x", result=result, provider="P")


def test_report_links_proposals_without_storing_patch_content(tmp_path):
    proposal_id = "a1b2c3d4e5f6"
    result = TaskResult("completed", "Prepared a patch", 1, [{
        "step": 1, "tool": "propose_patch", "tool_status": "review_required",
        "proposal_id": proposal_id, "tool_result_chars": 190,
    }])
    write_run_report(tmp_path, "run.json", task="Improve module", result=result, provider="Fake")
    data = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert data["artifacts"]["proposals"] == [{"proposal_id": proposal_id, "status": "review_required"}]
    assert "old\n+new" not in json.dumps(data)


def test_report_ignores_malformed_proposal_identifiers(tmp_path):
    result = TaskResult("completed", "ok", 1, [{"proposal_id": "../../outside"}])
    write_run_report(tmp_path, "run.json", task="x", result=result, provider="Fake")
    data = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert data["artifacts"]["proposals"] == []


def test_attach_audit_to_run_report_persists_compact_evidence(tmp_path):
    result = TaskResult("completed", "Prepared a patch", 1, [])
    write_run_report(tmp_path, "reports/run.json", task="Improve module", result=result, provider="Fake")
    audit = _valid_audit(tmp_path, review={"risk_level": "medium", "finding_count": 2},
                         verification={"status": "verified_fail", "suite": "pytest",
                                       "test_result": {"stdout": "SECRET TEST OUTPUT"}})
    attached = attach_audit_to_run_report(tmp_path, "reports/run.json", audit_result=audit)
    saved = json.loads((tmp_path / "reports/run.json").read_text(encoding="utf-8"))
    assert attached["status"] == "updated"
    assert saved["artifacts"]["audits"][0]["verification_status"] == "verified_fail"
    assert saved["artifacts"]["audits"][0]["proposal_sha256"] == audit["proposal_sha256"]
    assert "SECRET TEST OUTPUT" not in json.dumps(saved)


def test_attach_audit_requires_existing_v2_report(tmp_path):
    with pytest.raises(FileNotFoundError):
        attach_audit_to_run_report(tmp_path, "missing.json", audit_result={})
    (tmp_path / "old.json").write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        attach_audit_to_run_report(tmp_path, "old.json", audit_result={})


def test_attach_audit_rejects_symlink_report(tmp_path):
    result = TaskResult("completed", "ok", 1, [])
    write_run_report(tmp_path, "run.json", task="x", result=result, provider="Fake")
    outside = tmp_path.parent / (tmp_path.name + "-outside-audit.json")
    outside.write_text("{}", encoding="utf-8")
    (tmp_path / "alias.json").symlink_to(outside)
    with pytest.raises(PermissionError):
        attach_audit_to_run_report(tmp_path, "alias.json", audit_result={})
    assert outside.read_text(encoding="utf-8") == "{}"


def test_run_report_integrity_verifies_then_detects_tampering(tmp_path):
    from aurix.reports import verify_run_report

    result = TaskResult("completed", "ok", 1, [])
    write_run_report(tmp_path, "run.json", task="Inspect", result=result, provider="Fake")
    verified = verify_run_report(tmp_path, "run.json")
    assert verified["status"] == "valid"
    assert verified["valid"] is True

    report_path = tmp_path / "run.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["task"] = "Tampered task"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    tampered = verify_run_report(tmp_path, "run.json")
    assert tampered["status"] == "tampered"
    assert tampered["valid"] is False


def test_audit_attachment_refreshes_integrity_digest(tmp_path):
    from aurix.reports import verify_run_report

    result = TaskResult("completed", "Prepared a patch", 1, [])
    write_run_report(tmp_path, "run.json", task="Improve module", result=result, provider="Fake")
    audit = _valid_audit(tmp_path)
    attach_audit_to_run_report(tmp_path, "run.json", audit_result=audit)
    assert verify_run_report(tmp_path, "run.json")["valid"] is True


def test_run_report_without_integrity_is_not_treated_as_valid(tmp_path):
    from aurix.reports import verify_run_report

    (tmp_path / "legacy.json").write_text(json.dumps({"schema_version": 2, "run_id": "legacy"}), encoding="utf-8")
    result = verify_run_report(tmp_path, "legacy.json")
    assert result["status"] == "missing_integrity"
    assert result["valid"] is False


def test_attach_audit_refuses_tampered_report_instead_of_rehashing(tmp_path):
    from aurix.reports import verify_run_report

    result = TaskResult("completed", "ok", 1, [])
    write_run_report(tmp_path, "run.json", task="Original task", result=result, provider="Fake")
    path = tmp_path / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["task"] = "Changed after creation"
    path.write_text(json.dumps(data), encoding="utf-8")
    audit = _valid_audit(tmp_path)
    with pytest.raises(ValueError, match="tampered"):
        attach_audit_to_run_report(tmp_path, "run.json", audit_result=audit)
    assert verify_run_report(tmp_path, "run.json")["status"] == "tampered"


def test_audit_attachment_preserves_previous_report_digest(tmp_path):
    from aurix.reports import verify_run_report

    result = TaskResult("completed", "ok", 1, [])
    write_run_report(tmp_path, "run.json", task="Inspect", result=result, provider="Fake")
    before = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    old_digest = before["integrity"]["digest"]
    audit = _valid_audit(tmp_path, status="reviewed_verification_not_run",
                         review={"risk_level": "low", "finding_count": 0})
    attached = attach_audit_to_run_report(tmp_path, "run.json", audit_result=audit)
    after = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert attached["previous_digest"] == old_digest
    assert after["integrity_history"][0]["digest"] == old_digest
    assert after["integrity"]["digest"] != old_digest
    assert verify_run_report(tmp_path, "run.json")["valid"] is True


def test_attach_audit_rejects_malformed_nested_metadata(tmp_path):
    result = TaskResult("completed", "ok", 1, [])
    write_run_report(tmp_path, "run.json", task="Inspect", result=result, provider="Fake")
    audit = {
        "proposal_id": "a1b2c3d4e5f6", "proposal_sha256": "e" * 64,
        "review": "not-an-object", "verification": {}, "application": {},
    }
    with pytest.raises(ValueError, match="nested metadata"):
        attach_audit_to_run_report(tmp_path, "run.json", audit_result=audit)


def test_attach_audit_rejects_digest_not_matching_current_proposal(tmp_path):
    result = TaskResult("completed", "ok", 1, [])
    write_run_report(tmp_path, "run.json", task="Inspect", result=result, provider="Fake")
    audit = _valid_audit(tmp_path)
    audit["proposal_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="does not match"):
        attach_audit_to_run_report(tmp_path, "run.json", audit_result=audit)


def test_attach_audit_rejects_truthy_string_for_application_boolean(tmp_path):
    result = TaskResult("completed", "ok", 1, [])
    write_run_report(tmp_path, "run.json", task="Inspect", result=result, provider="Fake")
    audit = _valid_audit(tmp_path, application={"performed": "false"})
    with pytest.raises(ValueError, match="boolean"):
        attach_audit_to_run_report(tmp_path, "run.json", audit_result=audit)


def test_attach_audit_rejects_negative_finding_count(tmp_path):
    result = TaskResult("completed", "ok", 1, [])
    write_run_report(tmp_path, "run.json", task="Inspect", result=result, provider="Fake")
    audit = _valid_audit(tmp_path, review={"risk_level": "low", "finding_count": -1})
    with pytest.raises(ValueError, match="finding count"):
        attach_audit_to_run_report(tmp_path, "run.json", audit_result=audit)
