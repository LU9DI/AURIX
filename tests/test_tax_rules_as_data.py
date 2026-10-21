from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

_MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "research/tax-rules-as-data/run_study.py")
)


def test_classify_path_is_conservative_and_explained():
    classify = _MODULE["classify_path"]
    assert classify("src/rules/tax.ts") == "application_code"
    assert classify("rules/tax.json") == "declarative_candidate"
    assert classify("data/fator-r.csv") == "declarative_candidate"
    assert classify("src/services/calculator.ts") == "application_code"
    assert classify("prisma/schema.prisma") == "schema_or_data_candidate"
    assert classify("migrations/20261005_rule_update.sql") == "schema_or_data_candidate"
    assert classify("data/rules.json") == "declarative_candidate"
    assert classify("rules/README.md") == "other"


def test_parse_numstat_skips_binary_and_counts_added_plus_deleted():
    parse = _MODULE["parse_numstat"]
    rows = parse("3\t2\tsrc/rules/rates.json\n-\t-\tassets/logo.png\n")
    assert len(rows) == 1
    assert rows[0]["changed_lines"] == 5
    assert rows[0]["class"] == "declarative_candidate"


def test_run_study_on_temporary_git_repo(tmp_path: Path):
    repo = tmp_path / "fixture-repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "AURIX test")
    git("config", "user.email", "aurix-test@example.invalid")

    (repo / "rules.json").write_text('{"threshold": 0.1}\n', encoding="utf-8")
    git("add", "rules.json")
    git("commit", "-m", "add declarative threshold")

    (repo / "tax.ts").write_text('const aliquota = 0.1;\n', encoding="utf-8")
    git("add", "tax.ts")
    git("commit", "-m", "add calculation code")

    report = _MODULE["run_study"](repo)
    assert report["commits_evaluated"] == 2
    assert report["totals"]["changed_lines"] == 2
    assert report["totals"]["changed_lines_by_class"]["declarative_candidate"] == 1
    assert report["totals"]["changed_lines_by_class"]["application_code"] == 1
    assert report["totals"]["added_lines_containing_tax_rule_terms"] == 2
    signal_files = {
        item["path"]
        for commit in report["commits"]
        for item in commit["rule_signal_files"]
    }
    assert signal_files == {"rules.json", "tax.ts"}
    rendered = str(report)
    assert "const aliquota" not in rendered
    assert str(repo) not in rendered

    script = Path(__file__).resolve().parents[1] / "research/tax-rules-as-data/run_study.py"
    output_inside_repo = repo / "report.json"
    result = subprocess.run(
        [sys.executable, str(script), str(repo), "--output", str(output_inside_repo)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "outside target repository" in result.stderr
    assert not output_inside_repo.exists()

    output_outside_repo = tmp_path / "tax-data-screen.json"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(repo),
            "--max-commits",
            "1",
            "--output",
            str(output_outside_repo),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    saved_report = json.loads(output_outside_repo.read_text(encoding="utf-8"))
    assert saved_report["commits_evaluated"] == 1



def test_build_review_sample_is_deterministic_deduplicated_and_source_free():
    sampler_path = Path(__file__).resolve().parents[1] / "research/tax-rules-as-data/build_review_sample.py"
    sampler = runpy.run_path(str(sampler_path))["build_sample"]
    report = {
        "commits": [
            {"commit": "abc123", "rule_signal_files": [
                {"path": "src/tax.ts", "matching_added_lines": 2},
                {"path": "rules.json", "matching_added_lines": 1},
                {"path": "src/tax.ts", "matching_added_lines": 3},
            ]},
            {"commit": "def456", "rule_signal_files": [
                {"path": "src/tax.ts", "matching_added_lines": 1},
            ]},
        ]
    }
    sample = sampler(report, limit=2)
    assert len(sample) == 2
    assert len({(row["commit"], row["path"]) for row in sample}) == 2
    assert [row["sample_order_sha256"] for row in sample] == sorted(
        row["sample_order_sha256"] for row in sample
    )
    assert all(row["primary_label"] == "" for row in sample)
    assert all("matching_added_lines" not in row for row in sample)
    assert sampler(report, limit=2) == sample



def test_review_summary_uses_labelled_denominator_and_rejects_unknown_labels():
    summary_path = Path(__file__).resolve().parents[1] / "research/tax-rules-as-data/summarize_review.py"
    summarize = runpy.run_path(str(summary_path))["summarize"]
    result = summarize([
        {"primary_label": "data_only"},
        {"primary_label": "algorithmic"},
        {"primary_label": "uncertain"},
        {"primary_label": ""},
    ])
    assert result["total_sample_units"] == 4
    assert result["labelled_units"] == 3
    assert result["unlabelled_units"] == 1
    assert result["counts"]["data_only"] == 1
    assert result["counts"]["uncertain"] == 1
    assert result["proportions_among_labelled"]["data_only"] == 1 / 3
    assert "not the share of changed lines" in result["warning"]
    try:
        summarize([{"primary_label": "maybe"}])
    except ValueError as exc:
        assert "invalid primary_label" in str(exc)
    else:
        raise AssertionError("unknown labels must be rejected")
