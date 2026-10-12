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

### R-01 — Output truncation is not a process-memory bound

**Evidence:** `rea.py` calls `subprocess.run(..., capture_output=True)` and truncates stdout/stderr only after the child exits. The MCP adapter reads stdout one complete line at a time, puts lines on an unbounded `queue.Queue`, and checks `MAX_MCP_MESSAGE_CHARS` only after dequeueing.

**Impact:** a malfunctioning or unexpectedly noisy REA process can cause AURIX to buffer output in memory before the existing response-size limits take effect. The current limits bound returned text, but do not strictly bound peak memory consumption. This is a local child-process resource-exhaustion concern; no exploit was executed.

**Recommended remediation:** for the CLI path, stream stdout/stderr into bounded buffers while draining both pipes, terminate the child on hard output-budget breach, and return an explicit `output_limit_exceeded` status. For MCP, enforce a byte/character cap while reading chunks (before constructing an arbitrarily long line), bound the inter-thread queue, and terminate the child on protocol-budget violation. Ensure both pipes continue to be drained or the child is stopped to avoid deadlocks.

**Priority:** medium for deployments where the REA executable/provider is not fully trusted; lower where it is a pinned, locally trusted binary. Do not describe this as a confirmed remote vulnerability.

### R-02 — The tests don't yet prove all failure/result contracts

Current tests exercise representative happy paths, a CLI timeout, and several input validation failures. The inspected tests do not comprehensively assert:
- nonzero exit status and stderr truncation for both CLI methods;
- malformed JSON with exit status zero and nonzero;
- oversized stdout/stderr behavior;
- CLI timeout output type/size when `TimeoutExpired.stdout` or `.stderr` are bytes;
- MCP overlong protocol lines, repeated unsolicited lines, stalled initialization, process termination after timeout, and stderr flooding;
- invalid or unavailable REA provider identifiers at the MCP boundary;
- failure of `open_binary` versus failure of `binary_overview` independently.

**Recommended remediation:** add deterministic fake-process tests for these branches before refactoring output handling. Assert status, maximum returned lengths, process cleanup, and that no target execution is reported.

**Priority:** medium; these are assurance gaps, not individually confirmed bugs.

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

Implement R-01 with streaming bounded output and add regression tests for R-01/R-02. Run the full CI suite and record the exact commit/run. R-03 remains a deployment/documentation boundary and must not be represented as solved by Python path validation alone.
