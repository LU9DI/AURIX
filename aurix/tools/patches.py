"""Explicitly confirmed application and reversal of AURIX patch proposals.

This is a guardrail, not a sandbox. Only tracked, existing regular files may be
modified; the Git worktree must be clean before application.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import stat
import time
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

from aurix.tools.provenance import append_audit_event, verify_proposal_integrity
from aurix.tools.workspace import SENSITIVE_NAMES, safe_path

_PROPOSAL_ID = re.compile(r"^[0-9a-f]{12}$")
_MAX_PATCH_BYTES = 100_000


def _git(
    workspace: Path, args: Sequence[str], *, patch: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        input=patch,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


def _proposal_path(workspace: Path, proposal_id: str) -> Path:
    if not _PROPOSAL_ID.fullmatch(proposal_id):
        raise ValueError("Invalid proposal ID")
    root = workspace.expanduser().resolve()
    metadata = root / ".aurix"
    proposal_dir = metadata / "proposals"
    if metadata.is_symlink() or proposal_dir.is_symlink():
        raise PermissionError("AURIX proposal directories must not be symlinks")
    path = proposal_dir / f"{proposal_id}.diff"
    # Do not follow symlinks, even if they point back inside the repository.
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"Patch proposal not found: {proposal_id}")
    if path.stat().st_size > _MAX_PATCH_BYTES:
        raise ValueError("Patch proposal exceeds size limit")
    verify_proposal_integrity(path, proposal_id)
    return path


def _validate_patch(workspace: Path, patch: str) -> list[str]:
    if not patch.strip() or "\x00" in patch:
        raise ValueError("Patch is empty or contains a NUL byte")
    if len(patch.encode("utf-8")) > _MAX_PATCH_BYTES:
        raise ValueError("Patch proposal exceeds size limit")
    forbidden_headers = (
        "GIT binary patch",
        "diff --git ",
        "index ",
        "new file mode ",
        "deleted file mode ",
        "old mode ",
        "new mode ",
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
        "similarity index ",
    )
    if any(line.startswith(forbidden_headers) for line in patch.splitlines()):
        raise PermissionError(
            "Only plain unified diffs are supported; metadata and binary patches are refused"
        )

    lines = patch.splitlines()
    file_pairs: list[tuple[str, str]] = []
    old_path: str | None = None
    for line in lines:
        if line.startswith("--- "):
            old_path = line[4:].split("\t", 1)[0].split(" ", 1)[0]
        elif line.startswith("+++ "):
            new_path = line[4:].split("\t", 1)[0].split(" ", 1)[0]
            if old_path is None:
                raise ValueError("Malformed unified diff: missing old file header")
            file_pairs.append((old_path, new_path))
            old_path = None
    if not file_pairs or not any(line.startswith("@@") for line in lines):
        raise ValueError("Patch must contain file headers and at least one hunk")

    root = workspace.resolve()
    targets: list[str] = []
    for old, new in file_pairs:
        old_rel = old.removeprefix("a/")
        new_rel = new.removeprefix("b/")
        if old == "/dev/null" or new == "/dev/null" or old_rel != new_rel:
            raise PermissionError("Only in-place modifications of existing files are allowed")
        for header_path in (old_rel, new_rel):
            if "\\" in header_path:
                raise PermissionError("Backslashes are not allowed in patch paths")
            if header_path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", header_path):
                raise PermissionError("Absolute paths are not allowed")
            parts = Path(header_path).parts
            if not header_path or any(part == ".." or part.casefold() in {".git", ".aurix"} for part in parts):
                raise PermissionError("Unsafe path in patch")
            if Path(header_path).name.lower() in SENSITIVE_NAMES or Path(
                header_path
            ).name.lower().startswith(".env."):
                raise PermissionError("Patch may not modify sensitive files")
        target = safe_path(root, new_rel)
        if not target.is_file() or target.is_symlink():
            raise PermissionError("Patch targets must be existing regular files")
        relative = target.relative_to(root).as_posix()
        tracked = _git(root, ["ls-files", "--error-unmatch", "--", relative])
        if tracked.returncode != 0:
            raise PermissionError(f"Patch target is not tracked by Git: {relative}")
        targets.append(relative)
    return targets


@contextmanager
def _workspace_operation_lock(workspace: Path):
    """Serialize AURIX patch operations in one workspace.

    A lock left behind by a crash is intentionally not removed automatically: a
    human must inspect the recorded PID/time and repository state before clearing it.
    This lock coordinates AURIX processes only; it cannot lock out arbitrary editors.
    """
    root = workspace.expanduser().resolve()
    metadata = root / ".aurix"
    if metadata.is_symlink():
        raise PermissionError("AURIX metadata directory must not be a symlink")
    metadata.mkdir(parents=True, exist_ok=True)
    lock_path = metadata / "operation.lock"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise PermissionError(
            "Another AURIX patch operation holds the workspace lock, or a previous "
            "operation left a stale lock; inspect repository state before removing it"
        ) from exc
    try:
        stat = os.fstat(fd)
    except BaseException:
        # The descriptor is ours, but without a successful fstat we cannot prove
        # that the path still names this inode. Close the descriptor and leave the
        # lock in place for manual inspection rather than unlinking an unverified path.
        os.close(fd)
        raise
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"pid": os.getpid(), "created_at": time.time()}))
            stream.flush()
            os.fsync(stream.fileno())
        # Persist the directory entry where supported, not only the lock contents.
        try:
            directory_fd = os.open(metadata, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
        yield
    finally:
        try:
            current = lock_path.lstat()
            if (current.st_dev, current.st_ino) == (stat.st_dev, stat.st_ino):
                lock_path.unlink()
                try:
                    directory_fd = os.open(metadata, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except OSError:
                    pass
        except FileNotFoundError:
            pass


def inspect_operation_lock(workspace: Path | str) -> dict[str, object]:
    """Read-only inspection of the AURIX operation lock; never removes it."""
    root = Path(workspace).expanduser().resolve()
    metadata = root / ".aurix"
    if metadata.is_symlink():
        raise PermissionError("AURIX metadata directory must not be a symlink")
    lock_path = metadata / "operation.lock"
    try:
        info = lock_path.lstat()
    except FileNotFoundError:
        return {"status": "absent", "lock_exists": False, "read_only": True}
    if lock_path.is_symlink() or not lock_path.is_file():
        return {
            "status": "invalid",
            "lock_exists": True,
            "reason": "lock is not a regular file",
            "read_only": True,
        }
    try:
        if info.st_size > 4096:
            raise ValueError("lock record exceeds size limit")
        record = _load_strict_json(
            _read_regular_file(
                lock_path, max_bytes=4096, label="Operation lock"
            ).decode("utf-8")
        )
        if (
            not isinstance(record, dict)
            or type(record.get("pid")) is not int
            or record["pid"] <= 0
        ):
            raise ValueError("lock record has no valid positive PID")
        created_at = record.get("created_at")
        if (
            not isinstance(created_at, (int, float))
            or isinstance(created_at, bool)
            or created_at < 0
        ):
            raise ValueError("lock record has no valid creation timestamp")
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "lock_exists": True, "reason": str(exc), "read_only": True}
    pid = record["pid"]
    try:
        os.kill(pid, 0)
        owner_status = "possibly_alive"
    except ProcessLookupError:
        owner_status = "not_found"
    except PermissionError:
        owner_status = "inaccessible"
    except OSError:
        owner_status = "unknown"
    return {
        "status": "present",
        "lock_exists": True,
        "pid": pid,
        "created_at": created_at,
        "owner_status": owner_status,
        "stale_not_proven": True,
        "read_only": True,
    }


def _recovery_history_digest(entry: dict[str, object], previous_hash: str) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((previous_hash + canonical).encode("utf-8")).hexdigest()


def _validate_recovery_history(history: object) -> list[dict[str, object]]:
    """Validate the transaction-local recovery chain; legacy empty history is valid."""
    if not isinstance(history, list):
        raise PermissionError("Recovery history is malformed; manual intervention is required")
    previous = "0" * 64
    validated: list[dict[str, object]] = []
    for entry in history:
        if not isinstance(entry, dict):
            raise PermissionError(
                "Recovery history entry is malformed; manual intervention is required"
            )
        body = {
            key: value for key, value in entry.items() if key not in {"previous_hash", "entry_hash"}
        }
        if entry.get("previous_hash") != previous or entry.get(
            "entry_hash"
        ) != _recovery_history_digest(body, previous):
            raise PermissionError(
                "Recovery history integrity check failed; manual intervention is required"
            )
        previous = str(entry["entry_hash"])
        validated.append(dict(entry))
    return validated


def _external_anchor_path(workspace: Path | str, anchor_path: Path | str) -> tuple[Path, Path]:
    """Resolve an operator-managed anchor that must live outside the workspace."""
    root = Path(workspace).expanduser().resolve()
    supplied = Path(anchor_path).expanduser()
    if supplied.is_symlink():
        raise PermissionError("Recovery anchor must not be a symlink")
    anchor = supplied.resolve()
    try:
        anchor.relative_to(root)
    except ValueError:
        pass
    else:
        raise PermissionError("Recovery anchor must be stored outside the workspace")
    if anchor == root or not anchor.name:
        raise ValueError("Invalid recovery anchor path")
    # Refuse symlinked parent components, which can redirect an ostensibly external anchor.
    cursor = supplied.absolute().parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise PermissionError("Recovery anchor parent directories must not be symlinks")
        cursor = cursor.parent
    return root, anchor


def _read_regular_file(path: Path, *, max_bytes: int, label: str) -> bytes:
    """Read one bounded regular-file snapshot without following a final symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {40, 62}:  # ELOOP on common POSIX platforms
            raise PermissionError(f"{label} must not be a symlink") from exc
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise PermissionError(f"{label} is not a regular file")
        if info.st_size > max_bytes:
            raise ValueError(f"{label} exceeds size limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(fd)
        identity_before = (
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
        )
        identity_after = (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        )
        if identity_before != identity_after or len(payload) != after.st_size:
            raise PermissionError(f"{label} changed while being read")
        if len(payload) > max_bytes:
            raise ValueError(f"{label} exceeds size limit")
        return payload
    finally:
        os.close(fd)


def _journal_snapshot(root: Path) -> dict[str, str]:
    transactions = root / ".aurix" / "transactions"
    if (root / ".aurix").is_symlink() or transactions.is_symlink():
        raise PermissionError("AURIX transaction directories must not be symlinks")
    snapshot: dict[str, str] = {}
    if not transactions.exists():
        return snapshot
    if not transactions.is_dir():
        raise PermissionError("AURIX transaction path is not a directory")
    for path in sorted(transactions.iterdir()):
        if path.suffix != ".json":
            continue
        if path.is_symlink() or not path.is_file():
            raise PermissionError(f"Transaction journal is not a regular file: {path.name}")
        snapshot[path.name] = hashlib.sha256(
            _read_regular_file(path, max_bytes=1_000_000, label="Transaction journal")
        ).hexdigest()
    return snapshot


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous JSON objects instead of silently accepting the last value."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise json.JSONDecodeError(f"duplicate JSON key: {key}", "", 0)
        result[key] = value
    return result


def _load_strict_json(payload: str) -> object:
    """Load JSON while rejecting duplicate keys at every nesting level."""
    return json.loads(payload, object_pairs_hook=_reject_duplicate_json_keys)


def create_recovery_anchor(workspace: Path | str, anchor_path: Path | str) -> dict[str, object]:
    """Create an explicit external snapshot of transaction journals after validation."""
    root, anchor = _external_anchor_path(workspace, anchor_path)
    # Bind validation to the exact journal inventory being anchored. A mutation
    # between validation and hashing must not become a trusted external baseline.
    before = _journal_snapshot(root)
    report = verify_recovery_histories(root)
    if report["invalid"]:
        raise PermissionError("Cannot anchor invalid recovery journals; resolve them first")
    snapshot = _journal_snapshot(root)
    if before != snapshot:
        raise PermissionError(
            "Transaction journals changed during recovery-anchor creation; retry after inspection"
        )
    payload_obj = {
        "schema_version": 1,
        "algorithm": "sha256",
        "workspace": str(root),
        "journals": snapshot,
    }
    payload = (
        json.dumps(payload_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    anchor.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(anchor, flags, 0o600)
    except FileExistsError as exc:
        raise FileExistsError("Recovery anchor already exists; refusing to overwrite it") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            directory_fd = os.open(anchor.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except BaseException:
        try:
            anchor.unlink()
        except OSError:
            pass
        raise
    return {
        "status": "anchored",
        "anchor": str(anchor),
        "journals": len(snapshot),
        "read_only_workspace": True,
    }


def verify_recovery_histories(
    workspace: Path | str, anchor_path: Path | str | None = None
) -> dict[str, object]:
    """Verify recovery chains and optionally compare journals against an external snapshot."""
    root = Path(workspace).expanduser().resolve()
    metadata = root / ".aurix"
    transactions = metadata / "transactions"
    if metadata.is_symlink() or transactions.is_symlink():
        raise PermissionError("AURIX transaction directories must not be symlinks")
    results: list[dict[str, object]] = []
    if transactions.exists() and not transactions.is_dir():
        raise PermissionError("AURIX transaction path is not a directory")
    if transactions.exists():
        for path in sorted(transactions.iterdir()):
            if path.suffix != ".json":
                continue
            item: dict[str, object] = {
                "proposal_id": path.stem,
                "journal": path.relative_to(root).as_posix(),
            }
            try:
                if path.is_symlink() or not path.is_file():
                    raise PermissionError("journal is not a regular file")
                record = _load_strict_json(
                    _read_regular_file(path, max_bytes=1_000_000, label="Transaction journal").decode("utf-8")
                )
                if not isinstance(record, dict) or record.get("proposal_id") != path.stem:
                    raise ValueError("journal identity mismatch")
                history = record.get("recovery_history", [])
                validated = _validate_recovery_history(history)
                item.update(
                    status="valid",
                    entries=len(validated),
                    terminal_hash=(validated[-1]["entry_hash"] if validated else None),
                )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                ValueError,
                PermissionError,
                TypeError,
            ) as exc:
                item.update(status="invalid", reason=str(exc)[:240])
            results.append(item)
    invalid = sum(item["status"] != "valid" for item in results)
    result: dict[str, object] = {
        "status": "invalid" if invalid else "valid",
        "count": len(results),
        "valid": len(results) - invalid,
        "invalid": invalid,
        "read_only": True,
        "results": results,
    }
    if anchor_path is not None:
        _, anchor = _external_anchor_path(root, anchor_path)
        try:
            if anchor.is_symlink() or not anchor.is_file():
                raise PermissionError("Recovery anchor is missing or is not a regular file")
            if anchor.stat().st_size > 5_000_000:
                raise ValueError("Recovery anchor exceeds size limit")
            anchor_data = _load_strict_json(_read_regular_file(anchor, max_bytes=5_000_000, label="Recovery anchor").decode("utf-8"))
            if (
                not isinstance(anchor_data, dict)
                or type(anchor_data.get("schema_version")) is not int
                or anchor_data.get("schema_version") != 1
                or anchor_data.get("algorithm") != "sha256"
                or anchor_data.get("workspace") != str(root)
                or not isinstance(anchor_data.get("journals"), dict)
            ):
                raise ValueError("Recovery anchor schema or workspace identity mismatch")
            expected = anchor_data["journals"]
            actual = _journal_snapshot(root)
            if any(
                not isinstance(k, str)
                or not re.fullmatch(r"[0-9a-f]{12}\.json", k)
                or not isinstance(v, str)
                or not re.fullmatch(r"[0-9a-f]{64}", v)
                for k, v in expected.items()
            ):
                raise ValueError("Recovery anchor contains malformed journal names or digests")
            missing = sorted(set(expected) - set(actual))
            added = sorted(set(actual) - set(expected))
            changed = sorted(
                name for name in set(expected) & set(actual) if expected[name] != actual[name]
            )
            result["anchor"] = {
                "path": str(anchor),
                "status": "valid" if not (missing or added or changed) else "mismatch",
                "expected": len(expected),
                "actual": len(actual),
                "missing": missing,
                "added": added,
                "changed": changed,
            }
            if missing or added or changed:
                result["status"] = "invalid"
                result["invalid"] = (
                    int(result["invalid"]) + len(missing) + len(added) + len(changed)
                )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
            PermissionError,
            TypeError,
        ) as exc:
            result["anchor"] = {"status": "invalid", "reason": str(exc)[:240]}
            result["status"] = "invalid"
            result["invalid"] = int(result["invalid"]) + 1
    return result


def _append_recovery_history(history: object, event: dict[str, object]) -> list[dict[str, object]]:
    validated = _validate_recovery_history(history)
    previous = str(validated[-1]["entry_hash"]) if validated else "0" * 64
    entry = dict(event)
    entry["previous_hash"] = previous
    entry["entry_hash"] = _recovery_history_digest(event, previous)
    validated.append(entry)
    return validated


def _transaction_journal_path(workspace: Path, proposal_id: str) -> Path:
    """Return a safe, stable journal path for one proposal transaction."""
    if not _PROPOSAL_ID.fullmatch(proposal_id):
        raise ValueError("Invalid proposal ID")
    root = workspace.expanduser().resolve()
    metadata = root / ".aurix"
    transactions = metadata / "transactions"
    if metadata.is_symlink() or transactions.is_symlink():
        raise PermissionError("AURIX transaction directories must not be symlinks")
    transactions.mkdir(parents=True, exist_ok=True)
    path = transactions / f"{proposal_id}.json"
    try:
        info = path.lstat()
    except FileNotFoundError:
        info = None
    if info is not None and not stat.S_ISREG(info.st_mode):
        raise PermissionError("AURIX transaction journal must be a regular file")
    return path


def _write_transaction_journal(
    workspace: Path, proposal_id: str, record: dict[str, object]
) -> None:
    """Durably replace a journal record; incomplete records require manual recovery."""
    if not isinstance(record, dict) or record.get("proposal_id") != proposal_id:
        raise ValueError("Transaction journal identity must match its proposal ID")
    path = _transaction_journal_path(workspace, proposal_id)
    payload = (
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    # Unique same-directory names prevent stale crash leftovers or PID reuse from
    # blocking later journal updates, while preserving atomic os.replace semantics.
    fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync is not supported on every platform; file content
            # remains fsynced, and the journal is still useful for recovery.
            pass
    finally:
        try:
            temp.unlink()
        except OSError:
            # Cleanup must not mask the primary write/replace failure.
            pass


def _assert_no_incomplete_transaction(workspace: Path, proposal_id: str) -> None:
    path = _transaction_journal_path(workspace, proposal_id)
    if not path.exists():
        return
    try:
        record = _load_strict_json(
                    _read_regular_file(path, max_bytes=1_000_000, label="Transaction journal").decode("utf-8")
                )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise PermissionError(
            "Transaction journal is unreadable; manual recovery is required"
        ) from exc
    if not isinstance(record, dict) or record.get("proposal_id") != proposal_id:
        raise PermissionError(
            "Transaction journal identity is invalid; manual recovery is required"
        )
    if record.get("state") not in {"applied_and_audited", "rolled_back", "reverted_and_audited"}:
        raise PermissionError(
            f"An incomplete transaction journal exists (state={record.get('state')!r}); "
            "inspect repository and journal before retrying"
        )


def _verified_lifecycle_audit_events(root: Path) -> tuple[dict[str, tuple[str, str | None]], str | None]:
    """Verify the complete local audit chain and return each proposal's latest lifecycle event."""
    metadata = root / ".aurix"
    lock_path = metadata / "audit.lock"
    if metadata.is_symlink() or lock_path.is_symlink():
        return {}, "audit metadata or append lock is a symlink"
    if lock_path.exists():
        return {}, "audit append lock exists; active or stale append requires manual review"
    log = metadata / "audit.jsonl"
    try:
        raw = _read_regular_file(log, max_bytes=10_000_000, label="Audit log")
    except FileNotFoundError:
        return {}, "audit log is missing"
    except (OSError, PermissionError, ValueError) as exc:
        return {}, f"audit log is unreadable: {type(exc).__name__}"
    lines = raw.splitlines()
    if len(lines) > 100_000:
        return {}, "audit log contains too many events"
    previous = "0" * 64
    latest: dict[str, tuple[str, str | None]] = {}
    try:
        for line in lines:
            item = _load_strict_json(line.decode("utf-8"))
            if not isinstance(item, dict):
                raise ValueError("event is not an object")
            digest = item.pop("event_hash", None)
            if not isinstance(digest, str) or item.get("previous_hash") != previous:
                raise ValueError("invalid chain link")
            canonical = json.dumps(
                item, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            expected = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
            if digest != expected:
                raise ValueError("invalid event hash")
            proposal_id = item.get("proposal_id")
            event = item.get("event")
            if isinstance(proposal_id, str) and event in {
                "proposal_applied",
                "proposal_reverted",
                "transaction_recovered",
                "transaction_recovery_finalized",
            }:
                details = item.get("details")
                patch_digest = details.get("patch_sha256") if isinstance(details, dict) else None
                latest[proposal_id] = (event, patch_digest if isinstance(patch_digest, str) else None)
            previous = digest
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return {}, "audit log hash chain is invalid"
    return latest, None


def inspect_transactions(workspace: Path | str) -> dict[str, object]:
    """Read-only inventory of transaction journals and current repository state.

    This command never edits journals, applies patches, or performs rollback. Any
    ambiguous or inconsistent record is classified for manual intervention.
    """
    root = Path(workspace).expanduser().resolve()
    metadata = root / ".aurix"
    transactions = metadata / "transactions"
    if metadata.is_symlink() or transactions.is_symlink():
        raise PermissionError("AURIX transaction directories must not be symlinks")
    if not transactions.exists():
        return {
            "status": "clean",
            "workspace": str(root),
            "count": 0,
            "transactions": [],
            "read_only": True,
            "tracked_worktree_dirty": False,
        }
    if not transactions.is_dir():
        raise PermissionError("AURIX transaction path is not a directory")

    head_result = _git(root, ["rev-parse", "HEAD"])
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    status_result = _git(root, ["status", "--porcelain", "--untracked-files=no"])
    tracked_dirty = status_result.returncode != 0 or bool(status_result.stdout.strip())
    rows: list[dict[str, object]] = []
    terminal = {"applied_and_audited", "rolled_back", "reverted_and_audited"}
    lifecycle_events, audit_error = _verified_lifecycle_audit_events(root)
    for path in sorted(transactions.iterdir()):
        if path.suffix != ".json":
            continue
        row: dict[str, object] = {
            "journal": path.relative_to(root).as_posix(),
            "proposal_id": path.stem,
        }
        if path.is_symlink() or not path.is_file():
            row.update(
                status="manual_intervention_required", reason="journal is not a regular file"
            )
            rows.append(row)
            continue
        try:
            record = _load_strict_json(
                    _read_regular_file(path, max_bytes=1_000_000, label="Transaction journal").decode("utf-8")
                )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            row.update(status="manual_intervention_required", reason="journal is unreadable")
            rows.append(row)
            continue
        if not isinstance(record, dict) or record.get("proposal_id") != path.stem:
            row.update(status="manual_intervention_required", reason="journal identity is invalid")
            rows.append(row)
            continue
        try:
            _validate_recovery_history(record.get("recovery_history", []))
        except (PermissionError, ValueError, TypeError) as exc:
            row.update(
                status="manual_intervention_required",
                reason=f"recovery history is invalid: {type(exc).__name__}",
            )
            rows.append(row)
            continue
        state = record.get("state")
        row.update(
            state=state,
            patch_sha256=record.get("patch_sha256"),
            base_commit=record.get("base_commit"),
        )
        proposal = metadata / "proposals" / f"{path.stem}.diff"
        proposal_digest = None
        if proposal.is_file() and not proposal.is_symlink():
            proposal_digest = hashlib.sha256(_read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal")).hexdigest()
        if not isinstance(record.get("patch_sha256"), str) or proposal_digest != record.get(
            "patch_sha256"
        ):
            row.update(
                status="manual_intervention_required", reason="proposal missing or digest mismatch"
            )
        elif state in {"recovery_in_progress", "recovery_interrupted"}:
            # Read-only reconciliation: infer the observed filesystem state without
            # rewriting the journal or claiming that recovery is complete.
            try:
                patch = _read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal").decode("utf-8")
                targets = record.get("targets")
                if (
                    not isinstance(targets, list)
                    or not targets
                    or not all(isinstance(item, str) for item in targets)
                ):
                    raise ValueError("invalid target inventory")
                expected_targets = sorted(set(targets))
                diff = _git(root, ["diff", "--name-only", "--no-renames"])
                staged = _git(root, ["diff", "--cached", "--name-only", "--no-renames"])
                actual_targets = sorted(line for line in diff.stdout.splitlines() if line)
                index_clean = staged.returncode == 0 and not staged.stdout.strip()
                if (
                    head == record.get("base_commit")
                    and not tracked_dirty
                    and index_clean
                    and diff.returncode == 0
                ):
                    row.update(
                        status="manual_intervention_required",
                        observed_state="rollback_effectively_completed_journal_unfinalized",
                        suggested_action="verify baseline and finalize journal only through an explicit recovery command",
                        reason="worktree appears clean at base commit, but journal remains non-terminal; no state changed",
                    )
                elif (
                    head == record.get("base_commit")
                    and index_clean
                    and diff.returncode == 0
                    and actual_targets == expected_targets
                    and _git(
                        root,
                        ["apply", "--reverse", "--check", "--whitespace=error", "-"],
                        patch=patch,
                    ).returncode
                    == 0
                ):
                    row.update(
                        status="manual_intervention_required",
                        observed_state="patch_still_applied_exactly",
                        suggested_action="review transaction and rerun explicit recovery after fresh preflight",
                        reason="exact applied patch remains; journal was not modified",
                    )
                else:
                    row.update(
                        status="manual_intervention_required",
                        observed_state="partial_or_external_changes",
                        suggested_action="manual_intervention_required",
                        reason="filesystem does not match either a verified baseline or the exact applied patch",
                    )
            except (OSError, UnicodeError, ValueError, RuntimeError, PermissionError) as exc:
                row.update(
                    status="manual_intervention_required",
                    observed_state="unknown",
                    reason=f"interrupted recovery state cannot be reconciled: {type(exc).__name__}",
                )
        elif state not in terminal:
            row.update(
                status="manual_intervention_required",
                reason="transaction is not in a terminal state",
            )
        elif not isinstance(record.get("targets"), list) or not all(
            isinstance(item, str) for item in record["targets"]
        ):
            row.update(status="manual_intervention_required", reason="target inventory is invalid")
        elif state in {"applied_and_audited", "reverted_and_audited"} and (
            audit_error is not None
            or lifecycle_events.get(path.stem, (None, None))[0]
            != ("proposal_applied" if state == "applied_and_audited" else "proposal_reverted")
            or (
                lifecycle_events.get(path.stem, (None, None))[1] is not None
                and lifecycle_events[path.stem][1] != record.get("patch_sha256")
            )
            or (
                state == "applied_and_audited"
                and lifecycle_events.get(path.stem, (None, None))[1] is None
            )
        ):
            row.update(
                status="manual_intervention_required",
                reason=(
                    audit_error
                    or "latest verified lifecycle audit event does not match the terminal journal state"
                ),
            )
        elif state == "applied_and_audited":
            diff = _git(root, ["diff", "--name-only", "--no-renames"])
            staged = _git(root, ["diff", "--cached", "--name-only", "--no-renames"])
            reverse_check = _git(
                root,
                ["apply", "--reverse", "--check", "--whitespace=error", "-"],
                patch=_read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal").decode("utf-8"),
            )
            expected_targets = sorted(set(record["targets"]))
            actual_targets = sorted(line for line in diff.stdout.splitlines() if line)
            if (
                head != record.get("base_commit")
                or diff.returncode != 0
                or staged.returncode != 0
                or bool(staged.stdout.strip())
                or actual_targets != expected_targets
                or reverse_check.returncode != 0
            ):
                row.update(
                    status="manual_intervention_required",
                    reason="repository state differs from the recorded applied state",
                )
            else:
                row.update(
                    status="consistent_terminal_record",
                    reason="applied patch and target set match the journal; no mutation performed",
                )
        elif state == "rolled_back" and (
            tracked_dirty or head != record.get("base_commit")
        ):
            row.update(
                status="manual_intervention_required",
                reason="repository state differs from the recorded rollback state",
            )
        elif state == "rolled_back" and any(
            isinstance(entry, dict)
            and entry.get("action") in {"exact_patch_rollback", "finalize_verified_rollback"}
            for entry in record.get("recovery_history", [])
        ):
            recovery_action = next(
                entry.get("action")
                for entry in reversed(record["recovery_history"])
                if isinstance(entry, dict)
                and entry.get("action") in {"exact_patch_rollback", "finalize_verified_rollback"}
            )
            expected_event = (
                "transaction_recovered"
                if recovery_action == "exact_patch_rollback"
                else "transaction_recovery_finalized"
            )
            latest_event = lifecycle_events.get(path.stem, (None, None))
            if (
                audit_error is not None
                or latest_event[0] != expected_event
                or latest_event[1] != record.get("patch_sha256")
            ):
                row.update(
                    status="manual_intervention_required",
                    reason=(
                        audit_error
                        or "latest verified recovery audit event does not match the recovery history"
                    ),
                )
            else:
                row.update(
                    status="consistent_terminal_record",
                    reason="rollback baseline and recovery audit evidence match; no mutation performed",
                )
        else:
            row.update(
                status="consistent_terminal_record",
                reason="record is structurally consistent; no mutation performed",
            )
        rows.append(row)
    needs_attention = any(row.get("status") == "manual_intervention_required" for row in rows)
    return {
        "status": "manual_intervention_required" if needs_attention else "inspected",
        "workspace": str(root),
        "count": len(rows),
        "transactions": rows,
        "read_only": True,
        "tracked_worktree_dirty": tracked_dirty,
    }


def plan_transaction_recovery(workspace: Path | str) -> dict[str, object]:
    """Build a read-only, fail-closed recovery plan for every transaction journal.

    This function intentionally does not execute the proposed action. A rollback
    candidate is emitted only when the current tracked diff exactly matches the
    recorded targets, HEAD is still the recorded base commit, the index is clean,
    the proposal digest matches, and Git accepts the exact inverse patch.
    """
    root = Path(workspace).expanduser().resolve()
    inspection = inspect_transactions(root)
    plans: list[dict[str, object]] = []
    metadata = root / ".aurix"
    _, planning_audit_error = _verified_lifecycle_audit_events(root)
    for row in inspection["transactions"]:
        assert isinstance(row, dict)
        proposal_id = row.get("proposal_id")
        journal_path = metadata / "transactions" / f"{proposal_id}.json"
        plan: dict[str, object] = {
            "proposal_id": proposal_id,
            "inspection_status": row.get("status"),
            "action": "manual_review",
            "safe_to_automate": False,
            "requires_explicit_confirmation": True,
            "mutates_workspace": False,
            "preconditions": [],
            "reason": row.get("reason", "transaction requires review"),
        }
        inspection_reason = str(row.get("reason", ""))
        if planning_audit_error is not None or "audit" in inspection_reason.casefold():
            plan["reason"] = (
                "audit evidence is inconsistent; automatic recovery planning is blocked"
                if planning_audit_error is not None
                else inspection_reason
            )
            plans.append(plan)
            continue
        try:
            record = _load_strict_json(
                _read_regular_file(
                    journal_path, max_bytes=1_000_000, label="Transaction journal"
                ).decode("utf-8")
            )
            if not isinstance(record, dict):
                raise ValueError("journal is not an object")
            _validate_recovery_history(record.get("recovery_history", []))
            state = record.get("state")
            plan["state"] = state
            proposal = _proposal_path(root, str(proposal_id))
            patch = _read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal").decode("utf-8")
            digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
            if digest != record.get("patch_sha256"):
                plan["reason"] = "proposal digest does not match journal; do not auto-recover"
            elif state == "patch_applied":
                head = _git_head(root)
                staged = _git(root, ["diff", "--cached", "--name-only", "--no-renames"])
                diff = _git(root, ["diff", "--name-only", "--no-renames"])
                targets = (
                    sorted(set(record.get("targets", [])))
                    if isinstance(record.get("targets"), list)
                    else []
                )
                actual = sorted(line for line in diff.stdout.splitlines() if line)
                reverse = _git(
                    root, ["apply", "--reverse", "--check", "--whitespace=error", "-"], patch=patch
                )
                checks = {
                    "base_commit_unchanged": head == record.get("base_commit"),
                    "index_clean": staged.returncode == 0 and not staged.stdout.strip(),
                    "tracked_diff_matches_targets": diff.returncode == 0
                    and actual == targets
                    and bool(targets),
                    "exact_inverse_applies": reverse.returncode == 0,
                }
                plan["preconditions"] = [
                    {"check": key, "passed": value} for key, value in checks.items()
                ]
                if all(checks.values()):
                    plan.update(
                        action="propose_exact_patch_rollback",
                        safe_to_automate=False,
                        reason="all rollback preconditions currently pass; operator confirmation and a fresh recheck are still required",
                    )
                else:
                    plan["reason"] = "rollback preconditions failed; manual intervention required"
            elif row.get("status") == "consistent_terminal_record":
                plan.update(
                    action="no_recovery_needed",
                    requires_explicit_confirmation=False,
                    reason="terminal journal is consistent; no mutation is recommended",
                )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
            PermissionError,
            RuntimeError,
        ) as exc:
            plan["reason"] = f"cannot safely plan recovery: {type(exc).__name__}"
        plans.append(plan)
    return {
        "schema_version": 1,
        "status": "manual_intervention_required"
        if any(p["action"] == "manual_review" for p in plans)
        else "plan_ready",
        "workspace": str(root),
        "count": len(plans),
        "plans": plans,
        "read_only": True,
        "execution_performed": False,
    }


def recover_transaction(
    workspace: Path | str, proposal_id: str, *, confirm: bool = False
) -> dict[str, str]:
    """Perform a narrowly-scoped, explicitly confirmed exact-patch rollback.

    Recovery is permitted for an interrupted ``patch_applied`` journal, or an
    ``applying`` journal whose exact patch is demonstrably present, when HEAD, the
    index, tracked diff, target inventory, proposal digest, and inverse check all
    match immediately before mutation. Ambiguous states fail closed.
    """
    if not confirm:
        raise PermissionError("Explicit confirmation is required to recover a transaction")
    root = Path(workspace).expanduser().resolve()
    with _workspace_operation_lock(root):
        journal_path = _transaction_journal_path(root, proposal_id)
        try:
            journal = _load_strict_json(
                _read_regular_file(
                    journal_path, max_bytes=1_000_000, label="Transaction journal"
                ).decode("utf-8")
            )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise PermissionError(
                "Transaction journal is unreadable; manual recovery is required"
            ) from exc
        if not isinstance(journal, dict) or journal.get("proposal_id") != proposal_id:
            raise PermissionError(
                "Transaction journal identity is invalid; manual recovery is required"
            )
        _, audit_error = _verified_lifecycle_audit_events(root)
        if audit_error is not None:
            raise PermissionError(
                f"Audit evidence is unavailable or inconsistent; recovery refused: {audit_error}"
            )
        if journal.get("state") not in {"applying", "patch_applied"}:
            raise PermissionError(
                "Only an interrupted patch_applied transaction (or an applying transaction "
                "with the exact patch present) can be recovered automatically"
            )
        _validate_recovery_history(journal.get("recovery_history", []))
        proposal = _proposal_path(root, proposal_id)
        # Recovery must validate and reverse the same proposal bytes; separate
        # text/byte reads could otherwise bind a different patch to the digest.
        proposal_bytes = _read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal")
        patch = proposal_bytes.decode("utf-8")
        digest = hashlib.sha256(proposal_bytes).hexdigest()
        if digest != journal.get("patch_sha256"):
            raise PermissionError("Proposal digest changed; automatic recovery refused")
        targets = journal.get("targets")
        if (
            not isinstance(targets, list)
            or not targets
            or not all(isinstance(t, str) for t in targets)
        ):
            raise PermissionError(
                "Transaction target inventory is invalid; manual recovery is required"
            )
        targets = sorted(set(targets))
        if _git_head(root) != journal.get("base_commit"):
            raise PermissionError(
                "Git HEAD changed since the transaction; automatic recovery refused"
            )
        staged = _git(root, ["diff", "--cached", "--name-only", "--no-renames"])
        diff = _git(root, ["diff", "--name-only", "--no-renames"])
        actual = sorted(line for line in diff.stdout.splitlines() if line)
        if staged.returncode or staged.stdout.strip():
            raise PermissionError("Git index is not clean; automatic recovery refused")
        if diff.returncode or actual != targets:
            raise PermissionError(
                "Tracked diff differs from transaction targets; manual recovery is required"
            )
        inverse = _git(
            root, ["apply", "--reverse", "--check", "--whitespace=error", "-"], patch=patch
        )
        if inverse.returncode:
            raise PermissionError(
                "Exact inverse patch no longer applies; manual recovery is required"
            )
        # Recheck every relevant precondition immediately before the journal enters
        # the non-retryable state. The lock coordinates AURIX operations, not editors.
        if hashlib.sha256(_read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal")).hexdigest() != digest or _git_head(
            root
        ) != journal.get("base_commit"):
            raise PermissionError("Repository or proposal changed during recovery preflight")
        staged = _git(root, ["diff", "--cached", "--name-only", "--no-renames"])
        diff = _git(root, ["diff", "--name-only", "--no-renames"])
        if (
            staged.returncode
            or staged.stdout.strip()
            or diff.returncode
            or sorted(diff.stdout.splitlines()) != targets
        ):
            raise PermissionError("Repository changed during recovery preflight")
        baseline_target_state = _target_state_snapshot(root, targets)
        now = time.time()
        journal.update(
            state="recovery_in_progress",
            recovery="pending_verification",
            updated_at=now,
            recovery_attempt={
                "started_at": now,
                "action": "exact_patch_rollback",
                "patch_sha256": digest,
            },
        )
        _write_transaction_journal(root, proposal_id, journal)
        # Journal persistence can race with editors just like apply/revert. Recheck
        # all mutation preconditions after the durable state transition and before
        # reversing any source file.
        try:
            post_journal_proposal_digest = hashlib.sha256(
                _read_regular_file(
                    proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal"
                )
            ).hexdigest()
            post_journal_status = _git(
                root, ["status", "--porcelain", "--untracked-files=no"]
            )
            post_journal_staged = _git(
                root, ["diff", "--cached", "--name-only", "--no-renames"]
            )
            post_journal_diff = _git(root, ["diff", "--name-only", "--no-renames"])
            recovery_preconditions_valid = (
                post_journal_proposal_digest == digest
                and _git_head(root) == journal.get("base_commit")
                and post_journal_status.returncode == 0
                and bool(post_journal_status.stdout.strip())
                and post_journal_staged.returncode == 0
                and not post_journal_staged.stdout.strip()
                and post_journal_diff.returncode == 0
                and sorted(line for line in post_journal_diff.stdout.splitlines() if line)
                == targets
                and _target_state_snapshot(root, targets) == baseline_target_state
            )
        except Exception:
            recovery_preconditions_valid = False
        if not recovery_preconditions_valid:
            journal.update(
                state="recovery_interrupted",
                recovery="manual_intervention_required",
                updated_at=time.time(),
                reason="Repository changed after recovery journal persistence",
            )
            _write_transaction_journal(root, proposal_id, journal)
            raise PermissionError(
                "Repository changed after recovery journal persistence; "
                "manual intervention is required"
            )
        rollback = _git(root, ["apply", "--reverse", "--whitespace=error", "-"], patch=patch)
        if rollback.returncode:
            journal.update(
                state="recovery_interrupted",
                recovery="manual_intervention_required",
                updated_at=time.time(),
                recovery_attempt={
                    "started_at": now,
                    "action": "exact_patch_rollback",
                    "patch_sha256": digest,
                    "error": rollback.stderr.strip()[:500],
                },
            )
            _write_transaction_journal(root, proposal_id, journal)
            raise RuntimeError(
                "Exact rollback failed; recovery journal preserved for manual intervention"
            )
        final_head = _git_head(root)
        final_status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
        if (
            final_head != journal.get("base_commit")
            or final_status.returncode
            or final_status.stdout.strip()
        ):
            journal.update(
                state="recovery_interrupted",
                recovery="manual_intervention_required",
                updated_at=time.time(),
            )
            _write_transaction_journal(root, proposal_id, journal)
            raise RuntimeError(
                "Rollback result could not be verified; manual intervention is required"
            )
        history = _append_recovery_history(
            journal.get("recovery_history", []),
            {
                "action": "exact_patch_rollback",
                "started_at": now,
                "completed_at": time.time(),
                "patch_sha256": digest,
                "result": "verified",
            },
        )
        journal.update(
            state="rolled_back",
            recovery="verified",
            updated_at=time.time(),
            recovery_history=history,
        )
        journal.pop("recovery_attempt", None)
        _write_transaction_journal(root, proposal_id, journal)
        audit_error_after_rollback: Exception | None = None
        try:
            append_audit_event(
                root,
                "transaction_recovered",
                proposal_id,
                {"action": "exact_patch_rollback", "patch_sha256": digest, "result": "verified"},
            )
        except Exception as exc:
            audit_error_after_rollback = exc

        # Audit persistence and the terminal journal write are both race windows.
        # Verify the rollback baseline again before reporting a terminal recovery.
        try:
            final_proposal_digest = hashlib.sha256(
                _read_regular_file(
                    proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal"
                )
            ).hexdigest()
            final_head = _git_head(root)
            final_status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
            final_staged = _git(root, ["diff", "--cached", "--name-only", "--no-renames"])
            baseline_still_valid = (
                final_proposal_digest == digest
                and final_head == journal.get("base_commit")
                and final_status.returncode == 0
                and not final_status.stdout.strip()
                and final_staged.returncode == 0
                and not final_staged.stdout.strip()
            )
        except Exception:
            baseline_still_valid = False
        if not baseline_still_valid:
            journal.update(
                state="recovery_interrupted",
                recovery="manual_intervention_required",
                updated_at=time.time(),
                reason="Repository changed during recovery journal/audit persistence",
            )
            _write_transaction_journal(root, proposal_id, journal)
            raise RuntimeError(
                "Repository changed during recovery finalization; transaction was "
                "returned to a non-terminal state. Manual intervention is required."
            ) from audit_error_after_rollback
        if audit_error_after_rollback is not None:
            raise RuntimeError(
                "Rollback verified, but recovery audit event could not be persisted"
            ) from audit_error_after_rollback
        return {
            "proposal_id": proposal_id,
            "status": "recovered",
            "transaction": "rolled_back",
            "recovery_status": "verified",
            "journal": str(journal_path.relative_to(root)),
        }


def finalize_interrupted_recovery(
    workspace: Path | str, proposal_id: str, *, confirm: bool = False
) -> dict[str, str]:
    """Finalize a recovery journal only when rollback is independently verifiable.

    This never changes source files. It only transitions an interrupted journal to
    ``rolled_back`` when HEAD is still the recorded base and the tracked worktree
    and index are clean. Any ambiguity remains a manual-recovery case.
    """
    if not confirm:
        raise PermissionError("Explicit confirmation is required to finalize interrupted recovery")
    root = Path(workspace).expanduser().resolve()
    with _workspace_operation_lock(root):
        journal_path = _transaction_journal_path(root, proposal_id)
        try:
            journal = _load_strict_json(
                _read_regular_file(
                    journal_path, max_bytes=1_000_000, label="Transaction journal"
                ).decode("utf-8")
            )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise PermissionError(
                "Transaction journal is unreadable; manual recovery is required"
            ) from exc
        if not isinstance(journal, dict) or journal.get("proposal_id") != proposal_id:
            raise PermissionError(
                "Transaction journal identity is invalid; manual recovery is required"
            )
        _, audit_error = _verified_lifecycle_audit_events(root)
        if audit_error is not None:
            raise PermissionError(
                f"Audit evidence is unavailable or inconsistent; recovery finalization refused: {audit_error}"
            )
        if journal.get("state") not in {"recovery_in_progress", "recovery_interrupted"}:
            raise PermissionError("Only an interrupted recovery journal can be finalized")
        _validate_recovery_history(journal.get("recovery_history", []))
        proposal = _proposal_path(root, proposal_id)
        digest = hashlib.sha256(_read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal")).hexdigest()
        if digest != journal.get("patch_sha256"):
            raise PermissionError("Proposal digest changed; manual recovery is required")
        base_commit = journal.get("base_commit")
        if not isinstance(base_commit, str) or _git_head(root) != base_commit:
            raise PermissionError(
                "Git HEAD does not match recorded base; manual recovery is required"
            )
        status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
        staged = _git(root, ["diff", "--cached", "--name-only", "--no-renames"])
        if status.returncode or status.stdout.strip() or staged.returncode or staged.stdout.strip():
            raise PermissionError(
                "Tracked worktree or index is not clean; recovery cannot be finalized"
            )
        # Re-read key evidence immediately before the journal-only transition.
        if (
            hashlib.sha256(_read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal")).hexdigest() != digest
            or _git_head(root) != base_commit
        ):
            raise PermissionError("Repository changed during recovery finalization preflight")
        status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
        if status.returncode or status.stdout.strip():
            raise PermissionError("Repository changed during recovery finalization preflight")
        now = time.time()
        history = _append_recovery_history(
            journal.get("recovery_history", []),
            {
                "action": "finalize_verified_rollback",
                "completed_at": now,
                "patch_sha256": digest,
                "result": "baseline_verified",
                "source_state": journal.get("state"),
            },
        )
        journal.update(
            state="rolled_back", recovery="verified", updated_at=now, recovery_history=history
        )
        journal.pop("recovery_attempt", None)
        _write_transaction_journal(root, proposal_id, journal)
        audit_error_after_finalize: Exception | None = None
        try:
            append_audit_event(
                root,
                "transaction_recovery_finalized",
                proposal_id,
                {
                    "action": "finalize_verified_rollback",
                    "patch_sha256": digest,
                    "result": "baseline_verified",
                },
            )
        except Exception as exc:
            audit_error_after_finalize = exc

        # Recheck after both journal and audit persistence; never leave a verified
        # terminal label if an external writer dirtied the baseline in that window.
        try:
            final_digest = hashlib.sha256(
                _read_regular_file(
                    proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal"
                )
            ).hexdigest()
            final_head = _git_head(root)
            final_status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
            final_staged = _git(root, ["diff", "--cached", "--name-only", "--no-renames"])
            baseline_still_valid = (
                final_digest == digest
                and final_head == base_commit
                and final_status.returncode == 0
                and not final_status.stdout.strip()
                and final_staged.returncode == 0
                and not final_staged.stdout.strip()
            )
        except Exception:
            baseline_still_valid = False
        if not baseline_still_valid:
            journal.update(
                state="recovery_interrupted",
                recovery="manual_intervention_required",
                updated_at=time.time(),
                reason="Repository changed during recovery-finalization journal/audit persistence",
            )
            _write_transaction_journal(root, proposal_id, journal)
            raise RuntimeError(
                "Repository changed during recovery finalization; transaction was "
                "returned to a non-terminal state. Manual intervention is required."
            ) from audit_error_after_finalize
        if audit_error_after_finalize is not None:
            raise RuntimeError(
                "Rollback baseline finalized, but recovery-finalization audit event "
                "could not be persisted; inspect the audit chain"
            ) from audit_error_after_finalize
        return {
            "proposal_id": proposal_id,
            "status": "finalized",
            "transaction": "rolled_back",
            "recovery_status": "baseline_verified",
            "journal": str(journal_path.relative_to(root)),
        }


def _git_head(workspace: Path) -> str:
    result = _git(workspace, ["rev-parse", "HEAD"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Could not inspect Git HEAD")
    return result.stdout.strip()


def _tracked_status(workspace: Path) -> str:
    result = _git(workspace, ["status", "--porcelain", "--untracked-files=no"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Could not verify Git worktree state")
    return result.stdout.strip()


def _rollback_exact_patch(
    workspace: Path, patch: str, *, expected_status: str, reason: str
) -> None:
    """Apply the exact inverse and verify the final tracked-worktree state."""
    reverse_check = _git(
        workspace, ["apply", "--reverse", "--check", "--whitespace=error", "-"], patch=patch
    )
    if reverse_check.returncode != 0:
        raise RuntimeError(
            f"{reason}; automatic rollback refused because the exact inverse no longer applies. "
            "Recovery status: manual_intervention_required. Inspect the worktree immediately."
        )
    rollback = _git(workspace, ["apply", "--reverse", "--whitespace=error", "-"], patch=patch)
    if rollback.returncode != 0:
        raise RuntimeError(
            f"{reason}; automatic rollback failed. Recovery status: manual_intervention_required. "
            "Inspect the worktree immediately."
        )
    try:
        actual_status = _tracked_status(workspace)
    except Exception as exc:
        raise RuntimeError(
            f"{reason}; inverse patch ran but final state could not be verified. "
            "Recovery status: manual_intervention_required."
        ) from exc
    if actual_status != expected_status:
        raise RuntimeError(
            f"{reason}; inverse patch ran but final tracked status differs from expectation. "
            "Recovery status: manual_intervention_required. Inspect the worktree immediately."
        )


def _hash_regular_file_snapshot(path: Path, *, label: str) -> str:
    """Hash one regular file through a no-follow descriptor and detect concurrent writes."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {40, 62}:  # ELOOP on common POSIX platforms
            raise PermissionError(f"{label} must not be a symlink") from exc
        raise
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise PermissionError(f"{label} is not a regular file")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(fd)
        stable_before = (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        )
        stable_after = (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        )
        if stable_before != stable_after or total != after.st_size:
            raise PermissionError(f"{label} changed while its snapshot was being read")
        return digest.hexdigest()
    finally:
        os.close(fd)


def _target_state_snapshot(workspace: Path, targets: Sequence[str]) -> list[dict[str, str]]:
    """Capture stable hashes of approved regular-file targets before audit/application."""
    root = workspace.expanduser().resolve()
    snapshot: list[dict[str, str]] = []
    for relative in sorted(set(targets)):
        target = safe_path(root, relative)
        if target.is_symlink() or not target.is_file() or root not in target.resolve().parents:
            raise PermissionError(f"Patch target changed or became unsafe: {relative}")
        snapshot.append(
            {"path": relative, "sha256": _hash_regular_file_snapshot(target, label="Patch target")}
        )
    return snapshot


def _target_state_digest(snapshot: object) -> str | None:
    if not isinstance(snapshot, list):
        return None
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("path"), str)
        or not isinstance(item.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", ""))
        for item in snapshot
    ):
        return None
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()



def _expected_target_state_after_patch(
    workspace: Path,
    patch: str,
    targets: Sequence[str],
    baseline_snapshot: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Apply a patch to an isolated copy and hash its exact expected target contents."""
    root = workspace.expanduser().resolve()
    baseline = {item["path"]: item["sha256"] for item in baseline_snapshot}
    expected_paths = sorted(set(targets))
    if sorted(baseline) != expected_paths:
        raise PermissionError("Patch target baseline does not match the approved target inventory")

    with tempfile.TemporaryDirectory(prefix="aurix-patch-expected-") as temporary:
        mirror = Path(temporary)
        for relative in expected_paths:
            source = safe_path(root, relative)
            destination = mirror / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(source, flags)
            digest = hashlib.sha256()
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise PermissionError(f"Patch target is not a regular file: {relative}")
                with os.fdopen(fd, "rb") as source_stream:
                    fd = -1
                    with destination.open("wb") as destination_stream:
                        while True:
                            chunk = source_stream.read(65536)
                            if not chunk:
                                break
                            digest.update(chunk)
                            destination_stream.write(chunk)
                        destination_stream.flush()
                        os.fsync(destination_stream.fileno())
                    after = os.fstat(source_stream.fileno())
                stable_before = (
                    before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns,
                )
                stable_after = (
                    after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns,
                )
                if stable_before != stable_after or digest.hexdigest() != baseline[relative]:
                    raise PermissionError(
                        f"Patch target changed during application preflight: {relative}"
                    )
                destination.chmod(stat.S_IMODE(before.st_mode))
            finally:
                if fd >= 0:
                    os.close(fd)

        result = subprocess.run(
            ["git", "apply", "--whitespace=error", "-"],
            cwd=mirror,
            input=patch,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Could not derive expected patch result in an isolated copy: "
                f"{result.stderr.strip()[:300]}"
            )
        return [
            {
                "path": relative,
                "sha256": _hash_regular_file_snapshot(
                    mirror / relative, label="Expected patch target"
                ),
            }
            for relative in expected_paths
        ]

def _review_track_evidence_valid(track: object, patch: str, patch_digest: str) -> bool:
    """Validate review-track digest and every finding against exact added patch lines."""
    if not isinstance(track, dict):
        return False
    if (
        track.get("proposal_sha256") != patch_digest
        or track.get("evidence_schema") != 1
        or not isinstance(track.get("findings"), list)
    ):
        return False
    lines = patch.splitlines()
    for finding in track["findings"]:
        if not isinstance(finding, dict) or not isinstance(finding.get("evidence"), dict):
            return False
        evidence = finding["evidence"]
        patch_line = evidence.get("patch_line")
        if (
            evidence.get("patch_sha256") != patch_digest
            or evidence.get("file") != finding.get("file")
            or evidence.get("patch_line") != finding.get("patch_line")
            or not isinstance(patch_line, int)
            or patch_line < 1
            or patch_line > len(lines)
        ):
            return False
        line = lines[patch_line - 1]
        if not line.startswith("+") or line.startswith("+++"):
            return False
        actual_line_digest = hashlib.sha256(line[1:].encode("utf-8")).hexdigest()
        if evidence.get("line_sha256") != actual_line_digest:
            return False
        if evidence.get("source_line") is not None and (
            not isinstance(evidence.get("source_line"), int) or evidence["source_line"] < 1
        ):
            return False
        if not isinstance(evidence.get("hunk"), str) or not evidence["hunk"].startswith("@@"):
            return False
    return True


def _apply_proposal_locked(
    workspace: Path | str,
    proposal_id: str,
    *,
    confirm: bool = False,
    require_audit_gate: bool = False,
) -> dict[str, str]:
    """Apply a proposal after explicit confirmation and optional passing-audit gate.

    The gate binds recorded low-risk review and passing verification to the exact
    proposal digest. Local evidence is tamper-evident, not a remote trust anchor.
    """
    if not confirm:
        raise PermissionError("Explicit confirmation is required to apply a patch")
    root = Path(workspace).expanduser().resolve()
    initial_head = _git_head(root)
    proposal = _proposal_path(root, proposal_id)
    _assert_no_incomplete_transaction(root, proposal_id)
    # Decode and hash the same byte snapshot. Separate read_text/read_bytes calls
    # could observe different proposal contents if an external process swaps the
    # file between reads, misbinding the applied patch to its recorded digest.
    proposal_bytes = _read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal")
    patch = proposal_bytes.decode("utf-8")
    patch_digest = hashlib.sha256(proposal_bytes).hexdigest()
    if require_audit_gate:
        audit_dir = root / ".aurix" / "audits"
        audit_path = audit_dir / f"{proposal_id}.json"
        if (
            audit_dir.is_symlink()
            or audit_path.is_symlink()
            or not audit_path.is_file()
            or audit_path.stat().st_size > 1_000_000
        ):
            raise PermissionError("A passing audit record is required before application")
        try:
            audit = _load_strict_json(_read_regular_file(audit_path, max_bytes=1_000_000, label="Audit evidence").decode("utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise PermissionError("Audit evidence is unreadable; refusing application") from exc
        verification = audit.get("verification", {})
        review = audit.get("review", {})
        tracks = audit.get("review_tracks", {})
        security_track = tracks.get("security", {})
        correctness_track = tracks.get("correctness", {})
        verification_evidence = {
            key: verification.get(key)
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
        expected_evidence_digest = hashlib.sha256(
            json.dumps(
                verification_evidence,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        head = _git(root, ["rev-parse", "HEAD"])
        target_state = audit.get("target_state")
        target_state_digest = _target_state_digest(target_state)
        if (
            audit.get("schema_version") != 9
            or target_state_digest is None
            or verification.get("target_state_sha256") != target_state_digest
            or not isinstance(audit.get("audit_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", audit.get("audit_id", ""))
            or verification.get("audit_id") != audit.get("audit_id")
            or not isinstance(verification.get("verification_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", verification.get("verification_id", ""))
            or audit.get("proposal_id") != proposal_id
            or audit.get("proposal_sha256") != patch_digest
            or audit.get("status") != "audit_passed"
            or not head.returncode == 0
            or audit.get("base_commit") != head.stdout.strip()
            or verification.get("evidence_sha256") != expected_evidence_digest
            or verification.get("proposal_id") != proposal_id
            or verification.get("proposal_sha256") != patch_digest
            or verification.get("base_commit") != head.stdout.strip()
            or verification.get("suite") not in {"pytest", "ruff"}
            or verification.get("requested_suite") not in {"pytest", "ruff", "auto"}
            or not isinstance(verification.get("test_selection"), dict)
            or verification.get("isolation") not in {"trusted", "docker"}
            or not isinstance(verification.get("runtime_fingerprint"), dict)
            or not all(
                verification["runtime_fingerprint"].get(key)
                for key in (
                    "python_version",
                    "python_implementation",
                    "system",
                    "release",
                    "machine",
                )
            )
            or (
                verification.get("isolation") == "docker"
                and not re.fullmatch(
                    r"sha256:[0-9a-f]{64}", str(verification.get("sandbox_image_id", ""))
                )
            )
            or (
                verification.get("isolation") == "trusted"
                and verification.get("sandbox_image_id") is not None
            )
            or verification.get("regression_status") == "introduced_failure"
            or not isinstance(verification.get("baseline_result"), dict)
            or type(verification["baseline_result"].get("passed")) is not bool
            or verification["baseline_result"].get("passed") is not True
            or type(verification["baseline_result"].get("returncode")) is not int
            or verification["baseline_result"].get("returncode") != 0
            or not isinstance(verification.get("test_result"), dict)
            or type(verification["test_result"].get("passed")) is not bool
            or verification["test_result"].get("passed") is not True
            or type(verification["test_result"].get("returncode")) is not int
            or verification["test_result"].get("returncode") != 0
            or review.get("risk_level") != "low"
            or security_track.get("proposal_sha256") != patch_digest
            or security_track.get("risk_level") != "low"
            or correctness_track.get("proposal_sha256") != patch_digest
            or correctness_track.get("risk_level") != "low"
            or not _review_track_evidence_valid(security_track, patch, patch_digest)
            or not _review_track_evidence_valid(correctness_track, patch, patch_digest)
            or verification.get("status") != "verified_pass"
        ):
            raise PermissionError(
                "Audit evidence does not approve this exact patch; rerun audit and verification"
            )
    targets = _validate_patch(root, patch)
    if require_audit_gate:
        if _target_state_snapshot(root, targets) != target_state:
            raise PermissionError(
                "Patch target files changed since audit; rerun audit and verification"
            )
    inside = _git(root, ["rev-parse", "--show-toplevel"])
    if inside.returncode != 0 or Path(inside.stdout.strip()).resolve() != root:
        raise ValueError("Workspace must be the Git repository root")
    status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip() or "Could not inspect Git status")
    if status.stdout.strip():
        raise PermissionError(
            "Git worktree has tracked changes; commit or stash them before applying"
        )
    if hashlib.sha256(_read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal")).hexdigest() != patch_digest:
        raise PermissionError("Proposal changed during application preflight; refusing to apply")
    check = _git(root, ["apply", "--check", "--whitespace=error", "-"], patch=patch)
    if check.returncode != 0:
        raise ValueError(f"Patch preflight failed: {check.stderr.strip()[:500]}")
    # Revalidate repository identity and cleanliness at the last possible point
    # before applying. Capture target hashes so edits racing the final Git apply
    # cannot be silently bundled into the approved patch.
    if _git_head(root) != initial_head:
        raise PermissionError("Git HEAD changed during preflight; rerun audit and verification")
    baseline_target_state = _target_state_snapshot(root, targets)
    final_preflight_status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
    if final_preflight_status.returncode != 0 or final_preflight_status.stdout.strip():
        raise PermissionError("Tracked worktree changed during preflight; refusing to apply")
    if require_audit_gate and baseline_target_state != target_state:
        raise PermissionError(
            "Patch target files changed during final preflight; refusing to apply"
        )
    expected_target_state = _expected_target_state_after_patch(
        root, patch, targets, baseline_target_state
    )
    transaction = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "patch_sha256": patch_digest,
        "base_commit": initial_head,
        "targets": sorted(set(targets)),
        "state": "applying",
        "updated_at": time.time(),
        "recovery": "manual_if_interrupted",
    }
    _write_transaction_journal(root, proposal_id, transaction)
    # Journal persistence can take long enough for an external editor or Git
    # process to change the worktree after the earlier preflight. Recheck the
    # base commit, tracked cleanliness, and target snapshot immediately before
    # the mutating Git operation. A remaining race after these checks is still
    # possible; post-apply reconciliation remains mandatory.
    if _git_head(root) != initial_head:
        raise PermissionError(
            "Git HEAD changed after transaction journal creation; refusing to apply"
        )
    pre_apply_status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
    if pre_apply_status.returncode != 0 or pre_apply_status.stdout.strip():
        raise PermissionError(
            "Tracked worktree changed after transaction journal creation; refusing to apply"
        )
    if _target_state_snapshot(root, targets) != baseline_target_state:
        raise PermissionError(
            "Patch targets changed after transaction journal creation; refusing to apply"
        )
    applied = _git(root, ["apply", "--whitespace=error", "-"], patch=patch)
    if applied.returncode != 0:
        # Git apply is expected to be atomic, but explicitly inspect and recover
        # if a Git/platform failure leaves any of the intended edits behind.
        reverse_check = _git(
            root, ["apply", "--reverse", "--check", "--whitespace=error", "-"], patch=patch
        )
        if reverse_check.returncode == 0:
            _rollback_exact_patch(
                root, patch, expected_status="", reason="Patch application failed"
            )
            transaction.update(state="rolled_back", updated_at=time.time(), recovery="verified")
            _write_transaction_journal(root, proposal_id, transaction)
        raise RuntimeError(
            f"Patch application failed: {applied.stderr.strip()[:500]}. "
            "Recovery status: manual_intervention_required; inspect the worktree."
        )

    transaction.update(
        state="patch_applied", updated_at=time.time(), recovery="pending_verification"
    )
    _write_transaction_journal(root, proposal_id, transaction)
    if _git_head(root) != initial_head:
        raise RuntimeError(
            "Git HEAD changed while the patch was being applied; automatic rollback is "
            "unsafe. Recovery status: manual_intervention_required."
        )

    def rollback_applied_patch(reason: str) -> None:
        _rollback_exact_patch(root, patch, expected_status="", reason=reason)
        transaction.update(
            state="rolled_back", updated_at=time.time(), recovery="verified", reason=reason
        )
        _write_transaction_journal(root, proposal_id, transaction)

    # Confirm the resulting tracked diff is exactly the set of approved targets.
    changed = _git(root, ["diff", "--name-only", "--no-renames"])
    actual_targets = sorted(line for line in changed.stdout.splitlines() if line)
    if changed.returncode != 0 or actual_targets != sorted(set(targets)):
        rollback_applied_patch("Applied diff did not match the approved target set")
        raise RuntimeError(
            "Applied diff did not match the approved target set; changes were rolled back"
        )
    if _target_state_snapshot(root, targets) != expected_target_state:
        rollback_applied_patch("Applied target contents differ from the isolated expected patch result")
        raise RuntimeError(
            "Applied target contents differed from the approved patch result; "
            "changes were rolled back where safe and manual intervention may be required"
        )
    if hashlib.sha256(_read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal")).hexdigest() != patch_digest:
        rollback_applied_patch("Proposal changed during application")
        raise PermissionError("Proposal changed during application; changes were rolled back")
    try:
        append_audit_event(
            root,
            "proposal_applied",
            proposal_id,
            {
                "files": targets,
                "patch_sha256": patch_digest,
            },
        )
    except Exception as exc:
        rollback_applied_patch("Could not persist the application audit event")
        raise RuntimeError("Audit logging failed; patch application was rolled back") from exc

    # Reconcile once more after the audit write: arbitrary editors do not honor
    # AURIX's operation lock and may change either a target or another tracked file
    # while the audit event is being persisted. Leave the journal non-terminal if
    # the repository no longer matches the exact expected patch result.
    post_audit_status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
    post_audit_changed = _git(root, ["diff", "--name-only", "--no-renames"])
    post_audit_staged = _git(root, ["diff", "--cached", "--quiet"])
    post_audit_targets = sorted(
        line for line in post_audit_changed.stdout.splitlines() if line
    )
    current_proposal = _read_regular_file(
        proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal"
    )
    if (
        post_audit_status.returncode != 0
        or post_audit_changed.returncode != 0
        or post_audit_staged.returncode != 0
        or _git_head(root) != initial_head
        or post_audit_targets != sorted(set(targets))
        or _target_state_snapshot(root, targets) != expected_target_state
        or hashlib.sha256(current_proposal).hexdigest() != patch_digest
    ):
        raise RuntimeError(
            "Repository changed after the application audit event; transaction remains "
            "non-terminal. Recovery status: manual_intervention_required."
        )
    transaction.update(state="applied_and_audited", updated_at=time.time(), recovery="verified")
    _write_transaction_journal(root, proposal_id, transaction)
    # Journal persistence itself is another race window: an external writer may
    # change tracked files while the terminal record is being written.
    final_status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
    final_changed = _git(root, ["diff", "--name-only", "--no-renames"])
    final_staged = _git(root, ["diff", "--cached", "--quiet"])
    final_proposal = _read_regular_file(
        proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal"
    )
    try:
        final_state_valid = (
            final_status.returncode == 0
            and bool(final_status.stdout.strip())
            and final_changed.returncode == 0
            and final_staged.returncode == 0
            and _git_head(root) == initial_head
            and sorted(line for line in final_changed.stdout.splitlines() if line)
            == sorted(set(targets))
            and _target_state_snapshot(root, targets) == expected_target_state
            and hashlib.sha256(final_proposal).hexdigest() == patch_digest
        )
    except Exception:
        final_state_valid = False
    if not final_state_valid:
        transaction.update(
            state="patch_applied",
            updated_at=time.time(),
            recovery="pending_verification",
            reason="Repository changed during terminal journal persistence",
        )
        _write_transaction_journal(root, proposal_id, transaction)
        raise RuntimeError(
            "Repository changed during terminal journal persistence; transaction "
            "was returned to a non-terminal state. "
            "Recovery status: manual_intervention_required."
        )
    return {
        "proposal_id": proposal_id,
        "status": "applied",
        "files": ", ".join(targets),
        "reversible_with": f"aurix --revert-proposal {proposal_id} --confirm-revert",
        "transaction": "applied_and_audited",
        "journal": str(_transaction_journal_path(root, proposal_id).relative_to(root)),
    }


def _revert_proposal_locked(
    workspace: Path | str, proposal_id: str, *, confirm: bool = False
) -> dict[str, str]:
    """Reverse an applied proposal if its exact inverse still applies cleanly."""
    if not confirm:
        raise PermissionError("Explicit confirmation is required to revert a patch")
    root = Path(workspace).expanduser().resolve()
    _assert_no_incomplete_transaction(root, proposal_id)
    initial_head = _git_head(root)
    proposal = _proposal_path(root, proposal_id)
    proposal_bytes = _read_regular_file(
        proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal"
    )
    patch = proposal_bytes.decode("utf-8")
    patch_digest = hashlib.sha256(proposal_bytes).hexdigest()
    targets = _validate_patch(root, patch)
    inside = _git(root, ["rev-parse", "--show-toplevel"])
    if inside.returncode != 0 or Path(inside.stdout.strip()).resolve() != root:
        raise ValueError("Workspace must be the Git repository root")
    status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
    staged = _git(root, ["diff", "--cached", "--name-only", "--no-renames"])
    changed = _git(root, ["diff", "--name-only", "--no-renames"])
    actual_targets = sorted(line for line in changed.stdout.splitlines() if line)
    if (
        status.returncode != 0
        or not status.stdout.strip()
        or staged.returncode != 0
        or staged.stdout.strip()
        or changed.returncode != 0
        or actual_targets != sorted(set(targets))
    ):
        raise PermissionError(
            "Tracked worktree or index differs from the exact applied proposal; "
            "manual intervention is required"
        )
    check = _git(root, ["apply", "--reverse", "--check", "--whitespace=error", "-"], patch=patch)
    if check.returncode != 0:
        raise ValueError(
            "Exact reverse patch no longer applies; refusing to risk unrelated changes"
        )
    before_status = status.stdout.strip()
    if _git_head(root) != initial_head or _tracked_status(root) != before_status:
        raise PermissionError("Repository changed during reversal preflight; refusing to revert")
    baseline_target_state = _target_state_snapshot(root, targets)
    if _git_head(root) != initial_head or _tracked_status(root) != before_status:
        raise PermissionError("Repository changed during reversal target snapshot; refusing to revert")
    journal_path = _transaction_journal_path(root, proposal_id)
    transaction: dict[str, object] | None = None
    if journal_path.exists():
        transaction_value = _load_strict_json(
            _read_regular_file(
                journal_path, max_bytes=1_000_000, label="Transaction journal"
            ).decode("utf-8")
        )
        if (
            not isinstance(transaction_value, dict)
            or transaction_value.get("proposal_id") != proposal_id
            or transaction_value.get("state") != "applied_and_audited"
            or transaction_value.get("patch_sha256") != hashlib.sha256(patch.encode("utf-8")).hexdigest()
        ):
            raise PermissionError(
                "Transaction journal does not match the applied proposal; manual recovery is required"
            )
        transaction = dict(transaction_value)
        transaction.update(
            state="reverting", updated_at=time.time(), recovery="pending_verification"
        )
        _write_transaction_journal(root, proposal_id, transaction)
    else:
        # Older proposals may predate transaction journals. Create a durable
        # recovery record before mutating them so race/failure paths are still
        # inspectable instead of leaving an unjournaled partial reversal.
        transaction = {
            "schema_version": 1,
            "proposal_id": proposal_id,
            "patch_sha256": patch_digest,
            "base_commit": initial_head,
            "targets": sorted(set(targets)),
            "state": "reverting",
            "updated_at": time.time(),
            "recovery": "pending_verification",
            "reason": "Journal created while reverting a legacy proposal",
        }
        _write_transaction_journal(root, proposal_id, transaction)
    # Journal persistence is a separate filesystem operation: an external editor
    # can modify a target while it is being written. Revalidate the exact state
    # before running the inverse patch, rather than relying only on the earlier
    # preflight. A remaining race after this check is handled by reconciliation.
    if (
        _git_head(root) != initial_head
        or _tracked_status(root) != before_status
        or hashlib.sha256(
            _read_regular_file(proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal")
        ).hexdigest() != patch_digest
        or _target_state_snapshot(root, targets) != baseline_target_state
    ):
        raise PermissionError(
            "Repository or patch targets changed after reversal journal persistence; "
            "manual intervention is required"
        )
    result = _git(root, ["apply", "--reverse", "--whitespace=error", "-"], patch=patch)
    if _git_head(root) != initial_head:
        raise RuntimeError(
            "Git HEAD changed while the patch was being reverted; recovery status: "
            "manual_intervention_required. Inspect the worktree immediately."
        )
    if result.returncode != 0:
        raise RuntimeError(f"Patch reversal failed: {result.stderr.strip()[:500]}")
    def mark_reverted_and_audited() -> None:
        if transaction is not None:
            transaction.update(
                state="reverted_and_audited",
                updated_at=time.time(),
                recovery="verified",
            )
            _write_transaction_journal(root, proposal_id, transaction)

    def restore_applied_journal() -> None:
        if transaction is not None:
            transaction.update(
                state="applied_and_audited",
                updated_at=time.time(),
                recovery="verified",
            )
            _write_transaction_journal(root, proposal_id, transaction)

    after_status = _tracked_status(root)
    if not after_status:
        reverted_target_state = _target_state_snapshot(root, targets)
        try:
            append_audit_event(
                root,
                "proposal_reverted",
                proposal_id,
                {
                    "files": "tracked patch targets",
                    "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                    "recovery_status": "not_needed",
                },
            )
        except Exception as exc:
            # Reapply the exact patch so an audit failure does not silently leave
            # a reversal that the caller believes was recorded.
            forward_check = _git(root, ["apply", "--check", "--whitespace=error", "-"], patch=patch)
            if forward_check.returncode != 0:
                raise RuntimeError(
                    "Reversal audit logging failed and forward recovery is unsafe. "
                    "Recovery status: manual_intervention_required."
                ) from exc
            forward = _git(root, ["apply", "--whitespace=error", "-"], patch=patch)
            if (
                forward.returncode != 0
                or _tracked_status(root) != before_status
                or _git_head(root) != initial_head
                or _target_state_snapshot(root, targets) != baseline_target_state
                or hashlib.sha256(
                    _read_regular_file(
                        proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal"
                    )
                ).hexdigest() != patch_digest
            ):
                raise RuntimeError(
                    "Reversal audit logging failed and recovery could not be verified. "
                    "Recovery status: manual_intervention_required."
                ) from exc
            restore_applied_journal()
            raise RuntimeError(
                "Reversal audit logging failed; original patch was restored"
            ) from exc
        current_proposal = _read_regular_file(
            proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal"
        )
        if (
            _git_head(root) != initial_head
            or _tracked_status(root)
            or _target_state_snapshot(root, targets) != reverted_target_state
            or hashlib.sha256(current_proposal).hexdigest() != patch_digest
        ):
            raise RuntimeError(
                "Repository or patch changed during reversal audit persistence; "
                "transaction remains non-terminal. "
                "Recovery status: manual_intervention_required."
            )
        mark_reverted_and_audited()
        # Verify once more after the terminal journal write. If an external
        # writer raced with that persistence, downgrade the journal for recovery.
        final_proposal = _read_regular_file(
            proposal, max_bytes=_MAX_PATCH_BYTES, label="Patch proposal"
        )
        try:
            final_state_valid = (
                _git_head(root) == initial_head
                and not _tracked_status(root)
                and _target_state_snapshot(root, targets) == reverted_target_state
                and hashlib.sha256(final_proposal).hexdigest() == patch_digest
            )
        except Exception:
            final_state_valid = False
        if not final_state_valid:
            if transaction is not None:
                transaction.update(
                    state="reverting",
                    updated_at=time.time(),
                    recovery="pending_verification",
                    reason="Repository changed during terminal journal persistence",
                )
                _write_transaction_journal(root, proposal_id, transaction)
            raise RuntimeError(
                "Repository changed during terminal journal persistence; transaction "
                "was returned to a non-terminal state. "
                "Recovery status: manual_intervention_required."
            )
        return {
            "proposal_id": proposal_id,
            "status": "reverted",
            "files": "tracked patch targets",
            "transaction": "reverted_and_audited",
            "recovery_status": "verified",
        }



def apply_proposal(
    workspace: Path | str,
    proposal_id: str,
    *,
    confirm: bool = False,
    require_audit_gate: bool = False,
) -> dict[str, str]:
    """Apply a proposal under the per-workspace AURIX operation lock."""
    if not confirm:
        raise PermissionError("Explicit confirmation is required to apply a patch")
    root = Path(workspace).expanduser().resolve()
    with _workspace_operation_lock(root):
        return _apply_proposal_locked(
            root, proposal_id, confirm=confirm, require_audit_gate=require_audit_gate
        )


def revert_proposal(
    workspace: Path | str, proposal_id: str, *, confirm: bool = False
) -> dict[str, str]:
    """Revert a proposal under the per-workspace AURIX operation lock."""
    if not confirm:
        raise PermissionError("Explicit confirmation is required to revert a patch")
    root = Path(workspace).expanduser().resolve()
    with _workspace_operation_lock(root):
        return _revert_proposal_locked(root, proposal_id, confirm=confirm)
