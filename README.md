# AURIX

**Open, local-first AI engineering agent.** AURIX is an open-source project to build an agent that can inspect software projects, plan changes, use tools safely, run tests, and learn from measured outcomes—with no paid API required by default.

> Status: v0.85.0 research release; REA CLI investigation commands are allowlisted; not production-ready autonomous software engineering.

## Principles
- **Local-first:** local inference first; remote providers are optional adapters.
- **Tool-grounded:** prefer deterministic tools over unnecessary model calls.
- **Safe by default:** narrow workspace boundaries, command allowlists, bounded execution.
- **Measured, not hyped:** optimize only when reproducible evaluations show improvement.
- **Open and modular:** providers, memory backends, and tools are replaceable.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
python -m aurix.cli --doctor --workspace .
```

### Run AURIX without paid API tokens (default)

AURIX defaults to **Ollama on your own computer**. Inference happens on local hardware, so no hosted API key or paid token account is required. You still need enough RAM/VRAM and local compute; this is not zero-energy computing.

1. Install [Ollama](https://ollama.com/).
2. Download a model once (this requires an internet connection and disk space):

```bash
ollama pull qwen2.5-coder:7b
```

3. Ensure the Ollama service is running, then install and start AURIX:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m aurix.cli --doctor --workspace .
```

The default configuration is:

```dotenv
AURIX_PROVIDER=ollama
AURIX_BASE_URL=http://localhost:11434
AURIX_MODEL=qwen2.5-coder:7b
AURIX_API_KEY=
```

Model quality and speed depend on your hardware and the selected model. Smaller quantized models may run on modest hardware but can be less capable. The first model download is not part of inference and uses storage/bandwidth.

### Optional inference engines

You can instead configure a local OpenAI-compatible server such as [LM Studio](https://lmstudio.ai/), [llama.cpp server](https://github.com/ggml-org/llama.cpp), or [vLLM](https://docs.vllm.ai/):

```dotenv
AURIX_PROVIDER=openai-compatible
AURIX_BASE_URL=http://localhost:1234/v1
AURIX_MODEL=your-loaded-model-name
AURIX_API_KEY=
```

Hosted compatible APIs are also possible, but are **opt-in** and may cost money. AURIX does not silently switch from a local model to a hosted provider if local inference fails. Provider selection lives behind one interface.

**Can we build our own model?** Yes, incrementally: first our own orchestration, evaluation, memory, retrieval, tool-use and inference runtime; later fine-tune an open-weight model on licensed data if benchmarks justify it. Training a competitive foundation model from scratch is a separate, expensive research effort—not something solved by changing the inference server.

Run `aurix --doctor --workspace .` for read-only environment checks. Add `--probe-provider` to send a live test prompt; this can consume compute or API credits. Probe output suppresses raw model responses and exception details.

The CLI has a bounded tool loop for file listing, reading, and literal text search. It can also save proposed unified diffs for review. In v0.4, a proposal can be applied or reversed only through a separate CLI operation with an explicit confirmation flag; v0.5 adds an explicitly approved, fixed-command test/lint runner with a timeout and reduced environment; v0.6 can verify a proposal in a disposable Git worktree without changing the primary checkout; application requires a clean tracked Git worktree and only supports in-place edits to existing tracked regular files. This is not a sandbox and is not production-ready for untrusted repositories.

### Autonomous patch-generation benchmark (v0.38.0)

The autonomous benchmark asks the configured model to inspect a known-defect fixture and create a proposal using the regular `propose_patch` tool. AURIX then applies that proposal only to a disposable candidate copy and runs the fixed pytest suite against both the baseline and candidate. The original fixture remains unchanged.

```bash
aurix --autonomous-benchmark benchmarks/autonomous-smoke/suite.json \
  --confirm-autonomous-benchmark --json
```

The command can incur model compute/API costs and executes fixture tests. The default `trusted` mode runs on the host and is not a sandbox; use `--test-isolation docker --sandbox-image IMAGE` with an already-present, operator-reviewed image for stronger isolation. Docker failures do not fall back to host execution. A benchmark pass means only that the configured tests and expectations passed; it is not a proof of semantic correctness. Unit tests use a simulated provider; live-model evaluation is not claimed.

### Functional patch benchmark (v0.37.0)

A separate functional benchmark can test a supplied patch against a known-defect fixture. It runs the fixed pytest suite on a disposable baseline copy, applies the supplied diff to a second disposable copy, then runs the same suite. A demonstrated fix means the baseline fails and the candidate passes. This evaluates a supplied patch; it does not yet measure autonomous model-generated fixes.

```bash
# Executes code from the fixture; review the fixture and patch first.
aurix --functional-benchmark benchmarks/functional-smoke/suite.json \
  --confirm-functional-benchmark --json
```

Trusted execution runs tests on the host and is not an OS sandbox. For stronger isolation, add `--test-isolation docker --sandbox-image YOUR_REVIEWED_LOCAL_IMAGE`; the image must already exist locally. The primary fixture remains unchanged; only disposable copies are tested. Test success proves only the behavior covered by the tests.

### Evidence-aware benchmark reports (v0.36.0)

Run each acceptance case repeatedly, save the report, and compare later runs against it. Reports include a normalized suite SHA-256 fingerprint and runtime/provider metadata; comparison requires the same suite and repetition count.

```bash
# Capture a baseline report
aurix --benchmark benchmarks/smoke.json --benchmark-repetitions 3 \
  --benchmark-output artifacts/baseline.json --json

# Run again and compare against the baseline
aurix --benchmark benchmarks/smoke.json --benchmark-repetitions 3 \
  --benchmark-compare artifacts/baseline.json \
  --benchmark-output artifacts/comparison.json --json
```

The comparison is descriptive, not a significance test. Hold model/provider, prompt configuration, hardware, and runtime settings constant where possible. Criteria-based acceptance and estimated token counts do not establish semantic correctness or billing cost.

### Project inventory and Git inspection (v0.25.0)

### Context, token budgets, and cache (v0.39.0)

The orchestrator bounds approximate input context, preserving the task header and most recent evidence when older history must be compacted. The estimate is deliberately conservative and language-agnostic; provider tokenizers and server-side context limits remain authoritative. OpenAI-compatible providers receive `max_tokens`, and Ollama receives `options.num_predict`.

- `AURIX_CONTEXT_TOKENS=12000`: approximate total input context budget.
- `AURIX_CONTEXT_RESERVE_TOKENS=1000`: reserve for system prompt and safety margin.
- `AURIX_MAX_OUTPUT_TOKENS=2048`: maximum requested generation tokens, clamped to 1–32768.
- `AURIX_CACHE_ENABLED=true`: enable a process-local LRU cache for terminal responses only.
- `AURIX_CACHE_MAX_ENTRIES=128`: maximum cached responses.
- `AURIX_CACHE_TTL_SECONDS=300`: cache lifetime.

The cache never stores tool-call responses, is memory-only, and keys entries by provider/model, exact prompt, and a workspace file metadata fingerprint. Any detected workspace change invalidates a prior answer. Cache hits are still limited to exact prompt matches; disable with `AURIX_CACHE_ENABLED=false` when responses must always be freshly generated. Token counts are estimates, not provider billing figures. Context compaction is visible in trace/telemetry.

### Large-document analysis (v0.40.0)

AURIX can extract and hierarchically summarize large documents without putting the entire source into a single model prompt. PDF extraction uses `pypdf`; install it with `pip install 'aurix-agent[documents]'`. Text/Markdown and common text-based formats use the standard library. Scanned PDFs need OCR preprocessing; OCR is not bundled.

```bash
aurix --analyze-document ./technical-report.pdf --document-output ./report-analysis.json --document-workers 4 --json
```

The pipeline extracts text locally, creates bounded page-aware chunks, summarizes chunks concurrently, repeatedly reduces intermediate summaries, and produces an executive brief with source-page references, risks, dates/numbers, and open questions. The JSON report includes source SHA-256, extractable character count, chunk count, model-call count, and per-chunk summaries. The input document is not modified. Document content is treated as untrusted input, and model conclusions must be checked against cited pages.

- `--document-chunk-chars`: chunk size in characters (2,000–80,000; default 24,000).
- `--document-workers`: concurrent model calls (1–16; default 4). Tune this to provider rate limits and local hardware.
- `--document-output`: persist the full JSON report.
- `--json`: print the full JSON result.

For PDFs, page references refer to source PDF pages. For text formats, page references are logical segments rather than printed page numbers. Runtime depends on extraction speed, model latency, provider rate limits, document density, and whether OCR is needed; no fixed processing-time guarantee is implied.

Current package version: **0.85.0**.

The agent can map project ecosystems, manifests, test-file locations, CI configuration, source-file counts, and package-script names before proposing a change. This inventory is structural only: it does not execute tests or scripts. Git status and diff inspection are also available in the bounded tool loop.

### REA reverse-engineering integration (v0.23.0)

AURIX can delegate static JavaScript/Electron application analysis to the upstream
[REA — Reverse Engineer Anything](https://github.com/morluto/rea) CLI. REA remains
a separate MIT-licensed tool; AURIX does not copy or fork its implementation.
Install Node.js and REA using the upstream instructions, then ensure `rea` is on
`PATH` (or set `AURIX_REA_BIN` to the executable).

When useful, the model can request the `rea_analyze_app` tool for a directory or
`.asar` file inside the configured AURIX workspace. It calls
`rea analyze-javascript-application TARGET --json`, passes a reduced environment,
uses no shell, caps execution at 120 seconds, and bounds returned output. The
static analysis does not launch the target application. Targets outside the
workspace and unsupported file types are rejected.

```bash
npm install --global rea-agents
rea --help
aurix --workspace . "Inspect the Electron application in ./desktop-app" --json
```

The `rea_analyze_app` adapter covers the static JavaScript/Electron workflow.
A separate, restricted MCP workflow for native binary overview is described
below; neither integration exposes the full REA catalog, browser runtime capture,
or process tracing. Those capabilities require additional explicit adapters and
upstream prerequisites. REA must be installed separately; AURIX does not silently
download it or run `npx` during a task.


### Optional Docker-isolated test execution (v0.33.0)

AURIX can run its fixed `pytest`/`ruff` commands inside an operator-selected Docker image, with network disabled, a read-only container root filesystem, dropped Linux capabilities, process/memory/CPU limits, and only the workspace mounted writable. It checks that the image is already local and uses `--pull=never`; it will not download an image or fall back to host execution. The image must already contain the project dependencies and test tools. The Docker daemon and image remain part of the trust boundary; this is defense-in-depth, not a claim of perfect isolation.

Example (image must be built/pulled by the operator first):

```bash
aurix --workspace . --run-tests pytest --confirm-run-tests \
  --test-isolation docker --sandbox-image aurix-test:local --json

aurix --workspace . --verify-proposal a1b2c3d4e5f6 --confirm-verify \
  --test-isolation docker --sandbox-image aurix-test:local --json
```

The default `trusted` mode is unchanged and is not an OS sandbox. This optional Docker backend was tested with mocked Docker CLI calls in this environment; a live Docker run was not possible here.

### Baseline-aware proposal verification (v0.32.0)

When an operator enables agent verification, AURIX can run the fixed test suite on the clean baseline and then on the proposed patch in a disposable Git worktree. The result distinguishes `clean`, `introduced_failure`, `improved`, `preexisting_failure_persists`, and `not_compared`. Baseline comparison is enabled by default and runs tests twice, so it costs more time. This is regression evidence, not proof of semantic correctness. Tests are not OS-sandboxed and must only run against trusted repositories.

### Iterative proposal verification (v0.31.0)

When agent verification is enabled, the model receives test results in its next context. A failed proposal is treated as immutable for that run: the orchestrator rejects attempts to verify the same failed proposal again, prompting the model to create a new diff. Verification outcomes and process exit codes are recorded in the trace when available. This is a bounded model-directed repair loop, not proof of semantic correctness; tests still run without OS-level sandboxing.

### Opt-in agent verification (v0.29.0)

When launched with `--allow-agent-verification`, the model is explicitly informed that it may call `verify_proposal` with a stored proposal ID and a fixed `pytest` or `ruff` suite. Without this flag, the tool is omitted from the model-facing tool instructions and rejected by the orchestrator. Verification runs in a disposable Git worktree, but it is not an OS sandbox and must only be enabled for trusted repositories.

### Direct REA MCP transport (v0.28.0)

AURIX can now use REA's stdio JSON-RPC MCP server for a restricted native-binary
investigation workflow. The `rea_mcp_investigate` tool launches the already
installed `rea mcp` executable (no `npx`, auto-download, or shell), initializes
the MCP connection, discovers the live tool catalog, then calls only
`open_binary` and `binary_overview`. The target must be a regular file inside
the configured workspace. The analyzed target is not launched by AURIX; native
analysis may launch or connect to a configured provider such as Ghidra or Hopper.
The MCP process is bounded by a timeout and stopped after the workflow. This is
a first narrow MCP integration, not unrestricted access to the full REA catalog.

REA remains an optional external dependency. Install and configure it separately,
then run AURIX against a trusted target. MCP behavior is covered with protocol
fixtures; this release does not claim a live Ghidra/Hopper integration test.

### Heuristic patch review (v0.8)

Before applying a proposal, run a deterministic scan over added diff lines:

```bash
aurix --workspace . --review-proposal a1b2c3d4e5f6 --json
```

The scanner flags selected patterns such as dynamic code execution, subprocess/shell use, unsafe deserialization, hard-coded credential-like strings, disabled TLS verification, broad file permissions, and possible SQL interpolation. It is a triage aid, not a security analyzer: it may produce false positives and miss vulnerabilities. Even a `low` result does not authorize or apply the patch; review and test it manually.

### Audit evidence integrity (v0.16)

Audit attachment is accepted only when the existing run report digest verifies and the referenced proposal SHA-256 matches the exact proposal file currently stored under `.aurix/proposals`. Audit metadata is validated before the report is changed; invalid booleans, risk levels, verification states, or finding counts are rejected. This binds the audit record to the current patch bytes, but SHA-256 alone is not a digital signature and does not authenticate the author.

```bash
aurix --workspace . --audit-proposal a1b2c3d4e5f6 \
  --attach-audit-to-report reports/run.json --json
```

The report must already exist and pass integrity verification. Use `--confirm-audit-verify` only when you explicitly authorize execution of repository tests.

## Persistent memory (v0.22.0)

SQLite is the zero-setup default. Memory is opt-in: AURIX does not automatically persist task prompts or model completions as memories. Add and search records explicitly, scoped by repository or project:

```bash
# Store a deliberately selected fact in a scope
aurix --workspace . --memory-add "Auth tests require a seeded user" --memory-scope repo:my-project --memory-kind fact --memory-confidence 0.95 --json

# Search only that scope
aurix --workspace . --memory-search "auth tests" --memory-scope repo:my-project --json
```

Set `AURIX_MEMORY_BACKEND=postgres`, `DATABASE_URL` to a Neon/PostgreSQL connection string, and install `pip install -e ".[neon]"` to use Neon. You can select `--memory-backend sqlite` or `--memory-backend postgres` per command. The default SQLite database is `<workspace>/.aurix/memory.db`; `AURIX_MEMORY_PATH` can override its path. Scope is a logical filter, not an authorization boundary: do not share one database between mutually untrusted users without adding access controls. Neon stores memory; it does not perform model inference.

To include relevant saved memories in a task prompt, explicitly enable contextual memory:

```bash
aurix --workspace . --memory-scope repo:my-project --use-memory-context \
  "Inspect the authentication flow" --json
```

Context retrieval is disabled by default. When enabled, AURIX retrieves only records in the selected scope, includes at most 10 bounded records, and labels them as untrusted evidence rather than instructions. The labels and confidence values are descriptive metadata and are not independently verified. Scope is a logical filter, not an authorization boundary.

## Development

```bash
pytest
ruff check .
```

See `docs/ARCHITECTURE.md`, `docs/SAFETY.md`, and `CONTRIBUTING.md`.

## Roadmap
1. Reproducible baseline and evaluation task format.
2. Provider-independent tracing and adapters for compatible local and hosted inference servers.
3. Bounded read-only tool loop for repository listing, file reads, and text search.
4. Reviewable patch proposals, explicitly confirmed application/reversal, and fixed-command test/lint execution with timeout. OS-level sandboxing remains future work.
5. Persistent memory and measured retrieval quality.
6. Multi-agent verification only if ablation benchmarks prove useful.
7. Public benchmarks for quality, latency, memory, and API/model cost.

## License
Apache-2.0, pending a final dependency and model-license audit before public release.

## Run a repeatable smoke benchmark

The benchmark runner supports explicit acceptance criteria: `must_contain`, `must_not_contain`, `expected_status`, `required_tools`, `forbidden_tools`, `min_steps`, and `max_steps`. Reports show per-criterion results, tool usage, latency, and rough output-token estimates. Use `--benchmark-repetitions 3` to run each case three times (valid range 1–10) and report aggregate pass rate, stable passes, mean/median latency, and total estimated output tokens. Repeated calls may incur extra compute/API cost. It is a regression aid, **not** a measure of semantic correctness or general reasoning quality; token estimates use characters/4 and must not be treated as tokenizer counts or provider billing. Existing smoke cases remain compatible.

```bash
aurix --benchmark benchmarks/smoke.json --json
```

By default, metadata-only run telemetry is appended to `.aurix/runs.jsonl`. Prompts and completions are not written to this file. Disable persistence by injecting a custom telemetry implementation in Python; telemetry path can be changed with `AURIX_TELEMETRY_PATH`.


### Reviewable patch proposals

AURIX can prepare a unified diff using the `propose_patch` tool. The diff is saved under `.aurix/proposals/` and marked for manual review; **the agent does not apply it automatically**. Inspect every proposal before applying it yourself. The proposal writer rejects absolute paths, parent-directory traversal, and symlinked metadata directories, but a proposal is still untrusted input and must be reviewed before use.

### Applying a reviewed patch proposal (v0.4)

Review the full diff first. The agent never applies it during reasoning. Only after review, use the proposal ID shown by AURIX:

```bash
aurix --workspace . --apply-proposal a1b2c3d4e5f6 --confirm-apply
# If the exact reverse patch still applies cleanly:
aurix --workspace . --revert-proposal a1b2c3d4e5f6 --confirm-revert
```

The operation requires Git, a clean tracked worktree for application, and an existing tracked file for every target. It refuses additions/deletions, renames, binary patches, unsafe paths, symlinks, sensitive filenames, and patches that fail Git's preflight. Reversal is a new patch operation, not a guaranteed restoration if other edits have changed the same lines. Back up important work and inspect `git diff` after every operation. This remains defense in depth, not a security sandbox.


### Explicitly approved test execution (v0.5)

Run a fixed test or lint command in a workspace you trust:

```bash
aurix --workspace . --run-tests pytest --confirm-run-tests --json
aurix --workspace . --run-tests ruff --confirm-run-tests --json
```

Only the fixed commands `python -m pytest -q` and `python -m ruff check .` are available; model-provided arguments are never executed. Runtime is capped at 120 seconds, output is bounded, and common credential/application environment variables are not passed to the child process. **This is not a sandbox:** test code may still read files, access the network, or perform other actions available to the OS user. Only run tests from repositories you trust. The command is never called automatically by the model.


### Verify a proposal before applying it (v0.6)

AURIX can apply a proposal to a temporary detached Git worktree, run a fixed test or lint suite there, and remove the temporary worktree afterward. The primary checkout remains unchanged. This is a useful preflight, but **not an OS-level sandbox**: test code can still access resources available to the OS user. Run only against trusted repositories and review the patch even when tests pass.

```bash
aurix --workspace . --verify-proposal a1b2c3d4e5f6 --confirm-verify --verify-suite pytest --json
# Or check lint instead of tests:
aurix --workspace . --verify-proposal a1b2c3d4e5f6 --confirm-verify --verify-suite ruff --json
```

Verification requires a clean tracked worktree and an existing proposal ID. A successful result means the selected suite passed in the temporary worktree; it does not establish correctness, security, or absence of regressions beyond that suite.


### Strict model response protocol (0.9.0)

AURIX now fails closed when a provider returns malformed JSON, a non-object JSON value, an unsupported status/tool, non-string message content, invalid tool arguments, or a response over 100,000 characters. Such responses are marked `invalid_response` and do not execute a tool. This reduces accidental or model-induced protocol ambiguity; it is not a security sandbox and does not establish the correctness of model output.


### Local run reports (v0.11.0)

Use `aurix "Inspect the authentication flow" --workspace . --report-run reports/auth-review.json` to explicitly save a JSON report under the workspace. The report includes the task text, status, run ID, and trace metadata, but not raw prompts, model completions, or tool-result bodies. Report paths must be relative to the workspace; traversal and symlink destinations are rejected. Do not use this option for tasks whose text should not be persisted.


### Proposal-linked run reports (v0.11.0)

Run reports use schema version 2 and include a metadata-only `artifacts.proposals` index for proposals created during the task. The trace stores proposal IDs and bounded status labels, not patch bodies or raw tool results. Reports remain opt-in via `--report-run PATH`; the task text is included in the report.


### Combined proposal audit (v0.12.0)

Run `aurix --audit-proposal PROPOSAL_ID --workspace . --json` to combine heuristic diff review with an explicit record that verification was not run. To also run the selected fixed test suite in a disposable Git worktree, add `--confirm-audit-verify`; choose `--verify-suite pytest` or `--verify-suite ruff`. Verification executes repository code and is not an OS sandbox. The combined audit never applies the patch and never treats high-risk findings as a passing audit, even if tests pass.


### Linking proposal audits to run reports (v0.15.0)

After a task has written a schema-v2 run report, attach a proposal audit to it:

```bash
aurix --audit-proposal PROPOSAL_ID --workspace . --attach-audit-to-report reports/auth-review.json --json
```

To also execute the configured fixed suite in a disposable Git worktree, add `--confirm-audit-verify`. The report attachment stores compact metadata including the SHA-256 digest of the reviewed patch, UTC audit time, risk level, finding count, verification status and suite. It intentionally excludes full findings and raw test output. The run report must already exist and must be schema version 2. Verification is not an OS sandbox, and audits never apply patches.


### Run report integrity (v0.15.0)

Reports written with `--report-run` include a canonical SHA-256 digest. Verify an existing report without modifying it:

```bash
aurix --workspace . --verify-run-report reports/auth-review.json --json
```

Verification reports `valid`, `tampered`, or `missing_integrity` (for older reports). This is a tamper-evident checksum, not a digital signature: someone who can rewrite the report and recompute its digest can forge it. Keep reports in a trusted workspace and use external signed storage if authenticity is required.


### Audit attachment integrity (v0.15.0)

Audit attachment now verifies the existing schema-v2 report digest before modifying it and refuses to silently recalculate integrity for tampered or legacy reports. Each successful new attachment preserves the prior digest in a compact `integrity_history` entry and reports the previous/current digests. Duplicate attachment of the same proposal digest and audit timestamp is idempotent. This is local tamper detection, not a signature or an externally anchored immutable log.



### Evidence-aware memory records (v0.20.0)

Memory records may include a validated `kind` (`fact`, `hypothesis`, `decision`, `test_result`, or `observation`) and optional numeric `confidence` from `0.0` to `1.0`. These labels preserve provenance/epistemic status; they do not independently verify a claim. Existing records and custom metadata remain compatible. Example:

```bash
aurix --workspace . --memory-add "Regression test passed on commit abc123" \
  --memory-kind test_result --memory-confidence 1.0 --memory-scope repo:my-project --json
```

Confidence is user-supplied metadata, not a calibrated model probability.

### Memory retrieval (v0.19.0)

Memory search ranks recent records in the selected scope by deterministic lexical overlap; it is not embedding-based semantic retrieval. Results are bounded by `--memory-limit`, `--memory-candidates`, and `--memory-max-content-chars`. Example:

```bash
aurix --workspace . --memory-search "authentication regression" \
  --memory-scope repo:my-project --memory-limit 5 --json
```

A memory scope is a logical filter, not an authorization boundary. Do not share a database across mutually untrusted users without a separate authorization layer.


### Hybrid memory retrieval (v0.20.0)

The Python API `retrieve_memories(..., embedder=adapter, lexical_weight=0.65)` can combine lexical overlap with an injected embedding adapter implementing `embed(text) -> sequence[float]`. No embedding provider or model is bundled or selected automatically; without an adapter, the CLI remains lexical-only and reports `semantic_search: false`. Embedding failures and vector dimension mismatches raise errors rather than silently falling back. Candidates are still bounded to recent records in the requested scope. `evaluate_retrieval` reports precision@k, recall@k and reciprocal rank against manually labeled record IDs; it is a measurement helper, not proof that semantic retrieval is better.


### Memory evidence traceability (v0.22.0)

When `--use-memory-context` is enabled, task JSON output includes `memory_context.evidence`: compact provenance for the records retrieved (ID, scope, kind, retrieval mode, relevance score, and matched terms). Explicit run reports also store this metadata, covered by the report integrity digest. Memory text is not copied into the provenance trace, and memory use remains opt-in.

### Opt-in agent-driven verification

By default, the model cannot trigger test execution. For a repository you trust, pass `--allow-agent-verification` to let the agent request verification of a stored patch proposal using the fixed `pytest` or `ruff` suite. Verification runs in a disposable Git worktree and returns structured results to the agent, enabling a test-feedback/revision loop without changing the primary checkout. This is **not an OS sandbox**: tests can access available filesystem and network resources. Do not enable it for untrusted repositories.


### REA investigation commands (v0.27.0)

In addition to static JavaScript/Electron analysis, the model may request `rea_investigate` for the allowlisted REA CLI commands `analyze`, `search`, `function`, `decompile`, `xrefs`, `trace`, `providers`, and `capabilities`. Target paths are workspace-relative and bounded output is returned as structured evidence when possible. No shell is used and analyzed targets are not launched. Native analysis requires REA and a compatible provider configured separately. The separate native investigation workflow now uses direct MCP stdio transport for a restricted `open_binary` → `binary_overview` sequence; it still does not expose unrestricted access to the full REA MCP catalog.


### Evidence-aware benchmark criteria (v0.36.0)

Benchmark cases may require that the agent create a patch proposal (`require_patch_proposal`), successfully verify a proposal (`require_successful_verification`), and observe one of the specified `expected_regression_statuses`. These checks use tool trace metadata; they do not independently prove semantic correctness or replace a task's executable acceptance tests. Benchmark report schema is now version 5.

### Functional patch evaluation (v0.37.0)

The functional suite manifest is a JSON array with unique `id`, relative `fixture` and `patch` paths, and boolean `expect_baseline_passed` / `expect_candidate_passed` fields. Paths must remain within the manifest directory. Only existing-file modifications are accepted; additions, deletions, renames, and symlink targets are intentionally unsupported. Each case has a fixed pytest runner. The operator must explicitly confirm execution because fixture tests are executable code.

For reproducible runs in environments with unrelated globally installed pytest plugins, operators may set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. This is opt-in; by default AURIX preserves pytest's normal plugin discovery for project compatibility. Only disable autoload when the target project does not depend on entry-point plugins.


## Autonomous multi-model collaboration (v0.42.0)

AURIX can independently request peer reviews during an agent task using the `consult_other_ais` tool. It contacts only endpoints explicitly configured in `AURIX_PEER_PROVIDERS`; it does not discover accounts, extract credentials, bypass access controls, or silently fall back to hosted services. Peer responses are untrusted evidence and must be critically compared by the coordinator. A maximum of eight peers can be configured, and each consultation can query at most four peers.

Example `.env` configuration (JSON; use environment-variable names for secrets):

```dotenv
AURIX_PEER_PROVIDERS=[{"name":"local-reviewer","provider":"ollama","base_url":"http://localhost:11434","model":"qwen2.5-coder:7b"},{"name":"local-critic","provider":"openai-compatible","base_url":"http://localhost:1234/v1","model":"your-loaded-model"}]
```

Supported peer types are `ollama` and `openai-compatible`. For a hosted provider, configure its documented endpoint and set `api_key_env` to the name of an environment variable containing its key. The primary model decides when consultation is useful; it can request the `consult_other_ais` tool with `{"task":"...","max_peers":3}`. This can increase latency and compute/API costs. Task content is sent to each configured peer, so do not configure external peers for confidential work unless you are authorized to share that content.


## Continual learning foundation (v0.43.0)

AURIX now separates persistent memory from a reviewable learning queue. Task outcomes, user feedback, local-tool results, peer-model suggestions, and web-research notes can be recorded as **candidates**, but are not automatically treated as truth. Review and accept a candidate explicitly:

```bash
aurix --workspace . --learning-add "This fix passed the regression suite" --learning-source task_outcome --learning-quality 0.95 --learning-scope repo:my-project --json
aurix --workspace . --learning-list --learning-scope repo:my-project --json
aurix --workspace . --learning-review 1 --learning-decision accepted --learning-quality 0.95 --learning-scope repo:my-project --json
```

Training consent is separate from acceptance. Only records that are accepted, have explicit `--learning-consent-to-train` consent, and meet the quality threshold are included in a training-data export:

```bash
aurix --workspace . --learning-add "An approved training example" --learning-source user_feedback --learning-quality 0.95 --learning-consent-to-train --learning-scope repo:my-project --json
aurix --workspace . --learning-review 2 --learning-decision accepted --learning-scope repo:my-project --json
aurix --workspace . --learning-export .aurix/training-candidates.jsonl --learning-min-quality 0.8 --learning-scope repo:my-project --json
```

The export is a dataset preparation step, **not model training**. Updating model weights requires a separate training job, compatible open-weight model, sufficient compute, a held-out evaluation suite, rollback, and checks for regressions/catastrophic forgetting. The current release does not silently fine-tune itself during user conversations. Raw conversation logging and cross-user pooling are not enabled by default. Use separate scopes and authorization for multi-user deployments.

### Learning from the Internet

AURIX can be extended to research public web pages and open datasets, but it cannot literally consume the entire live Internet. Crawling and training must respect site access controls, applicable licenses, privacy, and source-specific terms; content retrieved from the web is untrusted input and can contain prompt-injection attempts. Public availability alone does not mean that a page is licensed for model training. Prefer licensed datasets, public APIs, documented crawl policies, provenance records, deduplication, and quality filters. Common Crawl offers large public crawl archives for research, but its terms also address third-party rights and AI/ML use, so review its current terms and the source-site terms before using data for training. See [Common Crawl data access](https://commoncrawl.org/get-started), [Common Crawl terms](https://www.commoncrawl.org/terms-of-use), and [Google's robots.txt guidance](https://developers.google.com/crawling/docs/robots-txt/useful-robots-txt-rules).


## Local knowledge retrieval and efficiency (v0.45.0)

AURIX now includes a local SQLite knowledge index for text and source-code files. Indexing and search use conventional lexical ranking and do not call a model, consume API tokens, or require embeddings. The index preserves source paths and chunk numbers for traceability. It skips common internal/build directories, symlinks, unsupported file types, and files above its size limit.

```bash
# Index documentation or source files (subsequent runs skip unchanged files)
aurix --workspace . --index-add ./docs --json

# Explicitly synchronize: updates changed files and removes deleted-file entries
# only after a complete scan
aurix --workspace . --index-sync ./docs --json

# Search relevant passages locally
aurix --workspace . --index-search "context window token budget" --index-limit 5 --json

# Inspect index size
aurix --workspace . --index-stats --json
```

The first implementation is lexical retrieval, not semantic vector search. It can serve as a token-free first pass before a model is called, but semantic similarity, PDF/OCR ingestion, automatic prompt injection defense beyond treating results as untrusted evidence, and model fine-tuning are separate capabilities. SSM/Mamba and ternary/BitNet models are not automatically enabled by this release; AURIX can use a compatible model only when the provider/runtime supports it. Linear-time sequence processing does not mean zero compute or perfect retention.


### Automatic retrieval during tasks (v0.45.0)

When `.aurix/knowledge.db` already exists, the orchestrator now searches it before its first model call and appends a bounded set of source-attributed snippets as **untrusted evidence**. This uses local CPU/SQLite only and makes no extra model request. AURIX does not automatically crawl or index the workspace: explicitly build or refresh the index with `--index-add` or `--index-sync` so users control which files enter the knowledge base. Indexing is incremental; unchanged files are skipped. Synchronization removes stale entries only after a complete scan, and it avoids pruning after the configured file limit truncates a scan.

- `AURIX_RAG_ENABLED=true`: enable automatic retrieval (default).
- `AURIX_RAG_LIMIT=4`: maximum snippets retrieved per task (1–10).
- `AURIX_RAG_MAX_CHARS=6000`: approximate total character budget for retrieved evidence (500–20,000).

Disable retrieval with `AURIX_RAG_ENABLED=false`. If the index is missing, corrupt, or empty, the task continues without retrieved knowledge. JSON task output includes the source/chunk/score metadata under `knowledge_context`; telemetry records the number of retrieved snippets, not their contents. Lexical search can miss synonyms and semantic matches, and retrieved text may be stale or adversarial; verify evidence before relying on it.

## Autonomous study kernel (0.46.0)

AURIX can maintain a persistent local queue of study topics and run bounded background study cycles. The default backend is SQLite; no Supabase account or vector database is required. Generated notes are stored as **unverified learning candidates**, never automatically trusted or marked as approved for model training.

```bash
# Queue topics without calling a model
aurix --workspace . --study-enqueue "Rust async cancellation safety" --study-priority 10 --json

# Inspect queue and persisted daemon state
aurix --workspace . --study-list --json

# Execute exactly one study cycle (uses the configured model/provider)
aurix --workspace . --study-once --json

# Run a bounded daemon; it exits after 10 cycles
aurix --workspace . --study-daemon --study-max-cycles 10 --json
```

The daemon observes a stop file at `.aurix/STOP_AUTONOMY`; create it to request shutdown and remove it before restarting. Configure the idle interval with `--study-min-interval` and `--study-max-interval` (seconds). On Linux, it pauses study work when available RAM falls below its safety threshold. `--study-max-cycles` is recommended for supervised runs; omit it only when a long-running daemon is intentionally desired.

The current built-in kernel synthesizes study notes using the configured model. It does **not** autonomously crawl the Internet by default. The optional SearXNG adapter documented below retrieves bounded public sources with attribution and source-policy checks. Do not use stealth browser automation to bypass login, CAPTCHA, rate limits, or provider access controls. Peer-model output and web text are untrusted evidence. Review candidates before accepting them; training export still requires explicit per-record consent and a quality threshold.

This Python kernel provides the first portable implementation in the current Python codebase. A Rust daemon/Node.js worker split remains an optional future refactor, not a requirement for the scheduler's core behavior.

## Autonomous public-web research (optional)

The autonomous study daemon can use a user-managed SearXNG instance to discover public sources. This is disabled unless `AURIX_SEARXNG_URL` is set. Example:

```dotenv
AURIX_SEARXNG_URL=http://localhost:8080
AURIX_RESEARCH_MAX_RESULTS=3
AURIX_RESEARCH_MAX_CHARS=12000
AURIX_RESEARCH_FETCH_PAGES=true
```

Then enqueue a topic and run one cycle or a bounded daemon:

```bash
aurix --workspace . --study-enqueue "Rust async cancellation safety" --study-priority 5 --json
aurix --workspace . --study-once --json
```

The adapter queries SearXNG's JSON endpoint, limits the number and size of results, checks that fetched page targets resolve to public IP addresses, respects `robots.txt`, and does not follow redirects automatically. The SearXNG endpoint is explicitly configured by the operator and may be local; result pages must be public HTTP(S) targets. Search snippets and page text are untrusted data. Model-generated notes remain learning candidates, and training consent stays disabled by default. This is bounded research, not exhaustive crawling of the Internet. For production deployment, use network egress controls as an additional SSRF defense and review source licenses and applicable terms.

## Durable autonomous research memory (v0.49.0)

Autonomous study cycles persist source excerpts and model-generated notes separately in
`.aurix/research_memory.db`. Each record retains its topic, capture time, content fingerprint,
source URL when available, title, and linked learning-candidate ID. Repeated URL/content pairs
are deduplicated. Retrieved excerpts are stored as `retrieved_evidence`; generated study notes
are stored as `model_hypothesis`. Neither is trusted automatically.

```bash
# List recent discoveries and counts by provenance/status
aurix --workspace . --research-memory-list --json

# Review a candidate explicitly; acceptance promotes its kind to validated_knowledge
aurix --workspace . --research-memory-review 12 --research-memory-decision accepted --json

# Reject an unsupported candidate
aurix --workspace . --research-memory-review 13 --research-memory-decision rejected --json
```

A review is an operator assertion, not cryptographic proof or independent fact-checking. AURIX
never promotes discoveries to validated knowledge merely because a model generated them or a web
page contained them. This feature stores durable research memory; it does not train model weights.


## Bounded planning and three-level memory (v0.50.0)

Each autonomous study cycle now keeps a small **working-memory** object in RAM, retrieves at most three operator-reviewed prior research records from the **episodic** SQLite research store, and creates a three-branch plan (direct query, documentation-oriented query, implementation/failure-mode query). The planner uses a bounded UCT-inspired score with prior weights, exploration, observed reward, and failure penalties. It tries no more than three branches and moves to another branch after an empty result or adapter error. This is a lightweight bounded planner, not a general-purpose MCTS implementation.

Research responses are read incrementally with byte caps and parsed as HTML text, plain text, or Markdown; no graphical page rendering is needed for these retrievals. Memory snippets are source-labelled and treated as context rather than proof. Unreviewed hypotheses are not fed back as established facts. The local knowledge index remains lexical; a true embedding/pgvector semantic store is not included in this release.

Authentication hardening intentionally does **not** collect or recycle browser session cookies, impersonate aged accounts, or bypass CAPTCHAs/rate limits. If a provider offers an official API, use its documented authentication and limits. PostgreSQL support is optional through `DATABASE_URL`; this release does not assume a Supabase project or create a pgvector schema.

## Integrated patch review loop (v0.54.0)

The orchestrator can now call `review_proposal` after creating a proposal with `propose_patch`. Review is a bounded heuristic scan of added unified-diff lines and returns findings, target paths, a risk triage level, and explicit limitations. It does not edit files, run tests, or authorize application. Proposal verification remains separately gated, and patch application still requires an explicit operator confirmation. A low heuristic risk level is not proof of correctness or security.

## Specialist agents, bounded teams, and read-only tools (v0.53.0)

AURIX can persist named specialist profiles and create a small team for a task. Profiles are role/instruction configurations; they are not separate model weights or processes. Unless a future multi-provider configuration is added, all specialists use the configured AURIX provider.

```bash
# Create and list reusable specialist profiles
python -m aurix.cli --workspace . --agent-create api_security --agent-role security --agent-description "Review API trust boundaries" --json
python -m aurix.cli --workspace . --agent-list --json

# Delegate one task to a specific profile
python -m aurix.cli --workspace . --agent-run api_security --agent-task "Threat-model this API design" --json

# Automatically create architect, researcher, and reviewer profiles,
# run them independently, and ask a coordinator to synthesize their outputs
python -m aurix.cli --workspace . --agent-team --agent-task "Design an offline-first sync engine" --json
# Use sequential provider calls if your provider does not support concurrency
python -m aurix.cli --workspace . --agent-team --agent-team-sequential --agent-task "Review a migration plan" --json
# Limit concurrent specialist calls (1-4; default 3)
python -m aurix.cli --workspace . --agent-team --agent-team-workers 2 --agent-task "Design a retry strategy" --json
```

Available roles: `generalist`, `researcher`, `architect`, `coder`, `reviewer`, `tester`, `security`, `documenter`, and `optimizer`. The registry is stored at `.aurix/agents.db`, with a default maximum of 100 profiles. Names must be unique. Team creation is bounded to 2-4 specialists, and the default team uses three. Specialist calls run in parallel by default with at most four workers, or sequentially with `--agent-team-sequential`. Task-scoped profiles are removed after the run, while explicitly created named specialists persist. Each agent can request a small, role-scoped set of read-only tools: project inventory, bounded path listing, safe text-file reading (sensitive files and symlinks rejected), literal workspace search, local knowledge search, and Git status for selected review roles. When supported by the model, the agent requests tools through a strict JSON protocol; AURIX validates the role allowlist and arguments, allows at most three tool calls, then requests one final answer. Providers that return ordinary text continue to work without tools. There is no arbitrary shell, file writing, network access, recursive spawning, or automatic application of proposed changes. Tool outputs and specialist responses are untrusted data and must be checked before execution.


### Proposal integrity and audit trail (v0.55.0)

New patch proposals include a SHA-256 manifest in `.aurix/proposals/` and are checked before review or other proposal operations. A local `.aurix/audit.jsonl` records creation, review, verification, application and reversal events in a previous-hash chain. The chain detects modified events on subsequent appends, but is not an authenticated remote log: a local administrator can rewrite both the log and chain. Proposals created by older releases without a manifest are marked `legacy_unsealed`; they are not silently treated as sealed. Hashes establish content integrity, not that a patch is safe or correct.


### Digest-bound proposal audit gate (v0.56.0)

For higher-assurance patch application, run a combined audit with verification explicitly enabled:

```bash
python -m aurix.cli --workspace . --audit-proposal PROPOSAL_ID \
  --confirm-audit-verify --test-isolation docker --json
```

After the audit reports `audit_passed`, apply with both explicit confirmation and the optional gate:

```bash
python -m aurix.cli --workspace . --apply-proposal PROPOSAL_ID \
  --confirm-apply --require-audit-gate --json
```

The gate checks that the saved audit record refers to the exact current patch digest, that heuristic review reported low risk, and that verification passed. The primary checkout must still satisfy the existing Git cleanliness and patch preflight checks. Use a reviewed Docker image when executing untrusted tests; a disposable Git worktree alone is not an OS sandbox. Local audit JSON is not a remote immutable trust anchor and should not be treated as protection against a malicious local administrator.

### Dual-track proposal review (v0.57.0)

Combined audits now record two separate deterministic review tracks: security triage and correctness/robustness triage. Both are bound to the proposal SHA-256 digest. With `--require-audit-gate`, application requires schema-v3 evidence, both tracks reporting low heuristic risk, and successful verification of the same patch. Older audit records must be regenerated. The correctness track is deliberately conservative and may produce false positives; neither track proves correctness or security, and tests still need a reviewed execution boundary.

### Reproducible sandbox identity (v0.59.0)

For Docker-based proposal verification, AURIX now inspects the locally available operator-selected image, validates its immutable `sha256:` image ID, and starts the test container by that ID instead of reusing a mutable tag. Verification evidence includes that image ID plus a runtime fingerprint (Python version/implementation and OS platform fields); the evidence digest and schema-v5 audit gate bind these fields to the exact patch and base commit. Re-run the audit after upgrading because older evidence schemas do not satisfy the new gate.

This improves traceability, not perfect reproducibility or complete isolation. Docker still shares the host kernel, and the disposable worktree is mounted writable inside the container. Use an operator-reviewed image and a dedicated Docker daemon for untrusted test code. The `trusted` execution mode remains host execution, not a sandbox.

### Evidence-bound verification (v0.58.0)

Proposal verification records the exact patch SHA-256, base Git commit, test suite, isolation mode, baseline and post-patch test results, and regression classification. A canonical digest covers these evidence fields. With `--require-audit-gate`, application requires schema-v4 audit evidence bound to the current Git HEAD and the same proposal bytes, passing test results, and no detected introduced regression.

This protects against stale or accidentally modified evidence; it is not a signature or remote trust anchor. A local administrator who can rewrite the workspace can recompute local hashes. The default `trusted` test mode executes code on the host and is not a sandbox; use a dedicated, operator-reviewed Docker setup for stronger isolation.


### Transactional patch application (v0.60.0)

Applying a proposal now checks that the resulting tracked diff is exactly the reviewed target set. If integrity validation or audit-event persistence fails after application, AURIX attempts to reverse the exact proposal before returning an error. Recovery is deliberately conservative: if the exact inverse no longer applies, it does not overwrite unexpected edits and instead raises an urgent inspection error. This narrows partial-application risk but is not a filesystem transaction or protection against concurrent external writers.


## Automatic test selection (v0.61.0)

Proposal verification supports `--verify-suite auto`. AURIX only narrows pytest execution when every changed target has an explicit mapping in `.aurix/test-map.json`, for example:

```json
{
  "version": 1,
  "mappings": {
    "src/parser.py": ["tests/test_parser.py", "tests/test_parser_errors.py"],
    "tests/test_parser.py": ["tests/test_parser.py"]
  }
}
```

Every changed target must be mapped and every mapped test must be an existing regular Python file under `tests/`. If the file is missing, malformed, unsafe, or incomplete, AURIX falls back to the full pytest suite. The mapping is an operator-maintained assertion of test coverage, not proof that the selected tests cover every dependency. Selection metadata, including the SHA-256 digest of the mapping manifest when used, is included in verification evidence and the schema-v6 audit digest. The verifier rechecks the manifest after testing and rejects stale evidence if it changed.


## Verified recovery outcomes (v0.62.0)

Patch application rollback checks the tracked Git status after applying the exact inverse. Patch reversal also reports a transaction outcome and attempts to restore the pre-reversal state if audit-event persistence fails. If recovery cannot be verified safely, AURIX explicitly reports `manual_intervention_required`; it does not overwrite unexpected changes. This is conservative recovery, not a filesystem transaction and not protection against concurrent external writers.


## Concurrency-aware patch operations (v0.63.0)

AURIX serializes its own patch application and reversal operations with a per-workspace exclusive lock. The lock records the process ID and creation time; stale locks are not removed automatically because doing so without inspecting repository state could allow overlapping operations. Patch preflight rechecks Git HEAD and tracked-worktree cleanliness immediately before applying. Reversal similarly rechecks HEAD and tracked status. If HEAD changes during a mutation, AURIX refuses unsafe automatic recovery and reports that manual inspection is required. These controls coordinate AURIX instances and detect common races, but cannot prevent arbitrary external editors or Git processes from changing files between system calls.


## Evidence-bound review findings (v0.64.0)

Security and correctness findings now identify the exact proposal digest, unified-diff line, added-line SHA-256, hunk header, and resulting source line when available. The v7 audit gate validates these references against the current patch before allowing a proposal through the audit gate. This improves traceability and invalidates stale evidence; it does not turn heuristic static analysis into proof of correctness or security.


## Cycle-bound audit identity (v0.65.0)

Every audit now receives a fresh `audit_id`, while the verification execution gets its own `verification_id`. The verification evidence digest binds both identifiers along with the proposal digest, base commit, test selection, execution boundary, runtime fingerprint, baseline, and test result. Before application, the gate requires the audit and verification to belong to the same cycle; copied verification evidence from a different audit is rejected. The audit schema is v8, so existing audit records must be regenerated. These local identifiers improve consistency and replay resistance, but are not signatures or a remote trust anchor against an actor able to rewrite the local workspace.


## Target-state-bound application (v0.66.0)

Before audit, AURIX fingerprints each existing patch target and binds the canonical target-state digest to verification evidence. Applying an audited proposal requires the same target bytes and repeats that comparison immediately before mutation. This detects stale audits and many external edits between verification and application; it does not provide an OS-level atomic lock against arbitrary writers.


## Durable patch transaction journal (v0.67.0)

Patch application writes a fsynced per-proposal journal before mutation, records each verified transition, and marks completed or rolled-back transactions. An interrupted or malformed journal blocks retry for that proposal until an operator inspects the journal and repository state. This is crash-recovery evidence, not an automatic recovery mechanism or a guarantee against external writers.


## Read-only transaction recovery inspection (v0.68.0)

Run `aurix --workspace PATH --inspect-transactions --json` to inspect durable patch transaction journals. The report checks journal structure and proposal digests, and compares terminal transaction records with the current Git HEAD and tracked diff. It is strictly read-only: it does not remove locks, alter journal states, apply inverse patches, or declare an ambiguous transaction recovered. Treat `manual_intervention_required` as a stop signal and inspect the repository before further mutation. This reduces guesswork after interruption but is not a filesystem-wide lock against arbitrary concurrent writers.


## Read-only transaction recovery planning (v0.69.0)

Use `aurix --workspace . --plan-transaction-recovery --json` to create a read-only plan for transaction journals. It can propose an exact-patch rollback only when the recorded base commit, proposal digest, index state, target inventory, and Git reverse-apply check match. It does not execute recovery; ambiguous cases require manual intervention.


### Explicit transaction recovery (v0.70.0)

Inspect journals first with `aurix --workspace . --inspect-transactions --json`, then build a read-only plan with `aurix --workspace . --plan-transaction-recovery --json`. For a specifically reviewed `patch_applied` journal whose preconditions still hold, an operator may request exact inverse recovery with `aurix --workspace . --recover-transaction PROPOSAL_ID --confirm-recovery --json`. This operation refuses changed commits, staged changes, unexpected target diffs, altered proposals, and inverse patches that no longer apply. It does not recover ambiguous states automatically.


### Interrupted recovery reconciliation (v0.71.0)

- Read-only transaction inspection now distinguishes an exact applied patch, an apparently completed rollback with an unfinalized journal, and partial/external changes after interrupted recovery.
- The inspection reports suggested next steps but never edits the journal or files and never marks an ambiguous transaction as recovered.
- Added regression tests for crashes before and after inverse-patch mutation.


### Explicit interrupted-recovery finalization (v0.72.0)

When inspection shows that an interrupted rollback has already returned tracked files to the recorded base state, an operator can explicitly finalize only the journal after reviewing the report:

```bash
aurix --workspace . --inspect-transactions --json
aurix --workspace . --finalize-interrupted-recovery PROPOSAL_ID --confirm-recovery --json
```

Finalization does not modify source files. It requires a matching proposal digest, unchanged base commit, and clean tracked worktree/index; otherwise it refuses and leaves the journal for manual intervention. The operation lock coordinates AURIX processes only, not arbitrary external writers.


### Recovery-history integrity (v0.75.0)

Recovery history entries are linked by SHA-256 digests, including the previous entry hash. Explicit recovery and interrupted-recovery finalization validate the existing chain before mutating files or finalizing the journal. This detects edits to individual entries, but is not an authenticated log: a local actor able to rewrite the entire journal can recompute the chain.


### Verify recovery history

Run `aurix --workspace . --verify-recovery-history --json` to independently verify recovery-history hash chains without modifying transaction journals. Invalid records cause a non-zero exit status.


### External recovery-journal anchor (v0.75.0)

The local hash chain detects accidental or partial edits to recovery-history entries, but an actor who can rewrite a complete journal could recompute it. For stronger detection of journal edits, deletion, or additions, create a separate snapshot outside the workspace and verify against it:

```bash
aurix --workspace . --create-recovery-anchor ../aurix-recovery-anchor.json --confirm-create-recovery-anchor --json
aurix --workspace . --verify-recovery-history --recovery-anchor ../aurix-recovery-anchor.json --json
```

Creation is explicit, refuses to overwrite an existing anchor, and only snapshots journals whose recovery histories validate. Verification compares exact journal bytes and the set of journal names. Keep the anchor in separately protected storage for meaningful protection. This is an integrity snapshot, not a signed or remotely witnessed log; anyone able to modify both the workspace and anchor can replace the evidence. Refreshing requires deliberately choosing a new anchor path and reviewing the old evidence first.
### Recovery failure handling (v0.80.0)

AURIX tests two critical interruption boundaries: failure to persist recovery intent must not mutate source files; failure to persist the terminal journal after a verified rollback leaves a non-terminal journal that requires explicit, independent baseline verification before finalization. These are simulated failure tests, not a substitute for filesystem/power-loss testing on production storage.


AURIX v0.80.0 also includes a fault-injection regression test for an external edit that races rollback after the durable recovery intent. If the inverse patch leaves the tracked worktree dirty, recovery is not marked successful: the journal remains in `recovery_interrupted` for manual inspection. The operation lock coordinates AURIX processes only and cannot prevent independent editors from changing files.


### Recovery failure handling (v0.82.0)

AURIX v0.82.0 adds a regression test proving interrupted-recovery finalization refuses to mark rollback complete when the Git index contains staged changes, and confirms the journal and index are unchanged after refusal. Earlier v0.81.0 coverage tests a tracked-file edit arriving after inverse-patch application succeeds but before final repository-state verification. In that case the edit is preserved and the transaction remains `recovery_interrupted`; the journal is not marked `rolled_back`. Together with the earlier pre-application race test, this covers two separate timing windows. The operation lock coordinates AURIX processes only and cannot prevent arbitrary external editors from changing files.


### Workspace operation locking (v0.85.0)

The operation lock serializes AURIX-managed patch operations within one workspace. Regression tests verify a competing operation is rejected, the lock owner's record is preserved, the lock is removed by its owner on normal exit, and symlink lock paths are rejected without touching their targets. This lock does not coordinate arbitrary editors or external Git commands.


The lock is covered by a subprocess-level regression test and uses best-effort directory synchronization after creation and owner-verified removal. It coordinates AURIX processes only; external tools are not serialized.

### Inspecting an operation lock safely

Use `aurix --workspace PATH --inspect-operation-lock --json` to inspect the workspace operation lock without deleting or changing it. A reported PID status is advisory only; it does not prove that a lock is stale. Inspect repository and transaction state before any manual cleanup.


## Repository layout (normalized)

The Python package, tests, project configuration, and CI workflow live at the repository root. `AURIX-backup-work/` remains as recovery evidence and historical archives; the root working tree is the canonical development copy.

## Security and release status

This is a research release, not production-ready autonomous coding software. The default `trusted` test mode executes code on the host and is not a sandbox. Research page retrieval rejects non-public destinations, pins each connection to a validated IP, preserves TLS hostname verification, disables redirects, rejects compressed responses, and bounds response buffering. Remote OpenAI-compatible endpoints must use HTTPS; plain HTTP is accepted only for loopback hosts. Response-cache fingerprints hash file contents within explicit byte budgets, while oversized files use a documented metadata-based fallback. Continue to use network egress controls when deploying.
