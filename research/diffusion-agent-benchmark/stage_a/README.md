# Stage A + B-lite: autoregressive vs masked-diffusion byte LM (first measured result)

Scope: mechanism check only (protocol Stage A, plus a reduced Stage B). **Not** a coding-agent benchmark and
**not** evidence about provider-scale models. CPU, float32, 1 thread, 2-CPU sandbox.

## Controls
- Same Transformer (4 layers, d=128, 0.876M params, identical for both); only the attention mask differs
  (causal vs bidirectional). Same frozen private code corpus (419 train / 46 val files, file-level split,
  exact + head-duplicate removal), same windows (128 bytes), batch 32, 1500 steps, AdamW, cosine schedule.
- Learning rate tuned **per variant** over {1e-3,2e-3,4e-3,8e-3,1.6e-2}, seed 0 (AR best 8e-3, diffusion best 4e-3;
  both optima are interior). 3 seeds at the best lr. Corpus is not committed (private code); `corpus_frozen.pkl`
  is the input expected by `stage_a.py`.
- Diffusion = absorbing-state masked diffusion (MDLM-style ELBO, stratified t). Its bpb is an **upper bound**
  on NLL (8 fixed t values on val); AR bpb is exact. They are not strictly the same quantity.

## Language-model diagnostic (val bits/byte, lower is better)
| budget | AR | masked diffusion |
|---|---|---|
| 1500 steps, 3 seeds | 1.572 / 1.575 / 1.586 (mean 1.578) | 4.744 / 4.879 / 4.630 (mean 4.751) |
| 6000 steps, seed 0 only | 1.323 | 3.842 |

Diffusion improves with 4x more training (4.74 -> 3.84) but is still ~2.9x worse in bpb; AR starts overfitting
at 6000 steps (train 0.89 vs val 1.32). Note the ELBO bound is loose, so the real gap in likelihood is smaller than
these numbers, but it cannot be quantified from this experiment.

## Completion quality and batch-1 latency (seed 0, 200 held-out prompts: 96-byte prompt -> 32 bytes, greedy)
AR uses a KV cache; diffusion re-runs a full bidirectional pass per step and unmasks the n/K most confident bytes.
Latency: median/p90 over 5 repetitions on the first 20 prompts, after warm-up (two evaluations shared the 2 CPUs).

| decoder (1500-step models) | forward passes | byte accuracy | first-8 accuracy | exact-32 | median ms | p90 ms |
|---|---|---|---|---|---|---|
| AR | 32 | 0.148 | 0.323 | 0.5% | 37.9 | 43.0 |
| diffusion K=2 | 2 | 0.133 | 0.112 | 0% | 9.7 | 11.4 |
| diffusion K=4 | 4 | 0.134 | 0.116 | 0% | 18.8 | 22.7 |
| diffusion K=8 | 8 | 0.134 | 0.114 | 0% | 36.4 | 44.0 |
| diffusion K=16 | 16 | 0.133 | 0.113 | 0% | 74.1 | 87.6 |
| diffusion K=32 | 32 | 0.133 | 0.113 | 0% | 140.4 | 159.6 |

The 6000-step models give the same picture (AR 0.156 / first-8 0.349 at 36.6 ms; diffusion K=2..32: 0.134-0.140
byte accuracy, first-8 0.129-0.145; `results/gen_eval_long.json`).

## What this does and does not show
- H1 (latency): per forward pass diffusion costs ~4.5 ms vs ~1.2 ms per cached AR step, so the break-even is about
  K=8 passes for 32 bytes. Diffusion is faster only with K<8 (K=2: 3.9x, K=4: 2x), where it is also worst in quality.
  Extra steps do **not** improve diffusion quality here (flat from K=2 to 32), i.e. the denoising iterations are not
  being used productively by this under-trained model.
- H2 (quality): at equal training budget the AR model is better on every quality measure; the 5-point
  non-inferiority margin is **not met** (first-8 accuracy gap ~21 points; byte accuracy gap ~1.5 points, where byte
  accuracy is dominated by easy bytes such as whitespace and is a weak metric).
- H3 (verified task success) is **not tested**: these models are far too small to produce test-passing patches.
- Caveats: one scale (0.88M params), small corpus, single-seed generation metrics, exact-32 has no resolution,
  no comparison against a strong diffusion recipe (e.g. confidence-based remasking, longer training, learned
  schedules). The result says "masked diffusion is much harder to train to AR quality at this scale", not
  "diffusion cannot work"; published diffusion LMs report competitive results only with substantially more compute.

## Harness gate 1 (protocol)
`../selftest_harness.py`: for each of the 3 suite fixtures the original fails, a known-good patch passes and a
plausible wrong patch fails (3/3 OK). It exercises the fixtures and test commands, not the AURIX provider path.

## Reproduce
```
python stage_a.py train --mode ar   --lr 8e-3 --seed 0 --steps 1500 --out results/ar_lr8e-3_s0.json
python stage_a.py train --mode diff --lr 4e-3 --seed 0 --steps 1500 --out results/diff_lr4e-3_s0.json
python -c "import gen_eval as g; g.main('results/ar_lr8e-3_s0.pt','results/diff_lr4e-3_s0.pt')"
```
Raw per-run JSON (`results/*.json`) and logs are committed; checkpoints (`*.pt`) and the corpus are not.
torch 2.14.1, 2 CPU cores, 1 thread per process.
