# Safety model

AURIX is intended to eventually read and modify code and invoke developer tools.

## Initial safeguards
- Resolve workspace paths and reject traversal.
- Run commands without a shell and only from a narrow allowlist.
- Bound command duration, output size, and reasoning steps.
- Treat model output as untrusted data, never as policy.

## Required before production
- Run untrusted repositories in disposable containers/VMs without ambient credentials.
- Require approval for writes, network access, installs, deployments, and destructive actions.
- Redact secrets from traces and memory; implement retention and deletion controls.
- Test prompt injection, path traversal, symlink escapes, command injection, resource exhaustion, and exfiltration.
- Never expose host secrets or production credentials to models or untrusted repositories.

## Docker-isolated test execution (v0.33)

For an operator-selected local image, the fixed test runner can use Docker with `--network=none`, `--read-only`, dropped Linux capabilities, `no-new-privileges`, PID/memory/CPU limits, and a single writable workspace bind mount. The runner verifies the image is already local and uses `--pull=never`; it fails closed if Docker or the image is unavailable and never silently runs on the host. The image must include project dependencies and test tools.

This is not a perfect security boundary: the Docker daemon, kernel, image contents, mounted workspace, and test process remain in the trust model. Use a dedicated daemon and reviewed image for hostile code. Live Docker execution must be validated on the target host. The default `trusted` mode is not sandboxed.

## Context privacy

The context builder skips common `.env*` and SSH private-key filenames and bounds both the number of files and total characters. This is defense-in-depth, not a guarantee that arbitrary credentials cannot appear in source files. Review repository contents before sending context to a hosted model. Telemetry deliberately stores metadata only; never add prompt/completion logging without explicit opt-in and a clear retention policy.

## Execution boundary

The agent does not automatically edit files or execute model-proposed commands. v0.4 adds a separate, explicitly confirmed patch-application command: it requires a clean tracked Git worktree and only permits in-place changes to existing tracked regular files after Git preflight. The command helper's allowlist is not a sandbox; do not expose it to untrusted model output as an autonomous executor. Sandboxed test execution, stronger OS-level isolation, and resource limits remain required before production use.


## Patch proposals

The `propose_patch` tool stores a bounded unified diff in `.aurix/proposals/` for human review. A separate CLI operation can apply it only with an explicit confirmation flag, a clean tracked worktree, and Git preflight. Only in-place modifications to existing tracked regular files are supported. Binary diffs, metadata headers, renames, additions/deletions, unsafe paths, symlinks, and sensitive filenames are refused. Reversal is available only when the exact inverse patch still applies. These controls are defense in depth, not proof of semantic safety; review diffs and inspect Git status afterward.


## Explicit test runner (v0.5)

The CLI can run only fixed `python -m pytest -q` or `python -m ruff check .` commands after explicit operator confirmation. The runner clamps timeouts to 120 seconds, truncates output, and passes a reduced environment that omits common API-key/database URL variables. This does **not** isolate filesystem or network access, does not prevent malicious tests from using OS permissions, and is not a sandbox. Run it only against trusted repositories. For untrusted code, use a disposable container/VM with no ambient credentials, restricted network, read-only mounts where possible, and CPU/memory/process limits.


## Continual learning and web ingestion

Learning candidates from users, tools, peers, or web research are untrusted until reviewed and evaluated. Acceptance and permission to use an example for model training are separate fields. Never use private conversation content or user documents for training without explicit, scoped consent. Do not let crawled content execute tools or alter system policy; treat web text and peer responses as data. Preserve source URL, timestamp, license/terms review, content hash, and evidence for every web-derived candidate. Model-weight updates must run as a separate job with held-out evaluations, regression gates, a recoverable prior checkpoint, and an operator-controlled promotion/rollback path.
