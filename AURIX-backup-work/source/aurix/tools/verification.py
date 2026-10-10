"""Verify a reviewed patch in a disposable Git worktree.

This keeps the user's primary checkout unchanged, but test code is still not
sandboxed from the operating system. Only use this for trusted repositories.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import hashlib
import json
import platform
import re
import uuid
from pathlib import Path
from typing import Literal

from aurix.tools.execution import IsolationMode, run_test_suite
from aurix.tools.patches import _git, _proposal_path, _validate_patch
from aurix.tools.provenance import append_audit_event

VerifySuite = Literal["pytest", "ruff", "auto"]


def verify_proposal(
    workspace: Path | str,
    proposal_id: str,
    *,
    confirm: bool = False,
    suite: VerifySuite = "pytest",
    timeout_seconds: int = 120,
    compare_baseline: bool = True,
    isolation: IsolationMode = "trusted",
    sandbox_image: str | None = None,
    audit_id: str | None = None,
    target_state_sha256: str | None = None,
) -> dict[str, object]:
    """Apply a proposal to a temporary detached worktree and run a fixed suite.

    The main checkout is not modified. This is isolation from the primary
    checkout, not an OS-level sandbox: tests may still access available OS
    resources and the network.
    """
    if not confirm:
        raise PermissionError("Explicit confirmation is required to verify a patch")
    if suite not in {"pytest", "ruff", "auto"}:
        raise ValueError("Unsupported verification suite; choose 'pytest', 'ruff', or 'auto'")

    if audit_id is None:
        audit_id = uuid.uuid4().hex
    if not isinstance(audit_id, str) or len(audit_id) != 32 or any(c not in "0123456789abcdef" for c in audit_id):
        raise ValueError("audit_id must be a 32-character lowercase hexadecimal identifier")
    verification_id = uuid.uuid4().hex
    if target_state_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", target_state_sha256):
        raise ValueError("target_state_sha256 must be a 64-character lowercase hexadecimal digest")
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be a directory")
    proposal = _proposal_path(root, proposal_id)
    patch_bytes = proposal.read_bytes()
    patch_digest = hashlib.sha256(patch_bytes).hexdigest()
    patch = patch_bytes.decode("utf-8")
    targets = _validate_patch(root, patch)
    requested_suite = suite
    test_paths: list[str] | None = None
    selection = {"mode": "full_suite", "reason": "Explicit full suite requested" if suite == "pytest" else
                 ("Explicit lint suite requested" if suite == "ruff" else "Automatic selection not yet evaluated"),
                 "paths": [], "manifest_sha256": None}
    test_map_digest: str | None = None
    if suite == "auto":
        suite = "pytest"
        manifest_path = root / ".aurix" / "test-map.json"
        try:
            if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 100_000:
                raise ValueError("No valid explicit test map")
            manifest_bytes = manifest_path.read_bytes()
            test_map_digest = hashlib.sha256(manifest_bytes).hexdigest()
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            mappings = manifest.get("mappings") if isinstance(manifest, dict) and manifest.get("version") == 1 else None
            if not isinstance(mappings, dict):
                raise ValueError("Invalid test map schema")
            selected: set[str] = set()
            for target in targets:
                mapped = mappings.get(target)
                if not isinstance(mapped, list) or not mapped:
                    raise ValueError(f"No explicit test mapping for {target}")
                for relative in mapped:
                    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative:
                        raise ValueError("Unsafe test-map path")
                    candidate = root / relative
                    if candidate.is_symlink() or not candidate.is_file() or root not in candidate.resolve().parents:
                        raise ValueError(f"Mapped test is missing or unsafe: {relative}")
                    if not relative.startswith("tests/") or not relative.endswith(".py"):
                        raise ValueError(f"Mapped target is not a test file: {relative}")
                    selected.add(relative)
            if selected:
                test_paths = sorted(selected)
                selection = {"mode": "mapped_subset", "reason": "Every changed target has an explicit valid .aurix/test-map.json mapping", "paths": test_paths, "manifest_sha256": test_map_digest}
            else:
                selection = {"mode": "full_suite", "reason": "No mapped tests; conservative fallback", "paths": []}
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, AttributeError) as exc:
            selection = {"mode": "full_suite", "reason": f"Conservative fallback: {str(exc)[:180]}", "paths": [], "manifest_sha256": test_map_digest}

    top = _git(root, ["rev-parse", "--show-toplevel"])
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
        raise ValueError("Workspace must be the Git repository root")
    head_result = _git(root, ["rev-parse", "HEAD"])
    if head_result.returncode != 0:
        raise RuntimeError("Could not identify verification base commit")
    base_commit = head_result.stdout.strip()
    status = _git(root, ["status", "--porcelain", "--untracked-files=no"])
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip() or "Could not inspect Git status")
    if status.stdout.strip():
        raise PermissionError("Git worktree has tracked changes; commit or stash them before verification")

    if not isinstance(compare_baseline, bool):
        raise ValueError("compare_baseline must be a boolean")

    with tempfile.TemporaryDirectory(prefix="aurix-verify-") as temp_parent:
        worktree = Path(temp_parent) / "checkout"
        added = _git(root, ["worktree", "add", "--detach", str(worktree), "HEAD"])
        if added.returncode != 0:
            raise RuntimeError(f"Could not create disposable Git worktree: {added.stderr.strip()[:500]}")
        try:
            baseline_result = None
            if compare_baseline:
                baseline_result = run_test_suite(
                    worktree, suite, confirm=True, timeout_seconds=timeout_seconds,
                    isolation=isolation, sandbox_image=sandbox_image, test_paths=test_paths,
                )
            checked = _git(worktree, ["apply", "--check", "--whitespace=error", "-"], patch=patch)
            if checked.returncode != 0:
                raise ValueError(f"Patch preflight failed in disposable worktree: {checked.stderr.strip()[:500]}")
            applied = _git(worktree, ["apply", "--whitespace=error", "-"], patch=patch)
            if applied.returncode != 0:
                raise RuntimeError(f"Could not apply patch in disposable worktree: {applied.stderr.strip()[:500]}")
            test_result = run_test_suite(
                worktree, suite, confirm=True, timeout_seconds=timeout_seconds,
                isolation=isolation, sandbox_image=sandbox_image, test_paths=test_paths,
            )
            if baseline_result is None:
                regression_status = "not_compared"
            elif baseline_result["passed"] and test_result["passed"]:
                regression_status = "clean"
            elif baseline_result["passed"] and not test_result["passed"]:
                regression_status = "introduced_failure"
            elif not baseline_result["passed"] and test_result["passed"]:
                regression_status = "improved"
            else:
                regression_status = "preexisting_failure_persists"
            # Bind test evidence to the exact proposal bytes and repository revision.
            if test_map_digest is not None:
                manifest_path = root / ".aurix" / "test-map.json"
                if manifest_path.is_symlink() or not manifest_path.is_file() or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != test_map_digest:
                    raise PermissionError("Test map changed during verification; refusing stale test evidence")
            if hashlib.sha256(proposal.read_bytes()).hexdigest() != patch_digest:
                raise PermissionError("Proposal changed during verification; refusing stale test evidence")
            if _git(root, ["rev-parse", "HEAD"]).stdout.strip() != base_commit:
                raise PermissionError("Repository HEAD changed during verification; refusing stale evidence")
            evidence = {
                "audit_id": audit_id,
                "verification_id": verification_id,
                "proposal_id": proposal_id,
                "proposal_sha256": patch_digest,
                "base_commit": base_commit,
                "target_state_sha256": target_state_sha256,
                "suite": suite,
                "requested_suite": requested_suite,
                "test_selection": selection,
                "isolation": isolation,
                "sandbox_image": sandbox_image if isolation == "docker" else None,
                "sandbox_image_id": (test_result.get("sandbox_image_id") if isolation == "docker" else None),
                "runtime_fingerprint": {
                    "python_version": platform.python_version(),
                    "python_implementation": platform.python_implementation(),
                    "system": platform.system(),
                    "release": platform.release(),
                    "machine": platform.machine(),
                },
                "baseline_result": baseline_result,
                "test_result": test_result,
                "regression_status": regression_status,
            }
            evidence_sha256 = hashlib.sha256(json.dumps(
                evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")).hexdigest()
            result = {
                **evidence,
                "status": "verified_pass" if test_result["passed"] else "verified_fail",
                "targets": targets,
                "primary_workspace_modified": False,
                "evidence_sha256": evidence_sha256,
                "security_note": (
                    "Tests ran in Docker isolation; review the image and daemon trust boundary."
                    if isolation == "docker" else
                    "Tests ran in a disposable Git worktree, not an OS sandbox. "
                    "Only verify patches from repositories you trust."
                ),
            }
            append_audit_event(root, "proposal_verified", proposal_id, {
                "audit_id": audit_id, "verification_id": verification_id,
                "suite": suite, "requested_suite": requested_suite, "status": result["status"],
                "regression_status": regression_status, "isolation": isolation,
            })
            return result
        finally:
            removed = _git(root, ["worktree", "remove", "--force", str(worktree)])
            if removed.returncode != 0:
                _git(root, ["worktree", "prune"])
                shutil.rmtree(worktree, ignore_errors=True)
