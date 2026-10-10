"""Deterministic heuristic review for proposed unified diffs.

This is a triage aid, not a proof of correctness or security.
"""
from __future__ import annotations

import re
import hashlib
from pathlib import Path
from typing import Any

from aurix.tools.patches import _proposal_path, _validate_patch
from aurix.tools.provenance import append_audit_event, verify_proposal_integrity

_RULES: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    ("dynamic-code", "high", "Added code may evaluate or execute dynamically",
     re.compile(r"\b(eval|exec)\s*\(")),
    ("shell-execution", "high", "Added code may invoke a shell or subprocess",
     re.compile(r"\b(subprocess\.(run|Popen|call|check_call|check_output)|os\.system|shell\s*=\s*True)\b")),
    ("deserialization", "high", "Added code may use unsafe deserialization",
     re.compile(r"\bpickle\.(loads|load)\s*\(|\byaml\.load\s*\(")),
    ("tls-validation", "medium", "Added code may disable TLS certificate verification",
     re.compile(r"\bverify\s*=\s*False\b|CERT_NONE")),
    ("secret-literal", "high", "Added code may contain a hard-coded credential",
     re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]")),
    ("broad-permissions", "medium", "Added code may set broad filesystem permissions",
     re.compile(r"chmod\s*\(.*0?777|\b0o777\b")),
    ("sql-concatenation", "medium", "Added code may build SQL using string concatenation/interpolation",
     re.compile(r"(?i)(select|insert|update|delete)\s+.{0,80}(\+\s*\w+|%s|\{\w+\})")),
)


def _added_line_records(patch: str, patch_sha256: str) -> list[dict[str, Any]]:
    """Parse added lines and bind each record to its patch and unified-diff location."""
    records: list[dict[str, Any]] = []
    current_file = ""
    hunk_header = ""
    new_line_number: int | None = None
    for patch_line, line in enumerate(patch.splitlines(), start=1):
        if line.startswith("+++ "):
            current_file = line[4:].split("\t", 1)[0].removeprefix("b/")
            new_line_number = None
            continue
        if line.startswith("@@"):
            match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if not match:
                hunk_header = line[:240]
                new_line_number = None
            else:
                hunk_header = line[:240]
                new_line_number = int(match.group(1))
            continue
        if line.startswith("\\ No newline"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added = line[1:]
            records.append({
                "file": current_file,
                "patch_line": patch_line,
                "source_line": new_line_number,
                "hunk": hunk_header,
                "line_sha256": hashlib.sha256(added.encode("utf-8")).hexdigest(),
                "patch_sha256": patch_sha256,
                "text": added,
            })
            if new_line_number is not None:
                new_line_number += 1
        elif line.startswith(" "):
            if new_line_number is not None:
                new_line_number += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
    return records

def _finding_evidence(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in (
        "file", "patch_line", "source_line", "hunk", "line_sha256", "patch_sha256"
    )}


def review_proposal(workspace: Path | str, proposal_id: str) -> dict[str, Any]:
    """Return a bounded static review of newly added diff lines."""
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be a directory")
    proposal = _proposal_path(root, proposal_id)
    integrity = verify_proposal_integrity(proposal, proposal_id)
    patch = proposal.read_text(encoding="utf-8")
    targets = _validate_patch(root, patch)
    findings: list[dict[str, Any]] = []
    records = _added_line_records(patch, integrity["sha256"])
    for record in records:
        added = record["text"]
        for rule_id, severity, summary, pattern in _RULES:
            if pattern.search(added):
                findings.append({
                    "rule": rule_id,
                    "severity": severity,
                    "file": record["file"],
                    "patch_line": record["patch_line"],
                    "summary": summary,
                    "sample": added.strip()[:240],
                    "evidence": _finding_evidence(record),
                })
    risk = "high" if any(x["severity"] == "high" for x in findings) else (
        "medium" if findings else "low")
    append_audit_event(root, "proposal_reviewed", proposal_id, {"risk_level": risk, "finding_count": len(findings), "sha256": integrity["sha256"]})
    return {
        "proposal_id": proposal_id,
        "proposal_sha256": integrity["sha256"],
        "evidence_schema": 1,
        "integrity": integrity,
        "status": "review_required",
        "risk_level": risk,
        "targets": targets,
        "added_lines_scanned": len(records),
        "finding_count": len(findings),
        "findings": findings[:100],
        "limitations": [
            "Heuristic scan covers added diff lines only and can miss vulnerabilities.",
            "A low risk level does not mean the patch is safe or correct.",
            "Human review and appropriate tests remain required.",
        ],
        "apply_permitted_by_review": False,
    }


_CORRECTNESS_RULES: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    ("swallowed-exception", "medium", "Added code may silently swallow an exception",
     re.compile(r"except(?:\s+[A-Za-z_][\w.]*)?\s*:\s*(?:#.*)?$")),
    ("assert-false", "medium", "Added code contains an unconditional failing assertion",
     re.compile(r"\bassert\s+(?:False|0|None)\b")),
    ("empty-exception-handler", "medium", "Added exception handler may have no meaningful handling",
     re.compile(r"^\s*pass\s*(?:#.*)?$")),
)


def review_correctness_proposal(workspace: Path | str, proposal_id: str) -> dict[str, Any]:
    """Run a separate deterministic correctness/robustness triage over added lines.

    This is intentionally independent from the security rule set, but is still a
    heuristic: it cannot establish semantic correctness or replace real tests.
    """
    root = Path(workspace).expanduser().resolve(strict=True)
    proposal = _proposal_path(root, proposal_id)
    digest = __import__("hashlib").sha256(proposal.read_bytes()).hexdigest()
    patch = proposal.read_text(encoding="utf-8")
    _validate_patch(root, patch)
    findings: list[dict[str, Any]] = []
    records = _added_line_records(patch, digest)
    for record in records:
        added = record["text"]
        for rule_id, severity, summary, pattern in _CORRECTNESS_RULES:
            if pattern.search(added):
                findings.append({
                    "rule": rule_id, "severity": severity, "file": record["file"],
                    "patch_line": record["patch_line"], "summary": summary,
                    "sample": added.strip()[:240],
                    "evidence": _finding_evidence(record),
                })
    risk = "medium" if findings else "low"
    append_audit_event(root, "proposal_correctness_reviewed", proposal_id,
                       {"risk_level": risk, "finding_count": len(findings), "sha256": digest})
    return {"proposal_id": proposal_id, "proposal_sha256": digest, "evidence_schema": 1,
            "status": "review_required", "risk_level": risk,
            "finding_count": len(findings), "findings": findings[:100],
            "limitations": ["Static heuristics cannot prove functional correctness.",
                            "Passing this review track does not replace tests or human review."],
            "apply_permitted_by_review": False}
