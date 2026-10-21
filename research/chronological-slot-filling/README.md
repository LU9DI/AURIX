# Chronological slot-filling study

Offline exploratory harness for measuring whether repository history can support line-template
reuse and whether lexical reuse improves as verified commits accumulate.

## Run

```bash
python research/chronological-slot-filling/run_study.py /path/to/cloned/repo --max-commits 200 --output study.json
```

The script never clones, checks out, or modifies the target repository. It walks non-merge commits
in chronological order, inspects added nonblank code lines, and builds its candidate counts only
from lines in earlier commits. It reports exact-line reuse, normalized-shape reuse, and top-1/top-5
recall for lexical values observed in earlier lines of the same normalized shape.

## Interpretation limits

- Top-k is **candidate recall**, not semantic correctness or executable-code accuracy.
- This first version is lexical, not AST-aware: it does not know variable scope, types, imports,
  task intent, or whether a candidate identifier is valid at the use site.
- Added-line diffs may include refactors, cherry-picks, generated files, and historical artifacts.
- A growing reuse rate does not by itself prove learning or improved patch success. Compare against
  a frequency-only baseline and evaluate chronological held-out patch tasks before drawing that
  conclusion.
- Output contains commit hashes and repository name, not absolute paths or remote URLs. Review
  output before sharing it; source code and identifiers are not written into the report.

No generation, model training, network access, repository cloning, or code execution occurs.
