# Manual review protocol: tax-rule diffs

## Purpose

Estimate how often tax-related changes are genuinely data-only, algorithmic, or mixed. This protocol is a human-review follow-up to the automated screening report, not a claim that the lexical screen finds every relevant change.

## Freeze the inputs

1. Run `run_study.py` against a local clone at a recorded Git commit.
2. Save the JSON report outside the target repository.
3. Record the analyzed repository commit, the AURIX study-script commit, and a SHA-256 hash of the JSON report in the experiment notes. Do not publish source code or private repository URLs.
4. Treat the report as immutable for this review round. If the script or source revision changes, create a new round rather than silently mixing results.

## Build a reproducible sample

1. Eligible units are individual changed-file entries in `commits[*].rule_signal_files`. The screen's keyword match is only a sampling signal.
2. Deduplicate by the pair `(commit, path)`; do not collapse different commits that touch the same file.
3. For each unit, calculate `SHA-256(commit + NUL + path)` and sort by the resulting lowercase hexadecimal digest, ascending. This produces a deterministic order independent of report row ordering.
4. Review the first 30 units, or all units if fewer than 30 exist. If the sample is very small, report the exact denominator; do not imply statistical precision.
5. Keep a separate appendix of obvious edge cases discovered during review, but do not mix those purposively selected cases into the random-like deterministic sample estimates.

## Label each unit

Review the full diff for the selected file and commit, including relevant surrounding code/tests and prior behavior when needed. Assign exactly one primary label:

- `data_only`: only legal parameters, rates, thresholds, mappings, or effective-date values change; no executable decision behavior or validation contract changes.
- `algorithmic`: executable behavior, calculation steps, branching, normalization, validation, fallback, or control flow changes without a separable data-only change.
- `mixed`: both data and executable behavior change in the same reviewed unit, or the distinction cannot be separated without losing semantics.
- `not_tax_rule`: the lexical signal is incidental, test/documentation-only, or unrelated to a business tax rule.
- `uncertain`: insufficient context to label responsibly. Record why; do not force it into another category.

A changed SQL migration is not automatically data-only. A JSON/YAML file is not automatically a tax rule. A test-only change should be labelled `not_tax_rule` unless it changes executable behavior through generated artifacts or fixtures in a way relevant to the target system.

## Record results

For each unit record: commit hash, relative path, primary label, reviewer, short rationale, and confidence (high/medium/low). Do not paste source lines or secrets into the results artifact.

Report counts and proportions with explicit denominators, including `uncertain` and `not_tax_rule`. Give a Wilson interval only if the sample design and unit definition justify it; otherwise describe the proportions as descriptive of this sample. The share of data-only units is not the share of changed lines and must not be presented as such.

## Known bias and limits

The candidate pool excludes relevant changes without matching terms, so it cannot estimate recall over all tax-rule changes. Multiple file entries from one commit are not independent observations. The deterministic hash order is reproducible but is not a guarantee of representativeness. A stronger follow-up would manually label a separately defined sample of all commits or all changed files, including files without lexical hits.

## Decision gate

Do not design a DSL or claim a conversion percentage from this review alone. Use the results to decide whether to run a broader review and to identify stable data boundaries. Any proposed data-driven rule format still needs schema validation, effective-date semantics, deterministic calculations, migration/versioning behavior, and regression tests against known cases.
