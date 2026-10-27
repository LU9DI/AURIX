---
name: research-validation
description: Keep experiments reproducible and conclusions tied to actual evidence.
---

# Research Validation

Source inspiration: https://skillissue.dev/patterns/

1. Read the experiment protocol, baseline, output schema, and tests before editing.
2. Record the hypothesis, variables, evaluation criteria, seeds, versions, and runtime configuration.
3. Keep prior run outputs unchanged; write new results to a new run directory.
4. Compare methods only when inputs, budgets, and scoring criteria are equivalent.
5. If a backend, model, or required control is unavailable, label the comparison inconclusive.
6. Test protocol invariants, artifact integrity, and failure paths.
7. Do not remove failed samples or adjust thresholds solely to improve results.
8. Report commands, run identifiers, sample counts, checksums, limitations, and conclusions supported by the data.
