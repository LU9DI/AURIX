# N-gram + neural hybrid benchmark

This is a bounded, reproducible *exploratory* experiment, stacked on PR #7 (the CPU-only n-gram provider). It does not change AURIX runtime behavior.

## Run

Use Python 3.11+, install the repository's CPU n-gram extra and PyTorch separately:

```bash
pip install -e '.[cpu-lm]'
pip install torch
python research/hybrid_benchmark/run.py --root . --output artifacts/hybrid-benchmark.json
```

The default neural run trains a small byte-level GRU for 400 optimization steps on CPU. Evaluation is capped at 25,000 held-out prefix bytes to bound the expensive per-byte probability-interpolation loop. Adjust `--steps`, `--max-eval-bytes`, `--hidden-size`, and `--seed` explicitly when comparing runs. No model weights or data are downloaded.

## Protocol

- Source files are sorted and split deterministically by SHA-256 of their normalized relative path: 80% train buckets, 20% held out. Files are never split across train and test.
- Output records Python/platform/library versions, seed, configuration, source-file hashes, byte counts, elapsed training/inference time, parameter count, BPB and an analytical estimate of GRU forward FLOPs per predicted byte.
- The n-gram model is trained on training files only. Held-out files are scored independently.
- Hybrid prediction mixes normalized probabilities: `p = alpha * p_gru + (1-alpha) * p_ngram`, with alpha in {0, 0.25, 0.5, 0.75, 1}. A smaller BPB is better.
- Evaluation currently scores deterministic prefixes from held-out files, not every held-out byte. This is an explicit runtime bound, not a full-corpus score.
- The split is by path, not by commit chronology. Similar code in different files can still leak patterns. The experiment is therefore exploratory and should later be repeated with repository/time-separated splits and multiple seeds.

## Interpretation guardrails

- The threshold of 1.713 BPB is only comparable if corpus, exact train/test files, byte encoding, context treatment, and scoring conventions match the historical experiment. This harness does **not** claim that equivalence.
- FLOPs are a formula-based estimate for GRU forward operations, not a hardware counter; training FLOPs and n-gram table-build work are not directly comparable yet.
- N-gram inference uses table lookups, but corpus preparation and model construction still consume CPU and memory.
- One seed/split cannot establish a robust win. A candidate hybrid only merits follow-up if it improves held-out BPB, remains within a declared compute budget, and later improves verified patch-task success.
- Results should be generated locally and reviewed before committing. Do not commit proprietary or sensitive repository contents; only the summary JSON and hashes should be shared.

## Current status

Harness only. No fresh BPB or FLOPs result is claimed until it is run against a named corpus and the JSON artifact is reviewed.
