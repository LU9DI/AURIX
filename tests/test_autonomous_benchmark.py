import json
from pathlib import Path

import pytest

from aurix.evaluation.autonomous import load_autonomous_suite, run_autonomous_benchmark


class SequenceProvider:
    def __init__(self, *responses):
        self.responses = list(responses)

    def generate(self, prompt, *, system=""):
        return self.responses.pop(0)


def _suite(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (fixture / "test_calculator.py").write_text(
        "from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    suite = tmp_path / "suite.json"
    suite.write_text(
        json.dumps(
            [
                {
                    "id": "add-bug",
                    "fixture": "fixture",
                    "task": "Fix add(a, b) so it adds its arguments and use propose_patch.",
                    "expect_baseline_passed": False,
                    "expect_candidate_passed": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    return suite


def _provider():
    patch = "--- a/calculator.py\n+++ b/calculator.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
    return SequenceProvider(
        json.dumps({"status": "tool_call", "tool": "propose_patch", "arguments": {"patch": patch}}),
        json.dumps({"status": "final", "message": "Prepared a minimal patch proposal."}),
    )


def test_autonomous_benchmark_model_proposal_fixes_bug_in_disposable_copy(tmp_path):
    suite = _suite(tmp_path)
    original = (tmp_path / "fixture" / "calculator.py").read_text(encoding="utf-8")
    report = run_autonomous_benchmark(suite, _provider(), confirm=True, timeout_seconds=10)
    assert report["cases"] == 1
    assert report["passed"] == 1
    assert report["demonstrated_fixes"] == 1
    case = report["results"][0]
    assert case["baseline"]["passed"] is False
    assert case["candidate"]["passed"] is True
    assert len(case["proposal_id"]) == 12
    assert (tmp_path / "fixture" / "calculator.py").read_text(encoding="utf-8") == original


def test_autonomous_benchmark_requires_confirmation(tmp_path):
    with pytest.raises(PermissionError, match="Explicit confirmation"):
        run_autonomous_benchmark(_suite(tmp_path), _provider())


def test_autonomous_suite_rejects_parent_traversal(tmp_path):
    suite = _suite(tmp_path)
    data = json.loads(suite.read_text(encoding="utf-8"))
    data[0]["fixture"] = "../outside"
    suite.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="inside the suite directory"):
        load_autonomous_suite(suite)


def test_autonomous_benchmark_fails_when_model_does_not_propose_patch(tmp_path):
    provider = SequenceProvider(json.dumps({"status": "final", "message": "I would fix it."}))
    report = run_autonomous_benchmark(_suite(tmp_path), provider, confirm=True, timeout_seconds=10)
    assert report["failed"] == 1
    assert report["results"][0]["status"] == "no_unique_proposal"
