"""Build a deterministic, source-free manual-review sample from a screening report."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

LABELS = ("data_only", "algorithmic", "mixed", "not_tax_rule", "uncertain")


def build_sample(report: dict, limit: int = 30) -> list[dict]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    units = {}
    for commit_row in report.get("commits", []):
        commit = commit_row.get("commit")
        if not isinstance(commit, str) or not commit:
            continue
        for entry in commit_row.get("rule_signal_files", []):
            path = entry.get("path")
            if not isinstance(path, str) or not path:
                continue
            key = (commit, path)
            digest = hashlib.sha256((commit + "\0" + path).encode("utf-8")).hexdigest()
            units[key] = {
                "sample_order_sha256": digest,
                "commit": commit,
                "path": path,
                "primary_label": "",
                "reviewer": "",
                "confidence": "",
                "rationale": "",
            }
    return sorted(units.values(), key=lambda row: row["sample_order_sha256"])[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="screening JSON report")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True, help="CSV path for review labels")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    sample = build_sample(report, args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["sample_order_sha256", "commit", "path", "primary_label", "reviewer", "confidence", "rationale"]
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sample)


if __name__ == "__main__":
    main()
