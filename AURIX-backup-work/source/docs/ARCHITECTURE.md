# AURIX architecture

```text
CLI -> bounded orchestrator -> provider protocol -> local/compatible inference
                          -> policy-gated tools -> optional REA static-analysis adapter
                          -> memory protocol (SQLite / optional Neon)
                          -> structured trace events (planned)
```

## Efficiency hypothesis

Token count is only one metric. Evaluate task success, regression rate, model calls, tokens where available, wall-clock latency, peak memory, tool failures, and human interventions. Candidate optimizations include context pruning, repository maps, content hashing, exact-result caching, compact task state, and smaller-model routing. Multi-agent calls should be included only when ablations show net value.

## Memory

Store compact reusable facts and task outcomes, not indiscriminate transcripts. Records should have provenance, timestamp, scope, and deletion behavior. Do not persist secrets. SQLite is the local default; PostgreSQL/Neon is optional. Add vector search only after retrieval benchmarks justify its complexity and cost.

## Planned task loop

1. Parse task and workspace scope.
2. Gather repository facts deterministically.
3. Draft a small, verifiable plan.
4. Invoke model reasoning when useful.
5. Execute one approved action at a time.
6. Run relevant tests and inspect the diff.
7. Report evidence, uncertainty, and remaining work.

## Context assembly and observability

The CLI assembles a bounded context from selected text files, prioritizing project entry points and excluding common environment/SSH secret filenames. Context files are untrusted data and are never executed by context assembly. This is a heuristic, not a complete secret scanner: do not point AURIX at a workspace containing secrets unless you have reviewed the behavior and configured exclusions.

Generation metadata is appended as JSON Lines under `.aurix/runs.jsonl` by default. It includes provider class, elapsed time, character counts, and approximate token estimates—not prompts, completions, or API keys. Character-based estimates are useful for rough local comparisons only and do not reflect actual tokenizer or provider billing data.

## Evaluation contract

`aurix.evaluation.benchmark` accepts a JSON array of tasks and simple `must_contain` acceptance terms. The report is deterministic in schema but model outputs and latency are not. Use a fixed model/version, repeated runs, task-specific checks, and human review for meaningful comparisons. Keyword pass rates alone are not a claim of general intelligence.

## Read-only tool loop

The orchestrator accepts a bounded JSON protocol (`final`, `need_context`, or `tool_call`). Model-callable inspection tools include `list_files`, `read_file`, `search_text`, `git_status`, and `git_diff`; `read_file` supports bounded line ranges with line numbers. Tool names are dispatched by an explicit allowlist, not reflection. Tool results are added to the next prompt as untrusted data. `AURIX_MAX_STEPS` bounds the number of model calls. The loop does not write project files or expose arbitrary shell execution. Git inspection uses fixed read-only commands, with repository-root checks and bounded output. This is a safety boundary, not a sandbox: model inputs and retrieved repository data still require careful handling.

Workspace tools enforce root-relative paths, reject symlink paths, skip common generated directories and sensitive file names, and cap result sizes. These controls reduce accidental exposure but are not a substitute for running the agent under a low-privilege OS account and isolating it from credentials.
