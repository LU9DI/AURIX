"""Estimate whether tax-platform-br changes are concentrated in declarative data.

This is a screening metric, not a semantic claim that changes can be moved to data.
It uses Git history and classifies changed lines by file type/path and conservative
textual signals. It never modifies or executes the target repository.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
from pathlib import Path

DATA_EXTENSIONS = {".json", ".jsonc", ".yaml", ".yml", ".toml", ".csv"}
SCHEMA_EXTENSIONS = {".sql", ".prisma"}
CODE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".py"}
DATA_PATH = re.compile(r"(^|/)(data|fixtures|rules|tables|rates|constants|config|migrations?)(/|$)", re.I)
RULE_SIGNAL = re.compile(r"\b(?:faixa|fator.?r|anexo|aliquota|al[ií]quota|limite|threshold|bracket|rate|tax.?rule)\b", re.I)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True,
        text=True, errors="replace",
    ).stdout


def classify_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    suffix = Path(normalized).suffix.lower()
    # SQL migrations are schema/data changes, not plain declarative data files.
    # Check this before DATA_PATH because "migrations" is a candidate directory.
    if suffix in SCHEMA_EXTENSIONS:
        return "schema_or_data_candidate"
    if DATA_PATH.search(normalized) or suffix in DATA_EXTENSIONS:
        return "declarative_candidate"
    if p.suffix.lower() in CODE_EXTENSIONS:
        return "application_code"
    return "other"


def parse_numstat(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            continue
        added, deleted, path = fields
        # Binary files use '-' instead of numeric counts.
        if added == "-" or deleted == "-":
            continue
        try:
            a, d = int(added), int(deleted)
        except ValueError:
            continue
        rows.append({
            "path": path,
            "added_lines": a,
            "deleted_lines": d,
            "changed_lines": a + d,
            "class": classify_path(path),
        })
    return rows


def run_study(repo: Path, max_commits: int = 0) -> dict:
    repo = repo.resolve()
    commits = git(repo, "log", "--reverse", "--no-merges", "--format=%H").splitlines()
    if max_commits > 0:
        commits = commits[-max_commits:]
    by_class = collections.Counter()
    by_extension = collections.Counter()
    rule_related_lines = collections.Counter()
    commit_rows = []
    for commit in commits:
        stat = git(repo, "show", "--format=", "--no-renames", "--numstat", commit)
        files = parse_numstat(stat)
        counts = collections.Counter()
        for row in files:
            by_class[row["class"]] += row["changed_lines"]
            by_extension[Path(row["path"]).suffix.lower() or "<no extension>"] += row["changed_lines"]
            counts[row["class"]] += row["changed_lines"]
        # Scan added lines in all files; only counts are retained, never source text.
        patch = git(repo, "show", "--format=", "--no-ext-diff", "--unified=0", commit)
        relevant_added = 0
        for line in patch.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            if RULE_SIGNAL.search(line[1:]):
                relevant_added += 1
        if relevant_added:
            rule_related_lines["added_lines_with_tax_rule_terms"] += relevant_added
        commit_rows.append({
            "commit": commit,
            "files_changed": len(files),
            "changed_lines_by_class": dict(counts),
            "added_lines_with_tax_rule_terms": relevant_added,
        })

    total = sum(by_class.values())
    candidates = by_class["declarative_candidate"] + by_class["schema_or_data_candidate"]
    return {
        "schema_version": 1,
        "study": "tax_platform_changes_as_data_screen",
        "repository_name": repo.name,
        "commits_evaluated": len(commits),
        "totals": {
            "changed_lines": total,
            "changed_lines_by_class": dict(by_class),
            "changed_lines_by_extension": dict(by_extension),
            "declarative_or_schema_candidate_share": candidates / total if total else None,
            "added_lines_containing_tax_rule_terms": rule_related_lines["added_lines_with_tax_rule_terms"],
        },
        "protocol": {
            "history": "all non-merge commits in chronological order unless --max-commits is set",
            "line_counts": "Git numstat added + deleted lines; rename detection disabled",
            "path_classification": "file extension and directory names only",
            "tax_terms": "count of added diff lines containing a small set of tax-rule terms; not limited to TypeScript",
            "privacy": "report contains commit hashes and relative file paths, no source text or remote URL",
            "limitations": [
                "candidate share is not the fraction of changes safely representable as data",
                "classification may label configs or non-rule SQL migrations as candidates even when they are not business rules",
                "rules embedded in application code may be missed; matching tax terms is only a rough signal",
                "a semantic review of candidate diffs is required before designing a DSL or schema",
            ],
        },
        "commits": commit_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="already-cloned tax-platform-br repository")
    parser.add_argument("--max-commits", type=int, default=0, help="most recent non-merge commits; 0 means all")
    parser.add_argument("--output", type=Path, help="write JSON report")
    args = parser.parse_args()
    report = run_study(args.repo, args.max_commits)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
