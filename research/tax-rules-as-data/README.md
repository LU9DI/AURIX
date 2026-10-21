# Tax-platform changes as data: screening experiment

Run against an existing local clone of `tax-platform-br`:

```bash
python research/tax-rules-as-data/run_study.py /path/to/tax-platform-br --output tax-data-screen.json
```

The script reads Git history only; it does not clone, check out, modify, or execute the target
repository. It reports changed-line counts grouped by likely declarative files, schema/migration
files, application code, and other files. It also counts added lines containing a small set of
tax-rule terms such as brackets, rates, limits, and Fator R.

## How to interpret it

This is a cheap screening pass, not proof that a fraction of work can safely become data. Paths
and extensions are weak proxies; tax logic may be embedded in TypeScript, and a migration or JSON
file may not represent a business rule. A useful follow-up is a manually reviewed sample of
rule-related diffs, estimating (a) what is genuinely a parameter/table edit, (b) what requires
algorithm changes, and (c) what needs both.

No DSL is proposed by this script. The goal is to establish a measured ceiling before designing
a declarative schema and invariant checks.
