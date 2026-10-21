"""Summarize manually labelled tax-rule review samples without overstating scope."""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

LABELS = ("data_only", "algorithmic", "mixed", "not_tax_rule", "uncertain")


def summarize(rows: list[dict]) -> dict:
    counts = collections.Counter()
    unlabeled = 0
    for row in rows:
        label = (row.get("primary_label") or "").strip()
        if not label:
            unlabeled += 1
        elif label not in LABELS:
            raise ValueError(f"invalid primary_label: {label}")
        else:
            counts[label] += 1
    total = len(rows)
    labelled = total - unlabeled
    return {
        "schema_version": 1,
        "unit": "changed-file entry identified by (commit, path)",
        "scope": "descriptive statistics for this screened sample only; not all tax-rule changes",
        "total_sample_units": total,
        "labelled_units": labelled,
        "unlabelled_units": unlabeled,
        "counts": {label: counts[label] for label in LABELS},
        "proportions_among_labelled": {
            label: counts[label] / labelled if labelled else None for label in LABELS
        },
        "warning": "The lexical screen may miss tax-related changes without matching terms; proportions are not the share of changed lines or convertible logic.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.review_csv.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    try:
        result = summarize(rows)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
