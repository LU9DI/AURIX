from __future__ import annotations

import runpy
from pathlib import Path

_MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "research/chronological-slot-filling/run_study.py")
)


def test_shape_and_slots_preserve_syntax_and_capture_identifiers():
    shape, slots = _MODULE["shape_and_slots"]('return client.status(400).json({"ok": true})')

    assert shape == 'return <ID>.status(<NUM>).json({<STR>: true})'
    assert "client" in slots
    assert "400" in slots
    assert '"ok"' in slots


def test_empty_history_has_null_rates_not_division_by_zero(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)

    report = _MODULE["run_study"](repo)

    assert report["history_commits_evaluated"] == 0
    assert report["totals"]["exact_line_reuse_rate"] is None
    assert report["totals"]["slot_top5_recall"] is None


def test_chronological_evaluation_only_counts_prior_shapes(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)

    source = repo / "sample.py"
    source.write_text("return alpha(1)\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "sample.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "first"], check=True, capture_output=True)

    source.write_text("return beta(2)\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "sample.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "second"], check=True, capture_output=True)

    report = _MODULE["run_study"](repo, max_commits=0)

    assert report["history_commits_evaluated"] == 2
    assert report["commits"][0]["same_shape"] == 0
    assert report["commits"][1]["same_shape"] == 1
    assert report["totals"]["same_shape_rate"] > 0
