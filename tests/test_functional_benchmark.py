import json
from pathlib import Path

import pytest

from aurix.evaluation.functional import load_functional_suite, run_functional_benchmark


def _make_suite(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixtures" / "add_bug"
    fixture.mkdir(parents=True)
    (fixture / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (fixture / "test_calculator.py").write_text(
        "from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
    )
    patch = tmp_path / "patches" / "fix.patch"
    patch.parent.mkdir()
    patch.write_text(
        "--- a/calculator.py\n+++ b/calculator.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n",
        encoding="utf-8",
    )
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps([{
        "id": "add-bug", "fixture": "fixtures/add_bug", "patch": "patches/fix.patch",
        "expect_baseline_passed": False, "expect_candidate_passed": True,
    }]), encoding="utf-8")
    return suite


def test_functional_benchmark_demonstrates_fix_without_mutating_fixture(tmp_path):
    suite = _make_suite(tmp_path)
    fixture_file = tmp_path / "fixtures" / "add_bug" / "calculator.py"
    original = fixture_file.read_text(encoding="utf-8")
    report = run_functional_benchmark(suite, confirm=True, timeout_seconds=10)
    assert report["cases"] == 1
    assert report["passed"] == 1
    assert report["demonstrated_fixes"] == 1
    assert report["results"][0]["baseline"]["passed"] is False
    assert report["results"][0]["candidate"]["passed"] is True
    assert fixture_file.read_text(encoding="utf-8") == original


def test_functional_benchmark_requires_explicit_confirmation(tmp_path):
    with pytest.raises(PermissionError, match="Explicit confirmation"):
        run_functional_benchmark(_make_suite(tmp_path))


def test_functional_suite_rejects_paths_outside_suite(tmp_path):
    suite = _make_suite(tmp_path)
    data = json.loads(suite.read_text(encoding="utf-8"))
    data[0]["patch"] = "../outside.patch"
    suite.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="inside the suite directory"):
        load_functional_suite(suite)


def test_functional_benchmark_rejects_patch_target_missing_from_fixture(tmp_path):
    suite = _make_suite(tmp_path)
    patch = tmp_path / "patches" / "fix.patch"
    patch.write_text(
        "--- a/does-not-exist.py\n+++ b/does-not-exist.py\n@@ -1 +1 @@\n-a\n+b\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="existing regular fixture file"):
        run_functional_benchmark(suite, confirm=True, timeout_seconds=10)


def test_functional_benchmark_rejects_deletions(tmp_path):
    suite = _make_suite(tmp_path)
    patch = tmp_path / "patches" / "fix.patch"
    patch.write_text(
        "--- a/calculator.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def add(a, b):\n-    return a - b\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="additions and deletions are unsupported"):
        run_functional_benchmark(suite, confirm=True, timeout_seconds=10)


def test_functional_suite_fingerprint_uses_relative_paths(tmp_path):
    first_root = tmp_path / "one"
    first_root.mkdir()
    first = _make_suite(first_root)
    second_root = tmp_path / "two"
    second_root.mkdir()
    second = _make_suite(second_root)
    first_report = run_functional_benchmark(first, confirm=True, timeout_seconds=10)
    second_report = run_functional_benchmark(second, confirm=True, timeout_seconds=10)
    assert first_report["metadata"]["suite_sha256"] == second_report["metadata"]["suite_sha256"]
