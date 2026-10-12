"""Combine proposal triage and explicitly approved verification into one audit result."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aurix.tools.patches import _proposal_path, _validate_patch, _target_state_snapshot, _target_state_digest
from aurix.tools.review import review_proposal, review_correctness_proposal
from aurix.tools.verification import verify_proposal
from aurix.tools.execution import IsolationMode
from aurix.tools.provenance import append_audit_event


def audit_proposal(
    workspace: str | Path,
    proposal_id: str,
    *,
    confirm_verify: bool = False,
    suite: str = "pytest",
    timeout_seconds: int = 120,
    isolation: IsolationMode = "trusted",
    sandbox_image: str | None = None,
) -> dict[str, Any]:
    """Review a proposal and optionally verify it in a disposable Git worktree.

    The heuristic review never authorizes applying the patch. Verification is
    opt-in because repository tests are executable code and are not OS-sandboxed.
    """
    root = Path(workspace).expanduser().resolve(strict=True)
    proposal_path = _proposal_path(root, proposal_id)
    patch_bytes = proposal_path.read_bytes()
    patch_digest = hashlib.sha256(patch_bytes).hexdigest()
    targets = _validate_patch(root, patch_bytes.decode("utf-8"))
    target_state = _target_state_snapshot(root, targets)
    target_state_sha256 = _target_state_digest(target_state)
    if target_state_sha256 is None:
        raise RuntimeError("Could not create target-state evidence")
    audit_id = uuid.uuid4().hex
    review = review_proposal(root, proposal_id)
    correctness_review = review_correctness_proposal(root, proposal_id)
    result: dict[str, Any] = {
        "schema_version": 9,
        "audit_id": audit_id,
        "target_state": target_state,
        "target_state_sha256": target_state_sha256,
        "proposal_id": proposal_id,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "proposal_sha256": patch_digest,
        "base_commit": __import__("subprocess").run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, timeout=10, check=False,
        ).stdout.strip(),
        "status": "reviewed_verification_not_run",
        "review": review,
        "review_tracks": {"security": review, "correctness": correctness_review},
        "verification": {
            "status": "not_run",
            "reason": "Explicit confirmation required" if not confirm_verify else "pending",
        },
        "application": {"performed": False, "permitted_by_review": False},
        "limitations": [
            "Heuristic review is not proof of security or correctness.",
            ("Docker isolation is used only when explicitly selected; review the image and daemon boundary."
             if isolation == "docker" else "Verification executes repository code and is not an OS sandbox."),
            "Passing tests do not authorize patch application.",
        ],
    }
    if confirm_verify:
        verification = verify_proposal(
            workspace, proposal_id, confirm=True, suite=suite, timeout_seconds=timeout_seconds,
            isolation=isolation, sandbox_image=sandbox_image, audit_id=audit_id,
            target_state_sha256=target_state_sha256,
        )
        result["verification"] = verification
        result["status"] = (
            "audit_passed" if review["risk_level"] == "low"
            and correctness_review["risk_level"] == "low"
            and verification["status"] == "verified_pass"
            and verification.get("proposal_sha256") == patch_digest
            and verification.get("base_commit") == result["base_commit"]
            and verification.get("target_state_sha256") == target_state_sha256
            and verification.get("regression_status") != "introduced_failure"
            else "audit_needs_attention"
        )
    # Bind the review and test result to the exact same bytes. A changed patch
    # invalidates the audit instead of leaving a stale green result behind.
    current_digest = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
    if current_digest != patch_digest:
        raise PermissionError("Proposal changed during audit; refusing to record stale evidence")
    if _target_state_snapshot(root, targets) != target_state:
        raise PermissionError("Patch target files changed during audit; refusing to record stale evidence")
    audit_dir = root / ".aurix" / "audits"
    if audit_dir.is_symlink():
        raise PermissionError("AURIX audit directory must not be a symlink")
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"{proposal_id}.json"
    if audit_path.is_symlink():
        raise PermissionError("Audit evidence path must not be a symlink")
    payload = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temp_path = audit_path.with_name(audit_path.name + ".tmp")
    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        pass
    os.replace(temp_path, audit_path)
    append_audit_event(root, "proposal_audited", proposal_id, {
        "sha256": patch_digest, "status": result["status"],
        "security_risk": review["risk_level"],
        "correctness_risk": correctness_review["risk_level"],
        "verification": result["verification"]["status"],
    })
    return result
