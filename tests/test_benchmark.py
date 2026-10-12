import json

import pytest

from aurix.evaluation.benchmark import load_cases, run_benchmark
from aurix.telemetry import JSONLTelemetry


class FakeProvider:
    def generate(self, prompt, *, system=""):
        return json.dumps({"status": "final", "message": "Run the test before changing code."})


def test_benchmark_checks_required_terms(tmp_path):
    cases = [{"id": "test-first", "task": "What first?", "must_contain": ["test", "code"]}]
    from aurix.orchestrator import Orchestrator

    report = run_benchmark(
        Orchestrator(FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "trace.jsonl")), cases
    )
    assert report["cases"] == 1
    assert report["passed"] == 1
    assert report["pass_rate"] == 1.0


def test_benchmark_rejects_empty_file(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(path)


def test_benchmark_checks_status_steps_and_text_exclusions(tmp_path):
    from aurix.orchestrator import Orchestrator

    cases = [
        {
            "id": "guardrails",
            "task": "What first?",
            "must_contain": ["test"],
            "must_not_contain": ["deploy immediately"],
            "expected_status": "completed",
            "min_steps": 1,
            "max_steps": 1,
        }
    ]
    report = run_benchmark(
        Orchestrator(FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "trace.jsonl")), cases
    )
    item = report["results"][0]
    assert report["schema_version"] == 5
    assert item["passed"] is True
    assert item["checks"] == {
        "must_contain": True,
        "must_not_contain": True,
        "required_tools": True,
        "forbidden_tools": True,
        "expected_status": True,
        "patch_proposal": True,
        "successful_verification": True,
        "regression_status": True,
        "step_bounds": True,
    }


def test_benchmark_fails_missing_required_tool_and_forbidden_phrase(tmp_path):
    from aurix.orchestrator import Orchestrator

    cases = [
        {
            "task": "What first?",
            "required_tools": ["inspect_project"],
            "must_not_contain": ["test"],
        }
    ]
    report = run_benchmark(
        Orchestrator(FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "trace.jsonl")), cases
    )
    item = report["results"][0]
    assert item["passed"] is False
    assert item["missing_tools"] == ["inspect_project"]
    assert item["forbidden_text_found"] == ["test"]


def test_load_cases_validates_step_bounds_and_duplicate_ids(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{"task": "bad", "min_steps": 4, "max_steps": 2}]), encoding="utf-8")
    with pytest.raises(ValueError, match="min_steps"):
        load_cases(path)

    from aurix.orchestrator import Orchestrator

    duplicate = [{"id": "same", "task": "one"}, {"id": "same", "task": "two"}]
    with pytest.raises(ValueError, match="Duplicate"):
        run_benchmark(
            Orchestrator(FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "trace2.jsonl")),
            duplicate,
        )


def test_load_cases_rejects_malformed_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid benchmark JSON"):
        load_cases(path)


def test_benchmark_repetitions_reports_aggregate_stability(tmp_path):
    from aurix.orchestrator import Orchestrator

    class AlternatingProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, *, system=""):
            self.calls += 1
            message = "contains target" if self.calls % 2 else "misses requirement"
            return json.dumps({"status": "final", "message": message})

    provider = AlternatingProvider()
    cases = [{"id": "unstable", "task": "repeat", "must_contain": ["target"]}]
    report = run_benchmark(
        Orchestrator(provider, telemetry=JSONLTelemetry(tmp_path / "repeat.jsonl")),
        cases,
        repetitions=4,
    )
    assert report["schema_version"] == 5
    assert report["cases"] == 1
    assert report["executions"] == 4
    assert report["passed"] == 2
    assert report["failed"] == 2
    assert report["pass_rate"] == 0.5
    assert report["consistently_passing_cases"] == 0
    assert report["per_case"][0]["pass_rate"] == 0.5
    assert len(report["results"]) == 4
    assert [item["repetition"] for item in report["results"]] == [1, 2, 3, 4]
    assert report["latency_mean_ms"] >= 0
    assert report["estimated_output_tokens_total"] > 0


def test_benchmark_repetitions_validated(tmp_path):
    from aurix.orchestrator import Orchestrator

    orchestrator = Orchestrator(
        FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "bad-reps.jsonl")
    )
    with pytest.raises(ValueError, match="between 1 and 10"):
        run_benchmark(orchestrator, [{"task": "task"}], repetitions=0)
    with pytest.raises(ValueError, match="between 1 and 10"):
        run_benchmark(orchestrator, [{"task": "task"}], repetitions=11)
    with pytest.raises(ValueError, match="between 1 and 10"):
        run_benchmark(orchestrator, [{"task": "task"}], repetitions=True)


def test_benchmark_report_has_reproducibility_metadata(tmp_path):
    from aurix.orchestrator import Orchestrator

    cases = [{"id": "same-suite", "task": "What first?", "must_contain": ["test"]}]
    report = run_benchmark(
        Orchestrator(FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "meta.jsonl")), cases
    )
    metadata = report["metadata"]
    assert metadata["aurix_version"]
    assert metadata["python_version"]
    assert metadata["provider_class"] == "FakeProvider"
    assert len(metadata["suite_sha256"]) == 64
    assert metadata["created_at"].endswith("+00:00")


def test_compare_reports_calculates_descriptive_deltas(tmp_path):
    from aurix.evaluation.benchmark import compare_reports
    from aurix.orchestrator import Orchestrator

    cases = [{"id": "same-suite", "task": "What first?", "must_contain": ["test"]}]
    baseline = run_benchmark(
        Orchestrator(FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "base.jsonl")), cases
    )

    class FailingProvider:
        def generate(self, prompt, *, system=""):
            return json.dumps({"status": "final", "message": "No matching acceptance phrase."})

    current = run_benchmark(
        Orchestrator(FailingProvider(), telemetry=JSONLTelemetry(tmp_path / "current.jsonl")), cases
    )
    comparison = compare_reports(current, baseline)
    assert comparison["comparison"] == "descriptive_only"
    assert comparison["pass_rate_delta"] == -1.0
    assert comparison["per_case"][0]["pass_rate_delta"] == -1.0
    assert any("statistical significance" in item for item in comparison["limitations"])


def test_compare_reports_rejects_different_suites(tmp_path):
    from aurix.evaluation.benchmark import compare_reports
    from aurix.orchestrator import Orchestrator

    orchestrator = Orchestrator(FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "suite.jsonl"))
    one = run_benchmark(orchestrator, [{"id": "one", "task": "task one"}])
    two = run_benchmark(orchestrator, [{"id": "two", "task": "task two"}])
    with pytest.raises(ValueError, match="different benchmark suites"):
        compare_reports(two, one)


def test_compare_reports_rejects_different_repetitions(tmp_path):
    from aurix.evaluation.benchmark import compare_reports
    from aurix.orchestrator import Orchestrator

    cases = [{"id": "one", "task": "task one"}]
    one = run_benchmark(
        Orchestrator(FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "one.jsonl")),
        cases,
        repetitions=1,
    )
    two = run_benchmark(
        Orchestrator(FakeProvider(), telemetry=JSONLTelemetry(tmp_path / "two.jsonl")),
        cases,
        repetitions=2,
    )
    with pytest.raises(ValueError, match="different repetition counts"):
        compare_reports(two, one)


def test_benchmark_can_require_patch_and_successful_verification():
    from types import SimpleNamespace

    from aurix.evaluation.benchmark import run_benchmark

    class TraceOrchestrator:
        provider = FakeProvider()

        def run(self, task, context=""):
            return SimpleNamespace(
                message="Patch verified successfully.",
                status="completed",
                steps=2,
                trace=[
                    {"step": 1, "tool": "propose_patch", "proposal_id": "abcdef123456"},
                    {
                        "step": 2,
                        "tool": "verify_proposal",
                        "proposal_id": "abcdef123456",
                        "verified_proposal": True,
                        "verification_passed": True,
                        "regression_status": "clean",
                    },
                ],
            )

    report = run_benchmark(
        TraceOrchestrator(),
        [
            {
                "task": "Fix the bug",
                "require_patch_proposal": True,
                "require_successful_verification": True,
                "expected_regression_statuses": ["clean"],
            }
        ],
    )
    result = report["results"][0]
    assert report["schema_version"] == 5
    assert result["passed"] is True
    assert result["proposal_ids"] == ["abcdef123456"]
    assert result["successful_verification"] is True
    assert result["observed_regression_statuses"] == ["clean"]


def test_benchmark_fails_when_required_patch_verification_missing():
    from types import SimpleNamespace

    from aurix.evaluation.benchmark import run_benchmark

    class TraceOrchestrator:
        provider = FakeProvider()

        def run(self, task, context=""):
            return SimpleNamespace(message="Done", status="completed", steps=1, trace=[])

    report = run_benchmark(
        TraceOrchestrator(),
        [
            {
                "task": "Fix the bug",
                "require_patch_proposal": True,
                "require_successful_verification": True,
                "expected_regression_statuses": ["clean"],
            }
        ],
    )
    result = report["results"][0]
    assert result["passed"] is False
    assert result["checks"]["patch_proposal"] is False
    assert result["checks"]["successful_verification"] is False
    assert result["checks"]["regression_status"] is False


def test_benchmark_rejects_non_boolean_evidence_requirements():
    from types import SimpleNamespace

    from aurix.evaluation.benchmark import run_benchmark

    class TraceOrchestrator:
        provider = FakeProvider()

        def run(self, task, context=""):
            return SimpleNamespace(message="ok", status="completed", steps=1, trace=[])

    with pytest.raises(ValueError, match="require_patch_proposal must be a boolean"):
        run_benchmark(TraceOrchestrator(), [{"task": "x", "require_patch_proposal": "yes"}])
