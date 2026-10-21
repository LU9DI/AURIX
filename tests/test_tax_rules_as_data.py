from __future__ import annotations

import runpy
import subprocess
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
    rendered = str(report)
    assert "const aliquota" not in rendered
    assert str(repo) not in rendered
