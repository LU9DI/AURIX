from __future__ import annotations

import hashlib
import json
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aurix import __version__
from aurix.orchestrator import Orchestrator
from aurix.telemetry import estimate_tokens

_STRING_LIST_FIELDS = (
    "must_contain",
    "must_not_contain",
    "required_tools",
    "forbidden_tools",
    "expected_regression_statuses",
)
_MAX_REPETITIONS = 10


def _validate_case(case: Any, index: int) -> dict[str, Any]:
    if (
        not isinstance(case, dict)
        or not isinstance(case.get("task"), str)
        or not case["task"].strip()
    ):
        raise ValueError(f"Benchmark case {index} requires a non-empty task")
    for field in _STRING_LIST_FIELDS:
        value = case.get(field, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ValueError(f"Benchmark case {index}: {field} must be a list of non-empty strings")
    for field in ("min_steps", "max_steps"):
        if field in case and (
            isinstance(case[field], bool) or not isinstance(case[field], int) or case[field] < 0
        ):
            raise ValueError(f"Benchmark case {index}: {field} must be a non-negative integer")
    if "min_steps" in case and "max_steps" in case and case["min_steps"] > case["max_steps"]:
        raise ValueError(f"Benchmark case {index}: min_steps cannot exceed max_steps")
    if "expected_status" in case and (
        not isinstance(case["expected_status"], str) or not case["expected_status"].strip()
    ):
        raise ValueError(f"Benchmark case {index}: expected_status must be a non-empty string")
    for field in ("require_patch_proposal", "require_successful_verification"):
        if field in case and not isinstance(case[field], bool):
            raise ValueError(f"Benchmark case {index}: {field} must be a boolean")
    if "context" in case and not isinstance(case["context"], str):
        raise ValueError(f"Benchmark case {index}: context must be a string")
    if "id" in case and (not isinstance(case["id"], str) or not case["id"].strip()):
        raise ValueError(f"Benchmark case {index}: id must be a non-empty string")
    return case


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate a non-empty JSON benchmark suite."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid benchmark JSON: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("Benchmark must be a non-empty JSON array")
    return [_validate_case(case, index) for index, case in enumerate(payload)]


def run_benchmark(
    orchestrator: Orchestrator,
    cases: list[dict[str, Any]],
    *,
    repetitions: int = 1,
) -> dict[str, Any]:
    """Run acceptance checks repeatedly and report stability/latency aggregates.

    This is a deterministic criteria runner, not a semantic software-quality score.
    Repetitions can trigger repeated provider calls and corresponding compute/API costs.
    """
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark cases must be a non-empty list")
    if (
        isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or not 1 <= repetitions <= _MAX_REPETITIONS
    ):
        raise ValueError(f"repetitions must be an integer between 1 and {_MAX_REPETITIONS}")
    validated = [_validate_case(case, index) for index, case in enumerate(cases)]
    case_ids = [case.get("id", f"case-{index + 1}") for index, case in enumerate(validated)]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Duplicate benchmark case id")

    suite_bytes = json.dumps(
        validated, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    suite_sha256 = hashlib.sha256(suite_bytes).hexdigest()
    results: list[dict[str, Any]] = []
    per_case: list[dict[str, Any]] = []
    for index, case in enumerate(validated):
        case_id = case_ids[index]
        case_results = []
        for repetition in range(1, repetitions + 1):
            start = time.perf_counter()
            # Repetitions are evaluations, not ordinary task reuse: always query the model afresh.
            cache_enabled = getattr(orchestrator, "enable_response_cache", None)
            if cache_enabled is not None:
                orchestrator.enable_response_cache = False
            try:
                result = orchestrator.run(case["task"], case.get("context", ""))
            finally:
                if cache_enabled is not None:
                    orchestrator.enable_response_cache = cache_enabled
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            normalized = result.message.casefold()
            missing = [
                needle
                for needle in case.get("must_contain", [])
                if needle.casefold() not in normalized
            ]
            forbidden_text = [
                needle
                for needle in case.get("must_not_contain", [])
                if needle.casefold() in normalized
            ]
            used_tools = [
                item["tool"] for item in result.trace if isinstance(item.get("tool"), str)
            ]
            missing_tools = [
                tool for tool in case.get("required_tools", []) if tool not in used_tools
            ]
            forbidden_tools_used = [
                tool for tool in case.get("forbidden_tools", []) if tool in used_tools
            ]
            expected_status = case.get("expected_status")
            status_ok = expected_status is None or result.status == expected_status
            proposal_ids = [
                item.get("proposal_id")
                for item in result.trace
                if item.get("tool") == "propose_patch" and isinstance(item.get("proposal_id"), str)
            ]
            proposal_ok = not case.get("require_patch_proposal", False) or bool(proposal_ids)
            verification_events = [
                item for item in result.trace if item.get("tool") == "verify_proposal"
            ]
            successful_verification = any(
                item.get("verified_proposal") is True and item.get("verification_passed") is True
                for item in verification_events
            )
            verification_ok = (
                not case.get("require_successful_verification", False) or successful_verification
            )
            expected_regressions = case.get("expected_regression_statuses", [])
            observed_regressions = [
                item.get("regression_status")
                for item in verification_events
                if isinstance(item.get("regression_status"), str)
            ]
            regression_ok = not expected_regressions or any(
                status in expected_regressions for status in observed_regressions
            )
            min_steps = case.get("min_steps")
            max_steps = case.get("max_steps")
            steps_ok = (min_steps is None or result.steps >= min_steps) and (
                max_steps is None or result.steps <= max_steps
            )
            checks = {
                "must_contain": not missing,
                "must_not_contain": not forbidden_text,
                "required_tools": not missing_tools,
                "forbidden_tools": not forbidden_tools_used,
                "expected_status": status_ok,
                "patch_proposal": proposal_ok,
                "successful_verification": verification_ok,
                "regression_status": regression_ok,
                "step_bounds": steps_ok,
            }
            item = {
                "id": case_id,
                "repetition": repetition,
                "passed": all(checks.values()),
                "checks": checks,
                "missing": missing,
                "forbidden_text_found": forbidden_text,
                "missing_tools": missing_tools,
                "forbidden_tools_used": forbidden_tools_used,
                "expected_status": expected_status,
                "status": result.status,
                "status_ok": status_ok,
                "proposal_ids": proposal_ids,
                "patch_proposal_ok": proposal_ok,
                "successful_verification": successful_verification,
                "verification_ok": verification_ok,
                "observed_regression_statuses": observed_regressions,
                "regression_status_ok": regression_ok,
                "steps": result.steps,
                "steps_ok": steps_ok,
                "tools_used": used_tools,
                "latency_ms": elapsed_ms,
                "estimated_output_tokens": estimate_tokens(result.message),
            }
            results.append(item)
            case_results.append(item)
        case_passed = sum(1 for item in case_results if item["passed"])
        latencies = [item["latency_ms"] for item in case_results]
        per_case.append(
            {
                "id": case_id,
                "runs": len(case_results),
                "passed": case_passed,
                "failed": len(case_results) - case_passed,
                "pass_rate": round(case_passed / len(case_results), 4),
                "stable_pass": case_passed == len(case_results),
                "latency_mean_ms": round(statistics.fmean(latencies), 2),
                "latency_median_ms": round(statistics.median(latencies), 2),
                "estimated_output_tokens_total": sum(
                    item["estimated_output_tokens"] for item in case_results
                ),
            }
        )

    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    latencies = [item["latency_ms"] for item in results]
    return {
        "schema_version": 5,
        "metadata": {
            "created_at": datetime.now(UTC).isoformat(),
            "aurix_version": __version__,
            "python_version": platform.python_version(),
            "provider_class": type(orchestrator.provider).__name__,
            "suite_sha256": suite_sha256,
        },
        "cases": len(validated),
        "repetitions": repetitions,
        "executions": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4),
        "consistently_passing_cases": sum(1 for item in per_case if item["stable_pass"]),
        "latency_mean_ms": round(statistics.fmean(latencies), 2),
        "latency_median_ms": round(statistics.median(latencies), 2),
        "estimated_output_tokens_total": sum(item["estimated_output_tokens"] for item in results),
        "per_case": per_case,
        "results": results,
        "limitations": [
            "Acceptance criteria do not establish semantic correctness.",
            "Token estimates use characters divided by four and are not provider billing data.",
            "Repeated runs may consume additional local compute or API credits.",
        ],
    }


def compare_reports(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Compare two benchmark reports with the same suite and repetition count.

    This is a descriptive comparison, not a statistical significance test.
    """
    for label, report in (("current", current), ("baseline", baseline)):
        if not isinstance(report, dict) or report.get("schema_version") != 5:
            raise ValueError(f"{label} report must use benchmark schema_version 5")
        if not isinstance(report.get("metadata"), dict) or not isinstance(
            report.get("per_case"), list
        ):
            raise ValueError(f"{label} report is missing metadata or per_case results")
        if not isinstance(report.get("pass_rate"), (int, float)):
            raise ValueError(f"{label} report has no valid pass_rate")
    current_meta, baseline_meta = current["metadata"], baseline["metadata"]
    if current_meta.get("suite_sha256") != baseline_meta.get("suite_sha256"):
        raise ValueError("Cannot compare reports from different benchmark suites")
    if current.get("repetitions") != baseline.get("repetitions"):
        raise ValueError("Cannot compare reports with different repetition counts")
    current_cases = {item.get("id"): item for item in current["per_case"] if isinstance(item, dict)}
    baseline_cases = {
        item.get("id"): item for item in baseline["per_case"] if isinstance(item, dict)
    }
    if not current_cases or current_cases.keys() != baseline_cases.keys():
        raise ValueError("Benchmark reports do not contain the same case IDs")
    per_case = []
    for case_id in sorted(current_cases):
        now, before = current_cases[case_id], baseline_cases[case_id]
        per_case.append(
            {
                "id": case_id,
                "baseline_pass_rate": before.get("pass_rate"),
                "current_pass_rate": now.get("pass_rate"),
                "pass_rate_delta": round(
                    float(now.get("pass_rate", 0)) - float(before.get("pass_rate", 0)), 4
                ),
                "baseline_stable_pass": before.get("stable_pass"),
                "current_stable_pass": now.get("stable_pass"),
                "latency_mean_delta_ms": round(
                    float(now.get("latency_mean_ms", 0)) - float(before.get("latency_mean_ms", 0)),
                    2,
                ),
                "estimated_output_tokens_delta": int(now.get("estimated_output_tokens_total", 0))
                - int(before.get("estimated_output_tokens_total", 0)),
            }
        )
    delta = round(float(current["pass_rate"]) - float(baseline["pass_rate"]), 4)
    return {
        "schema_version": 1,
        "comparison": "descriptive_only",
        "suite_sha256": current_meta["suite_sha256"],
        "baseline_version": baseline_meta.get("aurix_version"),
        "current_version": current_meta.get("aurix_version"),
        "baseline_provider": baseline_meta.get("provider_class"),
        "current_provider": current_meta.get("provider_class"),
        "baseline_pass_rate": baseline["pass_rate"],
        "current_pass_rate": current["pass_rate"],
        "pass_rate_delta": delta,
        "latency_mean_delta_ms": round(
            float(current.get("latency_mean_ms", 0)) - float(baseline.get("latency_mean_ms", 0)), 2
        ),
        "estimated_output_tokens_delta": int(current.get("estimated_output_tokens_total", 0))
        - int(baseline.get("estimated_output_tokens_total", 0)),
        "per_case": per_case,
        "limitations": [
            "Comparison is descriptive and does not establish causality or statistical significance.",
            "Provider, model, hardware, and runtime settings should be held constant for meaningful comparisons.",
            "Acceptance criteria do not establish semantic correctness.",
        ],
    }
