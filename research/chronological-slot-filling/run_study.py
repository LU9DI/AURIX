"""Chronological repository study for line-template reuse and incremental learning.

This is an offline diagnostic, not a code generator. It evaluates added lines in Git
history in chronological order, using only earlier commits to build its vocabulary.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
from pathlib import Path

IDENTIFIER = re.compile(r"(?<![.\\w])(?:[A-Za-z_$][\\w$]*)(?!\\w)")
NUMBER = re.compile(r"\\b\\d+(?:\\.\\d+)?\\b")
STRING = re.compile(r"""(['"]).*?\\1""")
KEYWORDS = {
    "and", "as", "assert", "async", "await", "break", "case", "catch", "class",
    "const", "continue", "def", "del", "elif", "else", "except", "false", "False",
    "finally", "for", "from", "function", "if", "import", "in", "is", "lambda",
    "let", "match", "new", "None", "not", "null", "or", "pass", "raise", "return",
    "self", "static", "switch", "this", "throw", "true", "True", "try", "var",
    "while", "with", "yield",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True,
        text=True, errors="replace",
    ).stdout


def added_lines(repo: Path, commit: str) -> list[str]:
    patch = git(repo, "show", "--format=", "--no-ext-diff", "--unified=0", commit)
    result = []
    for line in patch.splitlines():
        if line.startswith("+++") or not line.startswith("+"):
            continue
        value = line[1:].strip()
        if value and not value.startswith(("#", "//", "*")):
            result.append(value)
    return result


def shape_and_slots(line: str) -> tuple[str, list[str]]:
    """Replace identifiers/literals with typed slots while preserving syntax."""
    slots: list[str] = []
    def replace_string(match):
        slots.append(match.group(0))
        return "<STR>"
    shaped = STRING.sub(replace_string, line)
    def replace_number(match):
        slots.append(match.group(0))
        return "<NUM>"
    shaped = NUMBER.sub(replace_number, shaped)

    def replace_identifier(match):
        token = match.group(0)
        if token in KEYWORDS:
            return token
        slots.append(token)
        return "<ID>"
    shaped = IDENTIFIER.sub(replace_identifier, shaped)
    return shaped, slots


def run_study(repo: Path, max_commits: int = 200) -> dict:
    repo = repo.resolve()
    commits = git(repo, "log", "--reverse", "--no-merges", "--format=%H").splitlines()
    if max_commits > 0:
        commits = commits[-max_commits:]
    prior_exact: collections.Counter[str] = collections.Counter()
    prior_shapes: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    prior_slot_values: collections.Counter[str] = collections.Counter()
    rows = []
    total_lines = exact_hits = shape_hits = slot_total = slot_top1 = slot_top5 = 0

    for commit in commits:
        lines = added_lines(repo, commit)
        commit_exact = commit_shape = commit_slots = commit_top1 = commit_top5 = 0
        for line in lines:
            total_lines += 1
            if line in prior_exact:
                exact_hits += 1
                commit_exact += 1
            shape, slots = shape_and_slots(line)
            if shape in prior_shapes:
                shape_hits += 1
                commit_shape += 1
                candidates = prior_shapes[shape].most_common(5)
                ranked = [value for value, _ in candidates]
                # Evaluate only values that look like slots, and only if the same
                # shape occurred before. This is candidate recall, not semantic correctness.
                for gold in slots:
                    if gold.startswith(('"', "'", "<")):
                        continue
                    slot_total += 1
                    commit_slots += 1
                    if ranked and gold == ranked[0]:
                        slot_top1 += 1
                        commit_top1 += 1
                    if gold in ranked:
                        slot_top5 += 1
                        commit_top5 += 1
            prior_exact[line] += 1
            prior_shapes[shape].update(slots)
            prior_slot_values.update(slots)
        rows.append({
            "commit": commit,
            "added_code_lines": len(lines),
            "exact_reuse": commit_exact,
            "same_shape": commit_shape,
            "eligible_slots": commit_slots,
            "slot_top1": commit_top1,
            "slot_top5": commit_top5,
        })

    return {
        "schema_version": 1,
        "study": "chronological_line_template_slot_candidates",
        "repository_name": repo.name,
        "history_commits_evaluated": len(commits),
        "protocol": {
            "order": "git log --reverse --no-merges; only earlier commits are used",
            "line_filter": "added nonblank lines excluding common comment prefixes",
            "slot_candidates": "frequency-ranked values observed in earlier lines of the same normalized shape",
            "limitations": [
                "not a parser or type-aware scope analysis",
                "top-k measures whether a lexical value appeared in prior same-shape lines, not whether it is semantically correct",
                "commit diffs can include cherry-picks, refactors, generated code, and merge-history artifacts",
                "only added lines are scored; deletions and changed context are not modeled",
            ],
        },
        "totals": {
            "added_code_lines": total_lines,
            "exact_line_reuse_rate": exact_hits / total_lines if total_lines else None,
            "same_shape_rate": shape_hits / total_lines if total_lines else None,
            "eligible_slots": slot_total,
            "slot_top1_recall": slot_top1 / slot_total if slot_total else None,
            "slot_top5_recall": slot_top5 / slot_total if slot_total else None,
        },
        "commits": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="already-cloned Git repository")
    parser.add_argument("--max-commits", type=int, default=200,
                        help="most recent non-merge commits to evaluate (0 = all)")
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    args = parser.parse_args()
    report = run_study(args.repo, args.max_commits)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
