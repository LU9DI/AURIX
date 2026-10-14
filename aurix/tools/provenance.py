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
import stat
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _fsync_directory(path: Path) -> None:
    """Best-effort persistence of directory-entry changes on supported filesystems."""
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path, flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        # Some platforms/filesystems do not support opening or syncing directories.
        pass


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


def _read_proposal_snapshot(path: Path) -> bytes:
    """Read a bounded proposal snapshot without following a final symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if getattr(exc, "errno", None) in {40, 62}:
            raise PermissionError("Proposal must not be a symlink") from exc
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise PermissionError("Proposal must be a regular file")
        if info.st_size > 100_000:
            raise ValueError("Proposal exceeds size limit")
        chunks: list[bytes] = []
        remaining = 100_001
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > 100_000:
            raise ValueError("Proposal exceeds size limit")
        return payload
    finally:
        os.close(fd)


def register_proposal(workspace: Path, proposal_path: Path, proposal_id: str) -> dict[str, Any]:
    patch_bytes = _read_proposal_snapshot(proposal_path)
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
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    _atomic_create(path, manifest_bytes)
    try:
        append_audit_event(workspace, "proposal_created", proposal_id, {"sha256": manifest["sha256"]})
    except Exception as exc:
        # Compensate only when the path still names the exact manifest we created.
        # Never delete a replacement or a file whose content changed concurrently.
        try:
            current = path.lstat()
            if stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(current.st_mode):
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(path, flags)
                try:
                    opened = os.fstat(fd)
                    chunks = []
                    remaining = len(manifest_bytes) + 1
                    while remaining:
                        chunk = os.read(fd, min(65536, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    unchanged = (
                        (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)
                        and b"".join(chunks) == manifest_bytes
                    )
                finally:
                    os.close(fd)
                latest = path.lstat()
                if unchanged and (latest.st_dev, latest.st_ino) == (current.st_dev, current.st_ino):
                    path.unlink()
        except OSError:
            # Keep evidence if compensation cannot be proven safe.
            pass
        raise RuntimeError(
            "Proposal manifest was written but its creation audit event failed; "
            "the manifest was removed only if it remained unchanged. Inspect workspace before retrying."
        ) from exc
    return manifest


def verify_proposal_integrity(
    proposal_path: Path, proposal_id: str, *, proposal_bytes: bytes | None = None
) -> dict[str, Any]:
    """Verify a manifest against one byte snapshot when supplied.

    Passing ``proposal_bytes`` lets callers verify the exact bytes they subsequently
    decode or inspect, avoiding a hash/read time-of-check-to-time-of-use gap.
    """
    path = _metadata_path(proposal_path)
    snapshot = _read_proposal_snapshot(proposal_path) if proposal_bytes is None else proposal_bytes
    # lstat distinguishes a genuinely absent manifest from a dangling symlink.
    try:
        entry_stat = path.lstat()
    except FileNotFoundError:
        return {
            "integrity": "legacy_unsealed",
            "sha256": hashlib.sha256(snapshot).hexdigest(),
        }
    except OSError as exc:
        raise ValueError("Proposal manifest is unreadable") from exc

    if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISREG(entry_stat.st_mode) or entry_stat.st_size > 16_384:
        raise PermissionError("Unsafe proposal manifest")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            manifest_stat = os.fstat(stream.fileno())
            if not stat.S_ISREG(manifest_stat.st_mode) or manifest_stat.st_size > 16_384:
                raise PermissionError("Unsafe proposal manifest")
            manifest_bytes = stream.read(16_385)
            if len(manifest_bytes) > 16_384:
                raise PermissionError("Unsafe proposal manifest")
        manifest = json.loads(
            manifest_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except PermissionError:
        raise
    except OSError as exc:
        if getattr(exc, "errno", None) in {40, 62}:  # ELOOP on common POSIX platforms
            raise PermissionError("Unsafe proposal manifest") from exc
        raise ValueError("Proposal manifest is unreadable") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Proposal manifest is unreadable") from exc
    actual = hashlib.sha256(snapshot).hexdigest()
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
        or manifest_size != len(snapshot)
    ):
        raise PermissionError(
            "Proposal content changed after it was registered; refusing operation"
        )
    return {"integrity": "verified", "sha256": actual, "created_at": manifest.get("created_at")}


@contextmanager
def _audit_append_lock(metadata: Path):
    """Serialize audit-chain read/append operations across AURIX processes.

    A lock left by a crash is intentionally not removed automatically. The caller
    must inspect the workspace before clearing it.
    """
    if metadata.is_symlink():
        raise PermissionError("AURIX metadata directory must not be a symlink")
    metadata.mkdir(parents=True, exist_ok=True)
    lock_path = metadata / "audit.lock"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise PermissionError(
            "Audit append is already running, or a previous append left a stale lock; "
            "inspect the audit log before removing it"
        ) from exc
    lock_stat = os.fstat(fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"pid": os.getpid(), "created_at": time.time()}))
            stream.flush()
            os.fsync(stream.fileno())
        # Make the lock directory entry durable before appending to the audit chain.
        _fsync_directory(metadata)
        yield
    finally:
        try:
            current = lock_path.lstat()
            if (current.st_dev, current.st_ino) == (lock_stat.st_dev, lock_stat.st_ino):
                lock_path.unlink()
                _fsync_directory(metadata)
        except FileNotFoundError:
            pass


def append_audit_event(
    workspace: Path, event: str, proposal_id: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    metadata = root / ".aurix"
    with _audit_append_lock(metadata):
        return _append_audit_event_locked(root, event, proposal_id, details)


def _append_audit_event_locked(
    root: Path, event: str, proposal_id: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    metadata = root / ".aurix"
    if metadata.is_symlink():
        raise PermissionError("AURIX metadata directory must not be a symlink")
    metadata.mkdir(parents=True, exist_ok=True)
    log = metadata / "audit.jsonl"
    previous = "0" * 64
    log_identity: tuple[int, int, int] | None = None
    read_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        read_fd = os.open(log, read_flags)
    except FileNotFoundError:
        raw_lines: list[bytes] = []
    except OSError as exc:
        if getattr(exc, "errno", None) in {40, 62}:
            raise PermissionError("Audit log must not be a symlink") from exc
        raise ValueError("Audit log is unreadable") from exc
    else:
        info = os.fstat(read_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 10_000_000:
            os.close(read_fd)
            raise ValueError("Audit log is not a bounded regular file")
        with os.fdopen(read_fd, "rb") as stream:
            log_identity = (info.st_dev, info.st_ino, info.st_size)
            raw_data = stream.read(10_000_001)
            if len(raw_data) > 10_000_000:
                raise ValueError("Audit log is not a bounded regular file")
        # A JSONL record must end with a newline. Otherwise the next O_APPEND
        # write would concatenate two JSON objects and corrupt the chain.
        if raw_data and not raw_data.endswith(b"\n"):
            raise ValueError("Audit log ends with an incomplete line; manual repair is required")
        raw_lines = raw_data.splitlines()
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
    append_flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(log, append_flags, 0o600)
    except OSError as exc:
        if getattr(exc, "errno", None) in {40, 62}:
            raise PermissionError("Audit log must not be a symlink") from exc
        raise
    try:
        append_stat = os.fstat(fd)
        if not stat.S_ISREG(append_stat.st_mode):
            raise PermissionError("Audit log must be a regular file")
        if log_identity is not None and (
            append_stat.st_dev, append_stat.st_ino, append_stat.st_size
        ) != log_identity:
            raise PermissionError("Audit log changed during append; refusing operation")
        if log_identity is None and append_stat.st_size != 0:
            raise PermissionError("Audit log appeared during append; refusing operation")
        with os.fdopen(fd, "ab") as stream:
            stream.write(
                (json.dumps(stored, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        fd = -1
        if log_identity is None:
            # fsync(file) persists the event bytes; fsync(parent) also persists
            # creation of audit.jsonl when this was the first event.
            _fsync_directory(metadata)
    finally:
        if fd >= 0:
            os.close(fd)
    return stored



def _atomic_create(path: Path, content: bytes) -> None:
    """Durably create a file without replacing a concurrent creator's file.

    The temporary file lives beside the destination; linking it into place is
    atomic and fails with FileExistsError if another registration won the race.
    """
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path, follow_symlinks=False)
        try:
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(path.parent, directory_flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _atomic_write(path: Path, content: bytes) -> None:
    """Atomically replace a file using a unique same-directory temporary file."""
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        # Directory fsync improves rename durability on POSIX. Some filesystems
        # do not support it, so a failure here must not misreport the already
        # completed replacement as though it had not happened.
        try:
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(path.parent, directory_flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
