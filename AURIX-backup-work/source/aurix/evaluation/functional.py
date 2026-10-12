"""Functional patch evaluation against disposable, known-defect fixtures.

This evaluates a supplied candidate diff; it does not ask a model to create one.
The fixture and patch must be operator-reviewed. Trusted mode is not an OS sandbox.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from aurix import __version__
from aurix.tools.execution import IsolationMode, run_test_suite

_MAX_CASES = 100
_MAX_PATCH_BYTES = 1_000_000


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def load_functional_suite(path: str | Path) -> tuple[Path, list[dict[str, Any]]]:
    """Load a JSON suite; fixture and patch paths must remain beneath suite directory."""
    suite_file = Path(path).expanduser().resolve(strict=True)
    if not suite_file.is_file():
        raise ValueError("Functional suite must be a JSON file")
    root = suite_file.parent.resolve(strict=True)
    try:
        payload = json.loads(suite_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid functional suite JSON: {exc}") from exc
    if not isinstance(payload, list) or not payload or len(payload) > _MAX_CASES:
        raise ValueError(f"Functional suite must contain 1-{_MAX_CASES} cases")
    seen: set[str] = set()
    validated = []
    for index, case in enumerate(payload):
        if not isinstance(case, dict):
            raise ValueError(f"Case {index} must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError(f"Case {index} requires a unique non-empty id")
        seen.add(case_id)
        if case.get("suite", "pytest") != "pytest":
            raise ValueError(f"Case {case_id}: only fixed pytest execution is supported")
        if not isinstance(case.get("expect_baseline_passed"), bool) or not isinstance(case.get("expect_candidate_passed"), bool):
            raise ValueError(f"Case {case_id}: expected baseline/candidate outcomes must be booleans")
        resolved: dict[str, str] = {}
        for field in ("fixture", "patch"):
            value = case.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Case {case_id}: {field} must be a relative path")
            relative = Path(value)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Case {case_id}: {field} must be a relative path inside the suite directory")
            raw = root / relative
            if raw.is_symlink():
                raise ValueError(f"Case {case_id}: {field} must not be a symlink")
            try:
                target = raw.resolve(strict=True)
            except OSError as exc:
                raise ValueError(f"Case {case_id}: {field} path does not exist") from exc
            if not _inside(target, root):
                raise ValueError(f"Case {case_id}: {field} must resolve inside the suite directory")
            if field == "fixture" and not target.is_dir():
                raise ValueError(f"Case {case_id}: fixture must be a directory")
            if field == "patch" and not target.is_file():
                raise ValueError(f"Case {case_id}: patch must be a file")
            if field == "patch" and target.stat().st_size > _MAX_PATCH_BYTES:
                raise ValueError(f"Case {case_id}: patch exceeds {_MAX_PATCH_BYTES} bytes")
            resolved[field] = str(target)
        if any(path.is_symlink() for path in Path(resolved["fixture"]).rglob("*")):
            raise ValueError(f"Case {case_id}: fixture contains symlinks; refusing to load it")
        validated.append({**case, **resolved, "suite": "pytest"})
    return root, validated


def _check_patch_paths(patch: str, fixture: Path) -> None:
    if any(line.startswith(("new file mode ", "deleted file mode ", "old mode ", "new mode ",
                           "rename from ", "rename to ", "GIT binary patch", "Binary files "))
           for line in patch.splitlines()):
        raise ValueError("Patch may only modify contents of existing regular files")
    old_paths: list[str] = []
    new_paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith(("--- ", "+++ ")):
            is_old = line.startswith("--- ")
            value = line[4:].split("\t", 1)[0].strip()
            if value == "/dev/null":
                raise ValueError("Patch additions and deletions are unsupported; modify existing files only")
            expected_prefix = "a/" if is_old else "b/"
            if not value.startswith(expected_prefix):
                raise ValueError("Patch contains an unexpected file header")
            value = value[2:]
            pure = PurePosixPath(value)
            if pure.is_absolute() or ".." in pure.parts or not pure.parts:
                raise ValueError("Patch contains an unsafe file path")
            (old_paths if is_old else new_paths).append(str(pure))
    if not old_paths or old_paths != new_paths:
        raise ValueError("Patch must contain matching old/new paths for existing-file modifications")
    for rel in set(old_paths):
        target = fixture.joinpath(*PurePosixPath(rel).parts)
        if not target.exists() or target.is_symlink() or not target.is_file():
            raise ValueError(f"Patch target must be an existing regular fixture file: {rel}")


def run_functional_benchmark(
    suite_path: str | Path,
    *,
    confirm: bool = False,
    timeout_seconds: int = 120,
    isolation: IsolationMode = "trusted",
    sandbox_image: str | None = None,
) -> dict[str, Any]:
    """Run baseline and candidate pytest in separate disposable fixture copies."""
    if not confirm:
        raise PermissionError("Explicit confirmation is required to run a functional benchmark")
    if isolation not in {"trusted", "docker"}:
        raise ValueError("Unsupported isolation mode")
    root, cases = load_functional_suite(suite_path)
    normalized_cases = [{
        "id": case["id"], "fixture": Path(case["fixture"]).relative_to(root).as_posix(),
        "patch": Path(case["patch"]).relative_to(root).as_posix(), "suite": case["suite"],
        "expect_baseline_passed": case["expect_baseline_passed"],
        "expect_candidate_passed": case["expect_candidate_passed"],
    } for case in cases]
    suite_payload = json.dumps(normalized_cases, sort_keys=True, separators=(",", ":")).encode()
    suite_digest = hashlib.sha256(suite_payload).hexdigest()
    results: list[dict[str, Any]] = []
    started_all = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="aurix-functional-") as temp:
        temp_root = Path(temp)
        for case in cases:
            fixture = Path(case["fixture"])
            patch_file = Path(case["patch"])
            patch = patch_file.read_text(encoding="utf-8")
            _check_patch_paths(patch, fixture)
            baseline_copy = temp_root / f"{case['id']}-baseline"
            candidate_copy = temp_root / f"{case['id']}-candidate"
            shutil.copytree(fixture, baseline_copy, symlinks=False, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "venv"))
            shutil.copytree(fixture, candidate_copy, symlinks=False, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "venv"))
            # Recheck after copying; no symlink should be present in the execution tree.
            if any(path.is_symlink() for path in candidate_copy.rglob("*")):
                raise ValueError(f"Case {case['id']}: fixture contains symlinks; refusing execution")
            baseline = run_test_suite(baseline_copy, "pytest", confirm=True, timeout_seconds=timeout_seconds,
                                      isolation=isolation, sandbox_image=sandbox_image)
            preflight = subprocess.run(["git", "apply", "--check", "--whitespace=error", "-"], cwd=candidate_copy,
                                       input=patch, text=True, encoding="utf-8", errors="replace", capture_output=True,
                                       timeout=min(max(1, timeout_seconds), 30), shell=False, check=False)
            if preflight.returncode != 0:
                results.append({"id": case["id"], "status": "invalid_patch", "passed": False,
                                "baseline": baseline, "patch_error": preflight.stderr[-4000:]})
                continue
            applied = subprocess.run(["git", "apply", "--whitespace=error", "-"], cwd=candidate_copy,
                                     input=patch, text=True, encoding="utf-8", errors="replace", capture_output=True,
                                     timeout=min(max(1, timeout_seconds), 30), shell=False, check=False)
            if applied.returncode != 0:
                results.append({"id": case["id"], "status": "apply_failed", "passed": False,
                                "baseline": baseline, "patch_error": applied.stderr[-4000:]})
                continue
            candidate = run_test_suite(candidate_copy, "pytest", confirm=True, timeout_seconds=timeout_seconds,
                                       isolation=isolation, sandbox_image=sandbox_image)
            baseline_matches = baseline["passed"] is case["expect_baseline_passed"]
            candidate_matches = candidate["passed"] is case["expect_candidate_passed"]
            intended_fix = (not case["expect_baseline_passed"] and case["expect_candidate_passed"]
                            and not baseline["passed"] and candidate["passed"])
            results.append({"id": case["id"], "status": "passed" if baseline_matches and candidate_matches else "failed",
                            "passed": baseline_matches and candidate_matches, "baseline_matches_expectation": baseline_matches,
                            "candidate_matches_expectation": candidate_matches, "demonstrated_fix": intended_fix,
                            "baseline": baseline, "candidate": candidate,
                            "patch_sha256": hashlib.sha256(patch.encode()).hexdigest()})
    passed = sum(item["passed"] for item in results)
    return {
        "schema_version": 1,
        "metadata": {"created_at": datetime.now(timezone.utc).isoformat(), "aurix_version": __version__,
                      "python_version": __import__("platform").python_version(), "suite_sha256": suite_digest,
                      "isolation": isolation, "sandbox_image": sandbox_image if isolation == "docker" else None},
        "cases": len(cases), "passed": passed, "failed": len(cases) - passed,
        "pass_rate": round(passed / len(cases), 4),
        "demonstrated_fixes": sum(bool(item.get("demonstrated_fix")) for item in results),
        "duration_ms": round((time.perf_counter() - started_all) * 1000, 2), "results": results,
        "limitations": ["Evaluates supplied patches, not autonomous patch generation.",
                        "Passing tests do not prove semantic correctness beyond test coverage.",
                        "Trusted mode is not an OS sandbox; use a reviewed Docker image for untrusted fixtures.",
                        "Fixtures and patches must be reviewed before execution."],
    }
