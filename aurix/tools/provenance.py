"""Proposal integrity metadata and tamper-evident local audit events.

The hash chain detects accidental/tamper edits to recorded events; it is not
an authenticated or remote append-only log, so a local administrator can still
rewrite the entire chain.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _metadata_path(proposal_path: Path) -> Path:
    return proposal_path.with_suffix(".json")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous metadata rather than silently accepting the last key."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise json.JSONDecodeError(f"duplicate JSON key: {key}", "", 0)
        result[key] = value
    return result


def register_proposal(workspace: Path, proposal_path: Path, proposal_id: str) -> dict[str, Any]:
    patch_bytes = proposal_path.read_bytes()
    manifest = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "sha256": hashlib.sha256(patch_bytes).hexdigest(),
        "size_bytes": len(patch_bytes),
        "created_at": datetime.now(UTC).isoformat(),
    }
    path = _metadata_path(proposal_path)
    if path.exists() or path.is_symlink():
        raise FileExistsError("Proposal manifest already exists")
    _atomic_write(path, (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
    append_audit_event(workspace, "proposal_created", proposal_id, {"sha256": manifest["sha256"]})
    return manifest


def verify_proposal_integrity(proposal_path: Path, proposal_id: str) -> dict[str, Any]:
    """Verify a manifest if present; legacy proposals are explicitly marked unsealed."""
    path = _metadata_path(proposal_path)
    if not path.exists():
        return {
            "integrity": "legacy_unsealed",
            "sha256": hashlib.sha256(proposal_path.read_bytes()).hexdigest(),
        }
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_384:
        raise PermissionError("Unsafe proposal manifest")
    try:
        manifest = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Proposal manifest is unreadable") from exc
    actual = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != 1
        or manifest.get("proposal_id") != proposal_id
    ):
        raise ValueError("Proposal manifest identity mismatch")
    manifest_size = manifest.get("size_bytes")
    manifest_digest = manifest.get("sha256")
    if (
        type(manifest_size) is not int
        or manifest_size < 0
        or not isinstance(manifest_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest_digest)
        or manifest_digest != actual
        or manifest_size != proposal_path.stat().st_size
    ):
        raise PermissionError(
            "Proposal content changed after it was registered; refusing operation"
        )
    return {"integrity": "verified", "sha256": actual, "created_at": manifest.get("created_at")}


def append_audit_event(
    workspace: Path, event: str, proposal_id: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    metadata = root / ".aurix"
    if metadata.is_symlink():
        raise PermissionError("AURIX metadata directory must not be a symlink")
    metadata.mkdir(parents=True, exist_ok=True)
    log = metadata / "audit.jsonl"
    if log.is_symlink():
        raise PermissionError("Audit log must not be a symlink")
    previous = "0" * 64
    if log.exists():
        if not log.is_file() or log.stat().st_size > 10_000_000:
            raise ValueError("Audit log is not a bounded regular file")
        raw_lines = log.read_bytes().splitlines()
        if raw_lines and len(raw_lines) > 100_000:
            raise ValueError("Audit log contains too many events")
        for raw in raw_lines:
            try:
                item = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
                if not isinstance(item, dict):
                    raise TypeError("audit event must be a JSON object")
                digest = item.pop("event_hash")
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError("Audit log integrity check failed") from exc
            canonical = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            expected = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
            if digest != expected or item.get("previous_hash") != previous:
                raise ValueError("Audit log hash chain is invalid")
            previous = digest
    event_data: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        "proposal_id": proposal_id,
        "details": details or {},
        "previous_hash": previous,
    }
    canonical = json.dumps(event_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    event_hash = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
    stored = {**event_data, "event_hash": event_hash}
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "ab") as stream:
            stream.write(
                (json.dumps(stored, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
            )
            stream.flush()
        fd = -1
    finally:
        if fd >= 0:
            os.close(fd)
    return stored


def _atomic_write(path: Path, content: bytes) -> None:
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            temp.unlink()
        except OSError:
            pass
        raise
    os.replace(temp, path)
