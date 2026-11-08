# Benchmark audit: suite v2 (PR #15)

**Date:** 2026-10-23; protocol repair update 2026-11-08

**Worktree:** `C:\Users\lucas\AppData\Local\Temp\aurix-pr15`

**Branch:** `research/diffusion-first-test`

**Base:** `623afcd` (PR #15 head)

**Status:** protocol audited and repaired. No valid diffusion-vs-autoregressive comparison was possible.
The result is **inconclusive / blocked**.

The correction is committed on `research/diffusion-first-test`; no merge, deploy, or runtime
promotion was performed.

## 1. Question and scope

Can iterative parallel denoising reduce the total validated cost per correctly solved code task,
without reducing verified task success, relative to autoregressive generation under a comparable
inference budget?

This audit covers the benchmark protocol and the availability of a genuine code-diffusion arm.
It does not claim any model-performance result. The only model executions completed were two-task
harness smoke tests, described in section 5.

## 2. Protocol defects found and repaired

| # | Defect | Consequence | Repair | Regression coverage |
|---|---|---|---|---|
| 1 | `compare_arms.py` defaulted to the 3-task `suite.json` | A nominal full run could silently use the smoke suite | Default is now `suite/suite_v2.json`; `--suite` selects another file; `--expected-cases` refuses a size mismatch | suite tests |
| 2 | Analysis treated each repetition as an independent sample | Inflated confidence and false precision | Task-level success rates; paired task-cluster bootstrap; repetitions collapsed before resampling | `test_compare_arms_treats_repetitions_as_clustered_task_rates` |
| 3 | Primary metric was raw latency / wall time | Rewards fast failures and ignores retries | Primary metric is total arm wall seconds divided by correctly validated solutions; `null` at zero solutions | comparison output checks |
| 4 | Per-attempt raw evidence was incomplete | Results could not be re-audited | Every repetition writes a raw JSON report; all task rows go to `attempts.jsonl` | smoke and stub runs |
| 5 | Invalid JSON, timeouts, missing proposals, and harness errors could leave the denominator | Pass rate could be overstated | Every expected task gets one row per repetition; all abnormal statuses count as failures | invalid JSON, timeout, missing-proposal, duplicate-result paths |
| 6 | A stub could be mistaken for model evidence | Plausible-looking fake comparison | Stub arms require `--stub`; output is labeled `plumbing_only`; `real_model_comparison: false`; warning printed | `--stub` run |
| 7 | A model patch could edit the tests | Tasks could be solved by weakening assertions | Every task declares `allowed_patch_paths: ["calculator.py"]`; paths are validated before apply and rejected otherwise | `test_autonomous_benchmark_rejects_patch_to_test_file` |
| 8 | Gate 1 raised on a fixture timeout instead of returning a failure | A hung fixture aborted the gate | `TimeoutExpired` returns `False` | Gate 1 rerun |
| 9 | Single-arm runner defaulted to the 3-task suite | A 23-task run required remembering a flag | Defaults to `suite_v2.json`; `--suite` selects another file | suite tests |
| 10 | Suite identity was not checked across attempts | Arms could be compared on different inputs | Suite SHA-256 recorded per attempt; a mismatch is a protocol error and forces `inconclusive` | comparison output |
| 11 | A response without `status` was treated as a generic unsupported status and aborted immediately | A valid JSON envelope with a different shape became an undiagnosed failure | Strict parser distinguishes `missing_status`; one bounded format repair; second failure is still a failure | `tests/test_protocol.py` |
| 12 | Raw responses were unavailable for diagnosis | `invalid_json` was undecidable and could not be audited | Opt-in redacted local diagnostics (`AURIX_PROTOCOL_DIAGNOSTICS=1`), never production telemetry | `test_protocol_diagnostics_are_opt_in_and_redacted` |
| 13 | A provider timeout or transport error could abort the benchmark | One slow call could lose the whole run | Provider exceptions are recorded as `invalid_response` with type and redacted detail; the runner continues | `test_provider_failure_is_recorded_without_crashing` |
| 14 | Sampling was not pinned | The autoregressive baseline was not reproducible | `temperature=0.0` and `seed=0` in Ollama; other providers declare non-support explicitly | `tests/test_provider_ollama.py` |

The task fixtures are unchanged except for the new `allowed_patch_paths` field. The 23 tasks
remain synthetic single-file bug fixes; they can detect large differences, not broad coding ability.

## 3. Suite equivalence

`suite_v2.json` contains 23 unique task ids: the 3 original fixtures plus 20 generated fixtures.
The manifest is the single source of prompts, fixtures, expected baseline/candidate states, and
allowed patch paths. Both arms use the same manifest, so by construction they receive:

- the same task prompt and fixture copy;
- the same pytest command and test timeout;
- the same agent step limit and output/context limits;
- the same `allowed_patch_paths` restriction;
- a fresh disposable workspace for every task.

The harness enforces these settings, but the two-arm comparison itself was not run, so equivalence
was not exercised end to end across a real diffusion arm.

### Gate 1 results (final tree)

| Gate | Scope | Result |
|---|---|---|
| `build_suite_v2.py` | 20 generated fixtures: original fails, known-good passes, plausible-wrong fails | 20/20 OK |
| `selftest_harness.py` | 3 original fixtures: same three checks | 3/3 OK |
| Total | 23 fixtures | 23/23 OK |

Gate 1 validates fixtures and test commands. It is not model evidence and says nothing about
diffusion quality.

Logs:

- `C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-gate1-v2-post.log`
- `C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-gate1-original-post.log`

## 4. Diffusion-arm availability

A local inventory found no code-diffusion model or backend:

| Local model | Parameters | Quantization | Context | Format / runner | Decoding |
|---|---:|---|---:|---|---|
| `qwen2.5-coder:7b` | 7.6B | Q4_K_M | 32768 | GGUF / ggml | autoregressive |
| `qwen2.5:1.5b` | 1.5B | Q4_K_M | 32768 | GGUF / ggml | autoregressive |
| `llama3.2:1b` | 1.2B | Q8_0 | 131072 | GGUF / ggml | autoregressive |
| `deepseek-coder:6.7b` | 7B | Q4_0 | 16384 | GGUF / ggml | autoregressive |

The host has no PyTorch, Transformers, or Diffusers packages, no Hugging Face model cache in the
checked locations, and no usable CUDA stack. No OpenAI-compatible server exposing a diffusion
backend was listening on the usual ports.

The committed Stage A experiment does contain real iterative masked denoising (`gen_eval.py`,
K=2..32). It is a 0.876M-parameter byte language model trained on a private corpus: the corpus and
checkpoints are absent (`.gitignore`), it cannot produce code-agent patches, and it is explicitly a
mechanism-only result. It is not admissible as the code-diffusion arm and was not substituted.

The protocol's admission rule requires backend proof of iterative denoising and the actual step
count for each run. Neither can be recorded from an autoregressive chat endpoint. Therefore the
diffusion arm is missing, not merely slow.

## 5. What was executed

| Run | Tasks | Result | Cost | Classification |
|---|---:|---|---:|---|
| Offline stub comparison | 3 | 0/3 in both arms | about 5-9 s per arm | `plumbing_only`; not evidence |
| AR smoke, original protocol, `qwen2.5:1.5b` | 2 | 0/2 | 91.274 s total | harness smoke only; not performance evidence |
| AR smoke, repaired protocol, `qwen2.5:1.5b` | 2 | 0/2 | 399.8 s total | protocol smoke only; baseline pytest timed out; not performance evidence |
| Diffusion smoke | - | not run | - | blocked: no model |
| Full 23 x 10 comparison | 23 x 10 | not run | - | blocked |

The original AR smoke used `qwen2.5:1.5b`, not the intended `qwen2.5-coder:7b` arm. Both tasks
stopped at step 1 with `invalid_response`: one returned an unsupported status, the other invalid
JSON. No patch was produced.

The repaired-protocol smoke used the same model and suite. In both tasks the original response was
valid JSON without a top-level `status` (`missing_status`). The single bounded repair was
attempted; it returned 2,017 and 2,451 characters of truncated/invalid JSON (a degenerate patch
inside a `{"tool_call": ...}` envelope). Both cases correctly ended as `no_unique_proposal`.
Provider timeouts and protocol failures did not crash the runner. The pytest baselines timed out
at 30 s because the 8 GB host was under memory pressure with the model loaded, so this smoke is
protocol evidence only. After the smoke, the repair prompt was tightened to forbid generating a
patch during a format correction; that change is unit-tested and was not re-smoked.

Smoke configuration: Q4_K_M, 32768-token model context, harness context 8000, max output 768,
temperature 0, seed 0, max steps 6, test timeout 30 s, trusted isolation, CPU inference, one
request at a time. Hardware:
Intel i7-3537U (2 cores / 4 logical CPUs), 8 GB RAM, NVIDIA GT 730M 2 GB (unused), Windows 10
19045, Python 3.14.6, Ollama client 0.40.4.

Artifacts:

- `C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-stub-compare-2.json`
- `C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-ar-smoke.json`
- `C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-ar-smoke.log`
- `C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-fixed-smoke.json`
- `C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-protocol-diagnostics\aurix-protocol-diagnostics\`

The stub and smoke runs both have zero validated solutions, so "total validated cost per solved
task" is undefined (`null`) for them. No cost ratio is reported.

## 6. Repository test status

Focused tests pass:

```
python -m pytest tests/test_autonomous_benchmark.py tests/test_diffusion_research_suite.py -q
13 passed

python -m pytest tests/test_protocol.py -q
14 passed

python -m pytest tests/test_provider_ollama.py tests/test_provider_factory.py -q
8 passed

python -m pytest tests/test_orchestrator.py tests/test_telemetry.py \
  tests/test_diffusion_research_suite.py -q \
  -k "not test_orchestrator_can_propose_then_review_patch_without_applying_it"
39 passed
```

The excluded orchestrator test is the same Windows-only baseline failure documented below; it was
not introduced by this work.

The full suite is not green:

```
python -m pytest --tb=no -q
394 passed, 77 failed, 4 skipped
```

Failures by file: `test_patches.py` (55), `test_verification.py` (8), `test_audit.py` (8),
`test_provenance.py` (4), `test_orchestrator.py` (1), `test_rea_mcp.py` (1).

The same 77 failure ids occur on an untouched detached worktree at `623afcd`. The failure set is
identical, so these changes did not introduce them. They remain a repository-health issue and a
reason not to treat the tree as release-ready. Logs:

- `C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-pytest-current.log`
- `C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-pytest-baseline.log`

## 7. Deviations and threats to validity

- **Missing arm.** The central comparison was not run. No statement about H1, H2, or H3 is
  supported.
- **No denoising-step evidence.** The required step count could not be recorded because no
  diffusion backend exists locally.
- **Hardware.** Two CPU cores and 8 GB RAM are far below a meaningful code-model benchmark host.
  The 7B code model was not run; memory pressure and latency would be severe.
- **No OS sandbox.** The smoke used `trusted` isolation. Docker isolation was not exercised, and
  trusted mode is explicitly not a sandbox.
- **Threads not pinned.** Ollama chose its own CPU thread count. A strict comparison should pin
  threads and record the setting for both arms.
- **Wall-clock cost.** The metric includes test execution, fixture copying, and harness overhead.
  This is appropriate for total validated cost but is sensitive to machine load; it is not an
  energy or FLOP measurement.
- **Small task set.** Twenty-three synthetic tasks give coarse task-cluster intervals. Even a
  complete run would support only large-effect conclusions.
- **Smoke model mismatch.** Both smokes used a general 1.5B model, not the intended 7B code model.
  Their 0/2 results must not be presented as the autoregressive arm's performance.
- **Invalid smoke baselines.** In the repaired-protocol smoke, the pytest baselines timed out at
  30 s while the model was loaded on the 8 GB host. The task results are protocol evidence only,
  not a performance measurement.
- **Repair prompt changed after the smoke.** The final repair prompt forbids generating a patch
  during a format correction. It is covered by unit tests but was not exercised by a real model
  after the change, because a rerun reproduced severe memory contention.
- **Stage A is not a substitute.** Its diffusion result is mechanism-only, at 0.88M parameters,
  and cannot generate patches.

## 8. Exact commands

Gate 1, from the repository root:

```powershell
python research/diffusion-agent-benchmark/build_suite_v2.py
python research/diffusion-agent-benchmark/selftest_harness.py
```

Focused tests:

```powershell
python -m pytest tests/test_autonomous_benchmark.py tests/test_diffusion_research_suite.py -q
```

Full suite:

```powershell
python -m pytest --tb=no -q
```

Focused protocol tests:

```powershell
python -m pytest tests/test_protocol.py tests/test_provider_ollama.py -q
```

Offline stub (plumbing only):

```powershell
python research/diffusion-agent-benchmark/compare_arms.py --confirm --stub `
  --suite research/diffusion-agent-benchmark/suite/suite.json --expected-cases 3 --repeats 1 `
  --arm "stubA,stub,," --arm "stubB,stub,," `
  --output C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-stub-compare-2.json
```

AR smoke (repaired protocol):

```powershell
$env:AURIX_PROVIDER='ollama'
$env:AURIX_MODEL='qwen2.5:1.5b'
$env:AURIX_MAX_OUTPUT_TOKENS='768'
$env:AURIX_CONTEXT_TOKENS='8000'
$env:AURIX_TEMPERATURE='0'
$env:AURIX_SEED='0'
$env:AURIX_PROTOCOL_DIAGNOSTICS='1'
$env:AURIX_PROTOCOL_DIAGNOSTICS_DIR='C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-protocol-diagnostics'
python research/diffusion-agent-benchmark/run_autonomous_suite.py --confirm --provider ollama `
  --suite C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-smoke-suite\suite.json `
  --timeout 30 --max-steps 6 --protocol-diagnostics `
  --output C:\Users\lucas\AppData\Local\Temp\opencode\aurix-pr15-fixed-smoke.json
```

The intended full comparison, not run:

```powershell
python research/diffusion-agent-benchmark/compare_arms.py --confirm `
  --suite research/diffusion-agent-benchmark/suite/suite_v2.json --expected-cases 23 `
  --repeats 10 --isolation docker --sandbox-image <reviewed-local-image> `
  --arm ar,ollama,,qwen2.5-coder:7b `
  --arm diff,openai-compatible,http://localhost:1235/v1,<verified-diffusion-model> `
  --note "model versions; quantization; backend proof; exact denoising steps; threads; context"
```

## 9. Unblock conditions

1. Obtain a verified code-diffusion checkpoint and serving backend that exposes per-run denoising
   steps and can implement the `Provider.generate` protocol.
2. Record model name/version, quantization, backend, hardware, thread count, context limit,
   generation limit, and actual denoising step count for both arms.
3. Pin threads and use Docker isolation with a reviewed image, or explicitly accept and document
   trusted-mode risk.
4. Re-run Gate 1, then a 2-3 task smoke, then 23 tasks x 10 repetitions per arm.
5. Resolve or explicitly waive the 77 pre-existing repository test failures.

## 10. Conclusion

**Inconclusive / blocked.** The protocol now has task-clustered uncertainty, a validated-cost
metric, raw per-attempt evidence, protection against test tampering, a strict response parser,
one bounded repair, and opt-in redacted diagnostics. Gate 1 passes 23/23. The repaired-protocol
smoke exercised the missing-status path and counted truncated repair output as failure without
crashing. However, no genuine code-diffusion arm is available, no denoising step count can be
recorded, and no two-arm benchmark was run. The stub and smoke runs produced zero validated
solutions and are not evidence of model performance. No conclusion about diffusion versus
autoregressive code generation is supported.
