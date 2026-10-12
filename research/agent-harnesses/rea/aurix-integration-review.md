# REA integration: second-pass security and test review

- **Date:** 2026-10-12
- **Scope:** AURIX's REA CLI and stdio-MCP adapters plus their existing tests
- **Method:** read-only source inspection through pinned/current GitHub content; no REA binary or target artifact executed
- **Status:** findings are design/test gaps, not claims of a remotely exploitable vulnerability

## Source reviewed

- [`aurix/tools/rea.py`](https://github.com/LU9DI/AURIX/blob/main/aurix/tools/rea.py)
- [`aurix/tools/rea_mcp.py`](https://github.com/LU9DI/AURIX/blob/main/aurix/tools/rea_mcp.py)
- [`aurix/tools/workspace.py`](https://github.com/LU9DI/AURIX/blob/main/aurix/tools/workspace.py)
- [`tests/test_rea_integration.py`](https://github.com/LU9DI/AURIX/blob/main/tests/test_rea_integration.py)
- [`tests/test_rea_mcp.py`](https://github.com/LU9DI/AURIX/blob/main/tests/test_rea_mcp.py)
- [`tests/test_workspace.py`](https://github.com/LU9DI/AURIX/blob/main/tests/test_workspace.py)

## Positive controls observed

1. The CLI adapter uses argument arrays with `shell=False`, a reduced environment, timeouts, an allowlist for REA commands, query-length checks, and workspace path validation.
2. The MCP adapter starts `rea mcp` directly (not via a shell or package runner), requires a regular workspace-local file, and invokes only the `open_binary` and `binary_overview` tools after checking the advertised catalog.
3. `safe_path` rejects symlink components and verifies resolved workspace containment. Workspace reads additionally exclude sensitive files and ignored directories.
4. Existing tests cover basic static invocation, command allowlisting, path traversal, symlink rejection in the MCP path, timeout handling for the static CLI, and the expected MCP tool sequence.

## Findings and gaps

### R-01 — Output truncation is not a process-memory bound — mitigation implemented; residual verification remains

**Evidence (updated 2026-10-12):** `rea.py` now drains stdout and stderr on dedicated threads into bounded byte buffers and terminates the direct child on a combined output-budget breach or timeout. `rea_mcp.py` now uses a bounded message queue and bounded `readline` calls, rejects oversized/truncated frames before JSON parsing, fails fast on malformed JSON-RPC, and stops reading if queue backpressure persists. On POSIX, the MCP process is launched in a dedicated session and protocol failure/shutdown signals its process group; non-POSIX platforms fall back to direct-child termination. Regression tests cover CLI output-budget termination and MCP over-limit frames.

**Impact:** the original unbounded-buffering design gap is mitigated for retained CLI output and MCP frame/queue sizes. This does not establish a strict whole-process-tree memory bound: the CLI runner still terminates the direct child rather than a verified process group, and the MCP process-group path has only deterministic unit coverage so far, not a hostile descendant integration test. The implementation uses character limits for MCP framing and a byte budget for CLI output. No hostile executable was run.

**Remaining remediation:** add deterministic tests for timeout/termination races, stalled MCP initialization, nonzero exits, stderr flooding, and descendant cleanup on each supported platform. Consider OS-level resource limits and process-group cleanup where supported.

**Priority:** medium for deployments where the REA executable/provider is not fully trusted; lower where it is a pinned, locally trusted binary. Do not describe this as a confirmed remote vulnerability.

### R-02 — The tests don't yet prove all failure/result contracts

Current tests now exercise representative happy paths, a CLI timeout, output-budget termination, invalid JSON results for both CLI entry points, MCP oversized/truncated frames, and several input validation failures. The inspected tests do not comprehensively assert:
- nonzero exit status and stderr truncation for both CLI methods;
- malformed JSON with exit status zero and nonzero;
- oversized stdout/stderr behavior;
- CLI timeout output type/size when `TimeoutExpired.stdout` or `.stderr` are bytes;
- MCP overlong/truncated protocol lines, malformed JSON-RPC, queue backpressure, process-group cleanup, repeated unsolicited lines, stalled initialization, process termination after timeout, and stderr flooding;
- invalid or unavailable REA provider identifiers at the MCP boundary;
- failure of `open_binary` versus failure of `binary_overview` independently.

**Recommended remediation:** add deterministic fake-process tests for these branches before refactoring output handling. Assert status, maximum returned lengths, process cleanup, and that no target execution is reported.

**Priority:** medium; these are assurance gaps, not individually confirmed bugs.

### R-04 — Invalid JSON from the bounded CLI runner raised an attribute error — fixed; regression-tested

**Evidence:** after switching the CLI adapter from `subprocess.run` to `_run_bounded`, the returned process result became a dictionary. Two invalid-JSON branches still accessed `completed.returncode` as an object attribute instead of `completed["returncode"]`, causing an `AttributeError` rather than returning the intended `invalid_output` status when the process exited successfully with non-JSON output.

**Remediation:** fixed both branches in commit [`7bd5126`](https://github.com/LU9DI/AURIX/commit/7bd51262f4813f2f9a42fd7144bb34500efc99f2) and added regression tests for both static JavaScript analysis and native investigation in [`8b40976`](https://github.com/LU9DI/AURIX/commit/8b40976be6f305171e818bed855da9ca9722b84d). CI runs for those commits passed: [fix](https://github.com/LU9DI/AURIX/actions/runs/38315732945) and [tests](https://github.com/LU9DI/AURIX/actions/runs/38315748052).

**Status:** fixed for the covered branches. The subsequent MCP frame-boundary and truncated-EOF regression suite passed in [CI run 38315797924](https://github.com/LU9DI/AURIX/actions/runs/38315797924), with 309 tests passing in 12.24 seconds. The preceding run also passed with 309 tests in [CI run 38315787568](https://github.com/LU9DI/AURIX/actions/runs/38315787568).

### R-03 — Static-analysis “read-only” is not an OS sandbox

The adapters do not launch the analyzed target application, which is a meaningful safeguard. However, they do execute the configured REA executable and, for native analysis, may invoke configured providers. The reduced environment and timeout do not by themselves constrain filesystem access, child processes, CPU, memory, or network access.

**Recommended remediation:** document the trust boundary accurately. For untrusted binaries or provider plugins, run REA in an external sandbox/container with explicit filesystem, network, CPU, memory, and process limits. Keep the workspace mounted read-only unless writes are an explicit requirement.

**Priority:** deployment-dependent; treat as an architecture boundary, not a code-level guarantee.

## Suggested verification matrix

| Area | Case | Expected contract |
|---|---|---|
| CLI | exit 0 + valid JSON | completed, structured evidence |
| CLI | exit 0 + invalid/truncated JSON | invalid_output; bounded output |
| CLI | nonzero exit | failed; bounded stderr/output |
| CLI | timeout | timeout; bounded diagnostics; no false success |
| CLI | stdout/stderr exceeds budget | explicit limit status; child terminated; memory bounded |
| MCP | line exceeds protocol budget | protocol error; child stopped; no unbounded queue growth |
| MCP | initialize/list/call stalls | timeout and process cleanup |
| MCP | open or overview returns isError | failed result; no success claim |
| Path | traversal/absolute/symlink | rejected before process launch |
| Provider | malformed identifier | rejected before process launch |

## Next action

R-01 mitigation was committed on `main` in commits `95ffbd8`, `0360499`, `a27df16`, `d819ec3`, `75b16f4`, and related regression-test commits. The prior CI run at [`7e50db7`](https://github.com/LU9DI/AURIX/actions/runs/38315306950) passed. The latest CI run for commit [`694e7de`](https://github.com/LU9DI/AURIX/actions/runs/38315648593) passed (lint and test job successful; 306 tests passed). The preceding test run failed on a malformed newline fixture, which was corrected in `694e7de` and verified by the passing run. R-02 remains open for the failure cases listed above. New commits `7c0203e`, `7ddf96e`, `1938ff1`, and `7e18027` add MCP queue-backpressure handling, fail-fast malformed-JSON behavior, and POSIX process-group cleanup; their latest CI and the new process-group regression test must be checked before treating the whole series as green. R-03 remains a deployment/documentation boundary and must not be represented as solved by Python path validation alone.
