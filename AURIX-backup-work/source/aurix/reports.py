"""Explicit, local run reports with path and symlink protections."""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aurix.tools.patches import _proposal_path


def _report_digest(report: dict[str, Any]) -> str:
    """Hash canonical report content, excluding the digest envelope itself."""
    payload = {key: value for key, value in report.items() if key != "integrity"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _refresh_integrity(report: dict[str, Any]) -> None:
    report["integrity"] = {
        "algorithm": "sha256",
        "scope": "canonical-json-excluding-integrity",
        "digest": _report_digest(report),
    }


def verify_run_report(workspace: str | Path, destination: str | Path) -> dict[str, Any]:
    """Verify the integrity digest of an existing report without modifying it."""
    root = Path(workspace).expanduser().resolve(strict=True)
    raw = Path(destination).expanduser()
    if raw.is_absolute() or not raw.parts:
        raise ValueError("Report destination must be a relative path inside the workspace")
    if any(part in {"..", ".git", ".aurix"} for part in raw.parts):
        raise PermissionError("Report destination contains a prohibited path component")
    target = root / raw
    cursor = root
    for part in raw.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PermissionError("Symlink components are not allowed in report destinations")
    if not target.is_file():
        raise FileNotFoundError("Run report does not exist")
    if target.stat().st_size > 2_000_000:
        raise ValueError("Run report exceeds the 2 MB size limit")
    try:
        report = json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Run report is not valid UTF-8 JSON") from exc
    if not isinstance(report, dict) or report.get("schema_version") != 2:
        raise ValueError("Integrity verification requires a schema-version-2 run report")
    integrity = report.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        return {"status": "missing_integrity", "valid": False,
                "path": target.relative_to(root).as_posix(), "run_id": report.get("run_id")}
    expected = integrity.get("digest")
    actual = _report_digest(report)
    valid = isinstance(expected, str) and expected == actual
    return {"status": "valid" if valid else "tampered", "valid": valid,
            "path": target.relative_to(root).as_posix(), "run_id": report.get("run_id"),
            "algorithm": "sha256", "expected_digest": expected, "actual_digest": actual}


def write_run_report(workspace: str | Path, destination: str | Path, *, task: str, result: Any, provider: str) -> dict[str, Any]:
    """Write a report only when explicitly requested; destination must be inside workspace.

    Reports include the user's task and trace metadata, but never prompts, completions, or tool-result bodies.
    Existing symlinks are refused to prevent writes escaping the workspace.
    """
    root = Path(workspace).expanduser().resolve()
    raw = Path(destination).expanduser()
    if raw.is_absolute():
        raise ValueError("Report destination must be a relative path inside the workspace")
    if not task.strip():
        raise ValueError("Task must not be empty")
    if len(task) > 20_000:
        raise ValueError("Task exceeds the 20000-character report limit")
    if any(part in {"..", ".git"} for part in raw.parts) or not raw.parts:
        raise PermissionError("Report destination contains a prohibited path component")
    if any(part == ".aurix" for part in raw.parts):
        raise PermissionError("Report destination may not write into AURIX internal metadata")
    target = root / raw
    cursor = root
    for part in raw.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PermissionError("Symlink components are not allowed in report destinations")
    resolved_parent = target.parent.resolve()
    if not resolved_parent.is_relative_to(root):
        raise PermissionError("Report destination must remain inside the workspace")
    if target.exists() and not target.is_file():
        raise ValueError("Report destination must be a regular file")
    proposals = []
    for item in result.trace:
        if not isinstance(item, dict):
            continue
        proposal_id = item.get("proposal_id")
        if isinstance(proposal_id, str) and len(proposal_id) == 12 and all(c in "0123456789abcdef" for c in proposal_id):
            proposals.append({"proposal_id": proposal_id, "status": item.get("tool_status", "unknown")})
    report = {
        "schema_version": 2,
        "run_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task": task.strip(),
        "workspace": ".",
        "provider": provider,
        "result": {"status": result.status, "message_chars": len(result.message), "steps": result.steps},
        "trace": result.trace,
        "memory_evidence": list(getattr(result, "memory_evidence", [])),
        "artifacts": {"proposals": proposals},
        "safety": {
            "autonomous_file_edits": False,
            "shell_execution_by_model": False,
            "contains_raw_prompts_or_completions": False,
            "note": "Trace contains metadata only; inspect proposals and test output separately.",
        },
    }
    _refresh_integrity(report)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after creating directories to guard against a symlink introduced during setup.
    cursor = root
    for part in raw.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PermissionError("Symlink components are not allowed in report destinations")
    fd, temp_name = tempfile.mkstemp(prefix=".aurix-report-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return {"path": target.relative_to(root).as_posix(), "run_id": report["run_id"], "status": "written", "schema_version": 2}


def attach_audit_to_run_report(
    workspace: str | Path, destination: str | Path, *, audit_result: dict[str, Any]
) -> dict[str, Any]:
    """Append compact audit evidence to an existing schema-v2 run report.

    Raw test output and full review findings are deliberately excluded. The report
    must already exist; this function never creates a misleading partial run.
    """
    root = Path(workspace).expanduser().resolve(strict=True)
    raw = Path(destination).expanduser()
    if raw.is_absolute() or not raw.parts:
        raise ValueError("Report destination must be a relative path inside the workspace")
    if any(part in {"..", ".git", ".aurix"} for part in raw.parts):
        raise PermissionError("Report destination contains a prohibited path component")
    target = root / raw
    cursor = root
    for part in raw.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PermissionError("Symlink components are not allowed in report destinations")
    if not target.is_file():
        raise FileNotFoundError("Run report must exist before attaching an audit")
    if target.stat().st_size > 2_000_000:
        raise ValueError("Run report exceeds the 2 MB size limit")
    try:
        report = json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Existing run report is not valid UTF-8 JSON") from exc
    if not isinstance(report, dict) or report.get("schema_version") != 2:
        raise ValueError("Audit attachment requires a schema-version-2 run report")
    if not isinstance(report.get("run_id"), str) or not isinstance(report.get("artifacts"), dict):
        raise ValueError("Run report is missing required identity or artifacts metadata")
    # Never silently bless a modified report by recalculating its digest during attachment.
    integrity = verify_run_report(root, raw)
    if integrity["status"] != "valid":
        raise ValueError(f"Cannot attach audit to report with integrity status: {integrity['status']}")
    if not isinstance(audit_result, dict):
        raise ValueError("Audit result must be an object")
    proposal_id = audit_result.get("proposal_id")
    proposal_digest = audit_result.get("proposal_sha256")
    if not isinstance(proposal_id, str) or len(proposal_id) != 12 or not all(c in "0123456789abcdef" for c in proposal_id):
        raise ValueError("Audit result has an invalid proposal identifier")
    if not isinstance(proposal_digest, str) or len(proposal_digest) != 64 or not all(c in "0123456789abcdef" for c in proposal_digest):
        raise ValueError("Audit result has an invalid proposal SHA-256 digest")

    verification = audit_result.get("verification", {})
    review = audit_result.get("review", {})
    application = audit_result.get("application", {})
    if not isinstance(verification, dict) or not isinstance(review, dict) or not isinstance(application, dict):
        raise ValueError("Audit result contains invalid nested metadata")

    audited_at = audit_result.get("audited_at")
    audit_status = audit_result.get("status", "unknown")
    risk_level = review.get("risk_level", "unknown")
    finding_count = review.get("finding_count", 0)
    verification_status = verification.get("status", "unknown")
    verification_suite = verification.get("suite")
    applied = application.get("performed", False)
    allowed_audit_statuses = {
        "reviewed_verification_not_run", "audit_passed", "audit_needs_attention",
    }
    allowed_risk_levels = {"low", "medium", "high", "unknown"}
    allowed_verification_statuses = {
        "not_run", "verified_pass", "verified_fail", "verification_failed", "refused",
    }
    if not isinstance(audited_at, str) or not audited_at or len(audited_at) > 80:
        raise ValueError("Audit result has an invalid audited_at timestamp")
    if audit_status not in allowed_audit_statuses:
        raise ValueError("Audit result has an unsupported status")
    if risk_level not in allowed_risk_levels:
        raise ValueError("Audit result has an unsupported risk level")
    if isinstance(finding_count, bool) or not isinstance(finding_count, int) or not 0 <= finding_count <= 100_000:
        raise ValueError("Audit result has an invalid finding count")
    if verification_status not in allowed_verification_statuses:
        raise ValueError("Audit result has an unsupported verification status")
    if verification_suite not in {None, "pytest", "ruff"}:
        raise ValueError("Audit result has an unsupported verification suite")
    if not isinstance(applied, bool):
        raise ValueError("Audit application metadata must use a boolean performed value")

    # Bind the evidence to the exact proposal bytes currently stored in the workspace.
    proposal_path = _proposal_path(root, proposal_id)
    actual_proposal_digest = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
    if actual_proposal_digest != proposal_digest:
        raise ValueError("Audit proposal digest does not match the current proposal file")

    compact = {
        "proposal_id": proposal_id,
        "proposal_sha256": proposal_digest,
        "audited_at": audited_at,
        "status": audit_status,
        "risk_level": risk_level,
        "finding_count": finding_count,
        "verification_status": verification_status,
        "verification_suite": verification_suite,
        "patch_applied": applied,
    }
    audits = report.setdefault("artifacts", {}).setdefault("audits", [])
    if not isinstance(audits, list):
        raise ValueError("Run report artifacts.audits must be a list")
    # Idempotent for the same proposal revision and audit timestamp.
    if any(isinstance(item, dict) and item.get("proposal_sha256") == compact["proposal_sha256"]
           and item.get("audited_at") == compact["audited_at"] for item in audits):
        return {"status": "unchanged", "path": target.relative_to(root).as_posix(),
                "run_id": report["run_id"], "audit_count": len(audits),
                "integrity": "valid"}

    # Preserve a compact digest history before updating the current report digest.
    previous_digest = report["integrity"]["digest"]
    history = report.setdefault("integrity_history", [])
    if not isinstance(history, list):
        raise ValueError("Run report integrity_history must be a list")
    history.append({
        "digest": previous_digest,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "reason": "audit_attachment",
    })
    audits.append(compact)

    _refresh_integrity(report)
    fd, temp_name = tempfile.mkstemp(prefix=".aurix-report-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        # Refuse a symlink swap immediately before replacement.
        if target.is_symlink():
            raise PermissionError("Symlink report destinations are not allowed")
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return {"status": "updated", "path": target.relative_to(root).as_posix(),
            "run_id": report["run_id"], "audit_count": len(audits),
            "previous_digest": previous_digest, "current_digest": report["integrity"]["digest"]}
