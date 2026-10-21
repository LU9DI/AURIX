from __future__ import annotations

import runpy
from pathlib import Path

_MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "research/tax-rules-as-data/run_study.py")
)


def test_classify_path_is_conservative_and_explained():
    classify = _MODULE["classify_path"]
    assert classify("src/rules/tax.ts") == "application_code"\n    assert classify("rules/tax.json") == "declarative_candidate"
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
