# Tax-platform changes as data: screening experiment

Run against an existing local clone of `tax-platform-br`:

```bash
python research/tax-rules-as-data/run_study.py /path/to/tax-platform-br --output tax-data-screen.json
```

The output path must be outside the analyzed repository; the script rejects an output path inside
the target tree so the report cannot accidentally dirty the repository. The script reads Git history
only; it does not clone, check out, modify, or execute the target repository. It reports changed-line counts grouped by likely declarative files, schema/migration
files, application code, and other files. It also counts added lines containing a small set of
tax-rule terms such as brackets, rates, limits, and Fator R, and records the relative file paths
where those matching lines were added. This makes it easier to build a reproducible shortlist of
diffs for manual review without storing matching source lines in the report.

## How to interpret it

This is a cheap screening pass, not proof that a fraction of work can safely become data. Paths
and extensions are weak proxies; tax logic may be embedded in TypeScript, and a migration or JSON
file may not represent a business rule. A useful follow-up is a manually reviewed sample of
rule-related diffs, estimating (a) what is genuinely a parameter/table edit, (b) what requires
algorithm changes, and (c) what needs both.

No DSL is proposed by this script. The goal is to establish a measured ceiling before designing
a declarative schema and invariant checks.

The reproducible follow-up procedure is documented in [manual-review-protocol.md](manual-review-protocol.md).
It defines deterministic sample selection, labels for data-only versus algorithmic changes, and limits
on interpreting the resulting proportions.

## Manual architecture spot-check (not a historical percentage)

A read-only spot-check of the current `tax-platform-br` tree found both sides of the boundary:

- `migrations/20261005_107_simples_2027_revenue_composition.sql` stores a versioned rule and parameters in `tax_rules.parameters` (JSONB). This is a strong candidate for parameter/data review, though the SQL migration itself is not a declarative rule format.
- `migrations/20261005_111_simples_start_of_activity_rbt12.sql` updates explicit multipliers and a month count. These values look data-like, but their legal semantics and effective dates still need review.
- `src/services/taxService.ts` contains executable behavior such as `calculateMeiLoad` and `resolveSimplesNationalMonthlyRevenue`. A change to the algorithm or validation contract should not be counted as a parameter-only change.
- `src/services/taxActivityClassificationService.ts` implements CNAE normalization, explicit identifier matching, and an `unknown` fallback. The mapping can be data-driven, but normalization and fallback behavior are algorithmic invariants.

This sample supports testing a **hybrid boundary**: keep calculation/validation semantics in code, while versioning carefully validated legal parameters and mappings as data. It does **not** establish how much of the historical change volume is safely convertible. The full-history script plus manually reviewed diffs is still required for that estimate.


## Generate the review worksheet

After creating the screening JSON, generate a deterministic CSV worksheet (the CSV contains hashes, commit IDs, relative paths, and blank review fields, not source lines):

```bash
python research/tax-rules-as-data/build_review_sample.py tax-data-screen.json --limit 30 --output tax-data-review.csv
```

The sampler deduplicates by `(commit, path)`, computes `SHA-256(commit + NUL + path)`, and selects the lowest hashes. Reviewers should fill `primary_label`, `reviewer`, `confidence`, and `rationale` according to the protocol. The worksheet is an operational aid; it does not inspect diffs or assign labels automatically.


After filling the review worksheet, summarize the labels with:

```bash
python research/tax-rules-as-data/summarize_review.py tax-data-review.csv --output tax-data-review-summary.json
```

The summary validates the five allowed labels, reports unlabelled rows separately, and calculates proportions only over labelled sample units. It explicitly describes the result as a screened-sample statistic, not a historical conversion percentage.
