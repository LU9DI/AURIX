"""Autonomous patch-generation benchmark with disposable fixture workspaces.

The model generates a proposal through the normal Orchestrator protocol. The
proposal is then applied only to a disposable candidate copy and evaluated with
fixed pytest execution. This is not a sandbox unless Docker isolation is chosen.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from aurix import __version__
from aurix.evaluation.functional import _check_patch_paths
from aurix.orchestrator import Orchestrator
from aurix.providers.base import Provider
from aurix.telemetry import JSONLTelemetry
from aurix.tools.execution import IsolationMode, run_test_suite

_MAX_CASES = 50
_IGNORES = shutil.ignore_patterns(".git", ".aurix", "__pycache__", ".pytest_cache", ".venv", "venv")


def _timings(
    case_started: float,
    baseline: dict[str, Any],
    agent_started: float,
    candidate: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Record the observable cost of one task, including failed proposals."""
    timing = {
        "baseline_test_ms": float(baseline.get("duration_ms", 0.0)),
        "agent_ms": round((time.perf_counter() - agent_started) * 1000, 2),
        "total_ms": round((time.perf_counter() - case_started) * 1000, 2),
    }
    if candidate is not None:
        timing["candidate_test_ms"] = float(candidate.get("duration_ms", 0.0))
    return timing


def _generation_settings(provider: Provider) -> dict[str, Any]:
    """Report determinism settings, including explicit non-support."""

    getter = getattr(provider, "generation_settings", None)
    if callable(getter):
        try:
            settings = getter()
        except (TypeError, ValueError, RuntimeError):
            settings = None
        if isinstance(settings, dict):
            return settings
    return {
        "temperature": None,
        "seed": None,
        "supported": {"temperature": False, "seed": False},
        "note": "provider does not expose sampling settings",
    }


def _patch_targets(patch: str) -> list[str]:
    """Return the paths named by the old-side headers of a validated unified diff."""
    targets: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("--- "):
            continue
        value = line[4:].split("\t", 1)[0].strip()
        if value.startswith("a/"):
            value = value[2:]
        targets.append(value)
    return targets


def load_autonomous_suite(path: str | Path) -> tuple[Path, list[dict[str, Any]]]:
    suite_file = Path(path).expanduser().resolve(strict=True)
    if not suite_file.is_file():
        raise ValueError("Autonomous benchmark suite must be a JSON file")
    root = suite_file.parent.resolve(strict=True)
    try:
        payload = json.loads(suite_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid autonomous benchmark JSON: {exc}") from exc
    if not isinstance(payload, list) or not payload or len(payload) > _MAX_CASES:
        raise ValueError(f"Autonomous benchmark must contain 1-{_MAX_CASES} cases")
    seen: set[str] = set()
    cases: list[dict[str, Any]] = []
    for i, case in enumerate(payload):
        if not isinstance(case, dict):
            raise ValueError(f"Case {i} must be an object")
        case_id, fixture, task = case.get("id"), case.get("fixture"), case.get("task")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError(f"Case {i} requires a unique non-empty id")
        seen.add(case_id)
        if not isinstance(task, str) or not task.strip() or len(task) > 12000:
            raise ValueError(f"Case {case_id}: task must be non-empty and at most 12000 characters")
        if not isinstance(fixture, str) or not fixture.strip():
            raise ValueError(f"Case {case_id}: fixture must be a relative directory")
        relative = Path(fixture)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Case {case_id}: fixture must remain inside the suite directory")
        raw = root / relative
        if raw.is_symlink():
            raise ValueError(f"Case {case_id}: fixture must not be a symlink")
        resolved = raw.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Case {case_id}: fixture resolves outside suite directory") from exc
        if not resolved.is_dir() or any(p.is_symlink() for p in resolved.rglob("*")):
            raise ValueError(f"Case {case_id}: fixture must be a directory without symlinks")
        if not isinstance(case.get("expect_baseline_passed", False), bool):
            raise ValueError(f"Case {case_id}: expect_baseline_passed must be boolean")
        if not isinstance(case.get("expect_candidate_passed", True), bool):
            raise ValueError(f"Case {case_id}: expect_candidate_passed must be boolean")
        allowed = case.get("allowed_patch_paths")
        normalized_allowed: list[str] | None = None
        if allowed is not None:
            if not isinstance(allowed, list) or not allowed or len(allowed) > 20:
                raise ValueError(
                    f"Case {case_id}: allowed_patch_paths must be a non-empty list of paths"
                )
            normalized_allowed = []
            for raw_path in allowed:
                if not isinstance(raw_path, str) or not raw_path.strip():
                    raise ValueError(
                        f"Case {case_id}: allowed_patch_paths entries must be non-empty strings"
                    )
                relative_path = PurePosixPath(raw_path)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise ValueError(
                        f"Case {case_id}: allowed patch path must remain inside the fixture"
                    )
                target = resolved.joinpath(*relative_path.parts)
                if not target.is_file() or target.is_symlink():
                    raise ValueError(
                        f"Case {case_id}: allowed patch path must be an existing regular file"
                    )
                normalized_allowed.append(str(relative_path))
        cases.append(
            {
                "id": case_id,
                "fixture": str(resolved),
                "task": task,
                "expect_baseline_passed": case.get("expect_baseline_passed", False),
                "expect_candidate_passed": case.get("expect_candidate_passed", True),
                "allowed_patch_paths": normalized_allowed,
            }
        )
    return root, cases


def run_autonomous_benchmark(
    suite_path: str | Path,
    provider: Provider,
    *,
    confirm: bool = False,
    timeout_seconds: int = 60,
    max_steps: int = 8,
    isolation: IsolationMode = "trusted",
    sandbox_image: str | None = None,
) -> dict[str, Any]:
    """Ask the configured model to generate a patch, then test it in a disposable copy."""
    if not confirm:
        raise PermissionError("Explicit confirmation is required to run an autonomous benchmark")
    if isolation not in {"trusted", "docker"}:
        raise ValueError("Unsupported isolation mode")
    if isolation == "docker" and not sandbox_image:
        raise ValueError("Docker isolation requires a locally available, operator-reviewed image")
    if isolation == "trusted" and sandbox_image is not None:
        raise ValueError("sandbox_image requires Docker isolation")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= 120
    ):
        raise ValueError("timeout_seconds must be an integer between 1 and 120")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 2 <= max_steps <= 20:
        raise ValueError("max_steps must be an integer between 2 and 20")
    root, cases = load_autonomous_suite(suite_path)
    normalized = [
        {
            "id": c["id"],
            "fixture": Path(c["fixture"]).relative_to(root).as_posix(),
            "task": c["task"],
            "expect_baseline_passed": c["expect_baseline_passed"],
            "expect_candidate_passed": c["expect_candidate_passed"],
            "allowed_patch_paths": c["allowed_patch_paths"],
        }
        for c in cases
    ]
    suite_digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="aurix-autonomous-") as temp:
        temp_root = Path(temp)
        for case in cases:
            case_started = time.perf_counter()
            fixture = Path(case["fixture"])
            baseline_copy = temp_root / f"{case['id']}-baseline"
            candidate_copy = temp_root / f"{case['id']}-candidate"
            shutil.copytree(fixture, baseline_copy, symlinks=False, ignore=_IGNORES)
            shutil.copytree(fixture, candidate_copy, symlinks=False, ignore=_IGNORES)
            baseline = run_test_suite(
                baseline_copy,
                "pytest",
                confirm=True,
                timeout_seconds=timeout_seconds,
                isolation=isolation,
                sandbox_image=sandbox_image,
            )
            task = (
                case["task"].strip()
                + "\n\n"
                + "Benchmark contract: inspect the relevant source and tests, then create exactly one "
                "reviewable unified-diff proposal with propose_patch. Do not claim tests passed; "
                "do not attempt shell commands or apply changes. Modify existing regular files only."
            )
            orchestrator = Orchestrator(
                provider,
                max_steps=max_steps,
                workspace=candidate_copy,
                telemetry=JSONLTelemetry(candidate_copy / ".aurix" / "runs.jsonl"),
                allow_agent_verification=False,
            )
            agent_started = time.perf_counter()
            agent = orchestrator.run(task)
            proposal_ids = [
                entry.get("proposal_id")
                for entry in agent.trace
                if isinstance(entry.get("proposal_id"), str)
            ]
            unique_ids = list(dict.fromkeys(proposal_ids))
            if agent.status != "completed" or len(unique_ids) != 1:
                results.append(
                    {
                        "id": case["id"],
                        "status": "no_unique_proposal",
                        "passed": False,
                        "baseline": baseline,
                        "agent": {
                            "status": agent.status,
                            "message": agent.message,
                            "steps": agent.steps,
                            "trace": agent.trace,
                        },
                        "proposal_count": len(unique_ids),
                        "timings_ms": _timings(case_started, baseline, agent_started),
                    }
                )
                continue
            proposal_id = unique_ids[0]
            proposal_path = candidate_copy / ".aurix" / "proposals" / f"{proposal_id}.diff"
            if proposal_path.is_symlink() or not proposal_path.is_file():
                results.append(
                    {
                        "id": case["id"],
                        "status": "proposal_missing",
                        "passed": False,
                        "baseline": baseline,
                        "proposal_id": proposal_id,
                        "timings_ms": _timings(case_started, baseline, agent_started),
                    }
                )
                continue
            patch = proposal_path.read_text(encoding="utf-8")
            try:
                _check_patch_paths(patch, candidate_copy)
                allowed_paths = case.get("allowed_patch_paths")
                if allowed_paths is not None:
                    modified_paths = set(_patch_targets(patch))
                    disallowed = sorted(modified_paths - set(allowed_paths))
                    if disallowed:
                        raise ValueError(
                            "Patch modifies files outside the declared allowed set: "
                            + ", ".join(disallowed)
                        )
                preflight = subprocess.run(
                    ["git", "apply", "--check", "--whitespace=error", "-"],
                    cwd=candidate_copy,
                    input=patch,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=10,
                    shell=False,
                    check=False,
                )
            except (ValueError, PermissionError, OSError, subprocess.TimeoutExpired) as exc:
                results.append(
                    {
                        "id": case["id"],
                        "status": "invalid_patch",
                        "passed": False,
                        "baseline": baseline,
                        "proposal_id": proposal_id,
                        "patch_error": f"{type(exc).__name__}: {exc}",
                        "timings_ms": _timings(case_started, baseline, agent_started),
                    }
                )
                continue
            if preflight.returncode != 0:
                results.append(
                    {
                        "id": case["id"],
                        "status": "invalid_patch",
                        "passed": False,
                        "baseline": baseline,
                        "proposal_id": proposal_id,
                        "patch_error": preflight.stderr[-3000:],
                        "timings_ms": _timings(case_started, baseline, agent_started),
                    }
                )
                continue
            applied = subprocess.run(
                ["git", "apply", "--whitespace=error", "-"],
                cwd=candidate_copy,
                input=patch,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=10,
                shell=False,
                check=False,
            )
            if applied.returncode != 0:
                results.append(
                    {
                        "id": case["id"],
                        "status": "apply_failed",
                        "passed": False,
                        "baseline": baseline,
                        "proposal_id": proposal_id,
                        "patch_error": applied.stderr[-3000:],
                        "timings_ms": _timings(case_started, baseline, agent_started),
                    }
                )
                continue
            candidate = run_test_suite(
                candidate_copy,
                "pytest",
                confirm=True,
                timeout_seconds=timeout_seconds,
                isolation=isolation,
                sandbox_image=sandbox_image,
            )
            baseline_matches = baseline["passed"] is case["expect_baseline_passed"]
            candidate_matches = candidate["passed"] is case["expect_candidate_passed"]
            demonstrated_fix = (
                not baseline["passed"]
                and candidate["passed"]
                and not case["expect_baseline_passed"]
                and case["expect_candidate_passed"]
            )
            passed = baseline_matches and candidate_matches and agent.status == "completed"
            results.append(
                {
                    "id": case["id"],
                    "status": "passed" if passed else "failed",
                    "passed": passed,
                    "proposal_id": proposal_id,
                    "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                    "baseline_matches_expectation": baseline_matches,
                    "candidate_matches_expectation": candidate_matches,
                    "demonstrated_fix": demonstrated_fix,
                    "baseline": baseline,
                    "candidate": candidate,
                    "agent": {
                        "status": agent.status,
                        "message": agent.message,
                        "steps": agent.steps,
                        "trace": agent.trace,
                    },
                    "timings_ms": _timings(case_started, baseline, agent_started, candidate),
                }
            )
    passed_count = sum(bool(item.get("passed")) for item in results)
    return {
        "schema_version": 1,
        "benchmark": "autonomous-patch-v1",
        "metadata": {
            "created_at": datetime.now(UTC).isoformat(),
            "aurix_version": __version__,
            "python_version": __import__("platform").python_version(),
            "suite_sha256": suite_digest,
            "isolation": isolation,
            "sandbox_image": sandbox_image if isolation == "docker" else None,
            "provider_class": f"{type(provider).__module__}.{type(provider).__qualname__}",
            "generation_settings": _generation_settings(provider),
        },
        "cases": len(cases),
        "passed": passed_count,
        "failed": len(cases) - passed_count,
        "pass_rate": round(passed_count / len(cases), 4),
        "demonstrated_fixes": sum(bool(item.get("demonstrated_fix")) for item in results),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "results": results,
        "limitations": [
            "Model patch generation is autonomous only within the configured provider's response.",
            "Protocol repair is bounded to one additional model call and never replaces patch validation.",
            "Raw responses are not stored in this report; opt-in redacted diagnostics use a temporary directory.",
            "Passing tests prove only behavior covered by those tests.",
            "Trusted execution is not an OS sandbox; use a reviewed local Docker image for untrusted code.",
            "Each task is evaluated once; repeat runs to estimate variance.",
        ],
    }
