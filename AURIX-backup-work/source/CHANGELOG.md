## 0.85.0 — Cross-process lock verification and directory durability

- Added a real subprocess regression test proving a second process cannot enter a workspace while another AURIX process owns the operation lock.
- The test verifies owner identity is preserved during rejection and the lock is removed by its owner after normal exit.
- Added best-effort directory `fsync` after lock creation and owner-verified removal, complementing the existing file-content `fsync` for filesystems that support directory synchronization.
- This lock serializes AURIX operations only; it does not prevent external editors or Git commands from changing the workspace. Directory `fsync` remains best-effort where unsupported.

## 0.83.0 — Workspace operation-lock regression coverage

- Added regression tests proving a second AURIX operation is refused while the workspace lock is held.
- Verified the existing lock owner record remains unchanged after a rejected contender.
- Added symlink-lock coverage proving external lock targets are not followed or modified.
- This release strengthens verification of the existing lock behavior; it does not claim to lock out arbitrary editors or other tools that ignore AURIX's lock.

## 0.82.0 — Staged-index divergence during interrupted recovery

- Added regression coverage proving interrupted-recovery finalization refuses to mark rollback complete when the Git index contains staged changes, even if the tracked worktree content has been restored.
- The test asserts the journal and staged index remain unchanged after refusal.
- No automatic-recovery permissions were broadened; explicit confirmation and clean HEAD/worktree/index checks remain required.

## 0.81.0 — Post-rollback concurrent-edit detection

- Added fault-injection coverage for an external tracked-file edit occurring after the inverse patch succeeds but before the final clean-worktree verification.
- Confirms the recovered baseline is not falsely marked terminal when a concurrent edit appears in the verification window; the external edit is preserved and the journal remains `recovery_interrupted`.
- This closes a distinct race window from the earlier test that injects an edit before inverse-patch application. It does not claim to serialize arbitrary external editors.

## 0.80.0 — Concurrent-edit recovery guard

- Added a fault-injection regression test for a tracked-file edit arriving after recovery intent is durably written but before inverse-patch application.
- Verifies that rollback does not report success when the final tracked worktree is dirty; the journal is retained as `recovery_interrupted` and manual intervention is required.
- This tests a narrow race window and does not claim to lock out external editors or provide a filesystem-wide transaction.

## 0.79.0 — Recovery interruption matrix

- Added regression coverage for failure to persist recovery intent: source files remain untouched and the original journal state is preserved.
- Added regression coverage for failure to persist the terminal rollback journal after the inverse patch succeeds; the clean baseline can only be finalized through the explicit, independently verified finalization path.
- These tests document the recoverable boundary between filesystem mutation and terminal journal persistence; they do not claim power-loss testing or deployment validation.

## 0.78.0 — Transaction recovery replay and write-failure regression coverage

- Added a regression test proving a failed atomic journal replacement preserves the previous committed journal bytes and removes the temporary file.
- Added a recovery replay test proving a completed rollback cannot be executed a second time and does not mutate the restored source or terminal journal.
- No recovery policy was broadened: interrupted transactions still require explicit confirmation and ambiguous states fail closed.

## 0.77.0 — Strict transaction-journal JSON parsing

- Reject duplicate JSON keys in transaction journals across read-only verification, transaction inspection, recovery planning, recovery execution, and audit-evidence loading.
- Prevent ambiguous fields such as `state`, `proposal_id`, or `patch_sha256` from being silently resolved by last-key-wins JSON parsers.
- Added regression tests proving journal verification marks duplicate-key records invalid and transaction inspection fails closed.
- Existing durable journal writes continue to use exclusive temporary files, file fsync, atomic replacement, and best-effort directory fsync.

## 0.76.0 — Strict external recovery-anchor parsing

- Reject duplicate JSON object keys when reading recovery anchors, eliminating ambiguous parser interpretations of security-relevant fields.
- Validate every anchored journal name against the exact proposal-journal filename format before comparing snapshots; path-like or malformed names fail closed.
- Added regression tests for duplicate anchor keys and path traversal-like journal names.
- Scope remains unchanged: SHA-256 snapshots detect divergence from an operator-held baseline but are not signatures and cannot protect against an attacker who can rewrite both anchor and journals.

## 0.75.0 — External recovery-journal anchoring

- Added explicit creation of a new external SHA-256 snapshot for valid transaction journals; existing anchors are never overwritten.
- Recovery verification can compare the live journal set and exact bytes against an anchor, detecting changed, deleted, and newly added journals.
- Anchors must be outside the workspace, regular non-symlink files; creation is explicit and uses exclusive creation, restrictive permissions, fsync, and no silent overwrite.
- Added tests for changed/removed/added journals and anchor path/overwrite refusals.
- Scope: the anchor is an operator-managed integrity snapshot, not a digital signature or protection against an attacker who can rewrite both the workspace and anchor.

## 0.74.0 — Independent recovery-history verification

- Added read-only `verify_recovery_histories()` and `--verify-recovery-history` CLI operation.
- Verifies transaction identity and each recovery-history SHA-256 chain, reports per-journal status, and exits non-zero on invalid records.
- Added regression coverage for valid chains, tampering detection, and read-only behavior.

## [0.73.0] - 2026-10-09

- Added a transaction-local SHA-256 hash chain for recovery history entries.
- Recovery and interrupted-recovery finalization now validate existing history before changing repository state or finalizing journals.
- Added regression coverage for tampered recovery-history entries.

## v0.72.0 — Explicit interrupted-recovery finalization

- Added an explicitly confirmed journal-finalization operation for interrupted recoveries whose rollback can be independently verified against the recorded base commit and a clean tracked worktree/index.
- The operation never changes source files; it revalidates proposal digest and repository state, records recovery history, and emits a provenance event. Ambiguous states remain fail-closed.
- Added CLI support via `--finalize-interrupted-recovery ID --confirm-recovery`.

## v0.71.0 — Interrupted recovery reconciliation

- Extended read-only transaction inspection to classify interrupted recovery by comparing the current worktree against the exact applied patch and the recorded base commit.
- Distinguishes patch-still-applied, rollback-effectively-completed-but-journal-unfinalized, and partial/external-change states.
- Provides suggested next steps without changing files or journals; ambiguous states remain manual-intervention cases.
- Added crash-window regression tests around inverse-patch mutation and journal finalization.

## v0.70.0 — Explicit transaction recovery

- Added `--recover-transaction ID --confirm-recovery` for exact-patch rollback of interrupted `patch_applied` transactions.
- Recovery acquires the workspace operation lock, revalidates the journal, patch digest, base commit, clean index, exact target diff, and inverse applicability immediately before mutation.
- Recovery persists an in-progress journal state before mutation and verifies the final clean worktree before marking rollback complete. Ambiguous or interrupted outcomes require manual intervention.
- Added an auditable recovery history and a dedicated provenance event.

## 0.69.0 — Read-only recovery planning

- Added `--plan-transaction-recovery` to produce structured, non-executing plans for transaction journals.
- An exact rollback candidate is proposed only when the proposal digest, base commit, clean index, exact tracked target set, and reverse-apply check all pass.
- The plan rechecks no state by mutation, does not edit journals or files, and never labels rollback as safe to automate; explicit confirmation and fresh preflight remain mandatory for any future executor.
- Ambiguous states and external edits remain manual-intervention cases.

## 0.68.0 — Read-only transaction recovery inspection

- Added `aurix --inspect-transactions` to inventory transaction journals without changing repository files or journal state.
- Reports malformed journals, missing or digest-mismatched proposals, non-terminal transactions, and repository states inconsistent with the recorded application or rollback.
- Applied transactions are checked against the recorded base commit, exact tracked diff target set, staged state, and whether the exact inverse still applies.
- The command never auto-rolls back, clears locks, or marks a transaction recovered; ambiguous states remain manual-intervention cases.

## 0.67.0 — Durable patch transaction journal

- Writes a per-proposal transaction journal with fsynced content and directory metadata where supported, before mutating tracked files.
- Records applying, patch-applied, verified-complete, and verified-rollback states, including proposal digest, base commit, and approved target list.
- Blocks retry when a journal is malformed or records an incomplete transaction, preventing silent duplicate attempts after interruption.
- Journal completion is recorded only after application audit logging succeeds; rollback states are persisted only after tracked state is verified.
- This is explicit crash-recovery evidence and a fail-closed retry guard, not automatic rollback after process death or protection against all external filesystem races.

## 0.66.0 — Target-state-bound application

- Captures SHA-256 fingerprints for every existing patch target before review and verification.
- Binds the target-state digest into verification evidence and rejects stale audits if any target file changes before application.
- Rechecks target bytes immediately before mutation and before persisting an audit, reducing stale-evidence and time-of-check/time-of-use windows.
- This is change detection, not a filesystem-wide atomic lock; external writers can still race at the OS level.

## 0.65.0 — Cycle-bound audit and verification identity

- Each audit receives a fresh 128-bit hexadecimal `audit_id`; verification has a separate `verification_id` and must carry the same audit-cycle identity.
- Both identifiers are included in the canonical verification evidence digest and verified again by the patch-application gate.
- Audit schema advanced to v8; verification evidence from another cycle is rejected even if its ordinary digest is recomputed.
- Added regression coverage for cross-cycle evidence substitution.
- Limitation: identifiers and local digests provide consistency and tamper detection, not authenticity against an actor who can rewrite all local artifacts and source code.

## 0.64.0 — Evidence-bound review findings

- Security and correctness review findings now carry patch digest, unified-diff line, source line where available, hunk header, and SHA-256 of the exact added line.
- Audit schema advanced to v7; application gate rejects stale or structurally inconsistent review evidence.
- Added regression tests for evidence binding and tampered line evidence.
- Limitation: static review remains heuristic; line-level provenance improves traceability but does not prove security or correctness.

## 0.63.0 — Concurrency-aware patch operations

- Added an exclusive per-workspace lock for AURIX patch application and reversal.
- Refuses to proceed when a lock exists; stale locks require explicit inspection rather than automatic deletion.
- Rechecks Git HEAD and tracked-worktree status immediately before mutation.
- Detects Git HEAD changes during apply/revert and reports manual intervention instead of claiming safe rollback.
- Added regression tests for lock collisions and a simulated concurrent commit during preflight.
- Limitation: the lock coordinates AURIX processes only and cannot make arbitrary external file edits atomic.

## 0.62.0 — Verified recovery outcomes

- Exact patch rollback now verifies the resulting tracked Git status instead of assuming a successful inverse command means recovery completed.
- Recovery errors explicitly distinguish unsafe or unverified recovery and instruct operators to inspect the worktree.
- Patch reversal now records a transaction outcome and attempts to restore the pre-reversal state if audit logging fails.
- Added status verification around recovery paths; these checks reduce ambiguity but do not provide atomicity against concurrent external writers.

## 0.61.0 — Conservative automatic test selection

- Added `--verify-suite auto`: it selects targeted pytest files only when every changed file is covered by an explicit, validated `.aurix/test-map.json` mapping.
- Missing, malformed, unsafe, or incomplete mappings conservatively fall back to the full pytest suite.
- Test selection metadata is stored in verification evidence and included in the audit evidence digest; audit schema advanced to v6.
- The test runner validates relative test paths and supports targeted execution in trusted and Docker modes.
- Added tests for mapped selection and fail-safe fallback.

## 0.60.0 — Transactional patch application

- Patch application now verifies that the resulting tracked diff matches exactly the reviewed target set.
- If post-apply integrity checks or audit-event persistence fail, AURIX attempts an exact reverse-patch rollback and reports clearly when recovery cannot be completed safely.
- Added tests for rollback on audit-log failure and for explicit transaction outcome metadata.
- Recovery is fail-closed: if the inverse patch no longer applies exactly, AURIX refuses a risky rollback and tells the operator to inspect the worktree.


## 0.59.0 — Reproducible sandbox identity

- Docker verification resolves the operator-selected local image tag to its immutable `sha256:` image ID and starts the container by that ID, reducing mutable-tag race risk.
- Verification evidence records the sandbox image ID and a bounded Python/OS runtime fingerprint; the canonical evidence digest covers these fields.
- The audit gate now requires schema-v5 evidence, including the runtime fingerprint and image identity fields, so older audit records must be regenerated.
- Added regression coverage for image ID pinning, fail-closed Docker inspection, and evidence schema changes.
- Docker still shares the host kernel and mounts the temporary worktree writable; use a dedicated daemon for hostile code. The runtime fingerprint aids diagnosis but does not make execution bit-for-bit reproducible.


# Changelog
## 0.58.0 — Evidence-bound verification

- Verification results now bind the exact proposal SHA-256, base Git commit, suite, isolation mode, baseline result, post-patch result, and regression classification.
- A canonical evidence digest detects changes to stored test evidence.
- The audit gate now requires schema v4, a matching current HEAD, matching proposal digest, passing test evidence, and no detected introduced regression.
- Added regression tests for valid evidence, stale base commits, and modified verification records.
- Verification still depends on the selected execution boundary; trusted mode is not a sandbox, and local hashes are not an external trust anchor.


## 0.56.0 — Digest-bound audit gate

- Combined proposal audits are persisted as bounded local JSON evidence and bind review and verification outcomes to the SHA-256 digest of the exact patch.
- The audit flow re-hashes the proposal after review/verification and refuses to record stale evidence if the bytes changed mid-audit.
- Added opt-in `--require-audit-gate` for patch application; it requires a low-risk review, passing verification, matching proposal identity, and an exact digest match in the latest audit record.
- Kept the existing explicit `--confirm-apply` requirement. The gate is opt-in for backward compatibility; local evidence is not a remote or administrator-proof trust anchor.
- Added regression tests for successful gates, absent/stale audit evidence, and proposal changes during auditing.


## 0.55.0 — Proposal integrity and audit provenance

- Newly created patch proposals receive a SHA-256 manifest with creation timestamp and size; review, verification, apply, and revert paths verify the manifest when present and refuse changed contents.
- Added a local JSONL audit trail for proposal creation, review, application, and reversal, with a previous-hash chain checked before every append.
- Legacy proposals without manifests remain readable but are explicitly identified as `legacy_unsealed`; they do not gain retroactive integrity guarantees.
- Added regression tests for proposal tampering, manifest identity mismatch, and audit-chain modification.
- The audit chain is tamper-evident, not remotely immutable: an administrator able to rewrite the workspace can rewrite the entire local log.

## 0.54.0 — Integrated patch review loop

- Exposed the deterministic proposal-review tool directly to the orchestrator, allowing a model to create a review-only patch and then request bounded static triage by proposal ID.
- Kept review separate from application: heuristic findings never authorize patch application or imply that tests passed.
- Enforced a strict proposal-ID argument schema and kept the tool unavailable to arbitrary shell execution or file-writing flows.
- Added end-to-end regression coverage for proposal creation followed by independent review of added diff lines.

## 0.53.0 — Role-scoped read-only agent tools

- Added a capability-limited toolbox for project inventory, safe path listing/reading, literal workspace search, local knowledge retrieval, and read-only Git status.
- Each role has an explicit tool allowlist; every call is schema-validated and outputs are bounded. Sensitive files and symlinks are rejected by workspace readers.
- Added a strict JSON tool-request protocol with a maximum of three tool calls per agent run and one final synthesis request; ordinary text-only provider responses continue to work.
- Tool errors are returned as bounded error types without leaking exception text or credentials. No arbitrary shell, file writes, network access, or recursive agent spawning is exposed.
- Added regression tests for allowed/denied capabilities, bounded protocol parsing, and secret-file exclusion.


## 0.52.0 — Bounded parallel specialist teams

- Specialist contributions can run concurrently through a bounded thread pool (1–4 workers); each worker creates its own configured provider instance and results retain deterministic role order.
- Added sequential mode for providers that do not support concurrent requests, plus CLI worker-count validation.
- Task-scoped team profiles are deleted after execution so repeated runs do not fill the persistent named-agent registry; explicitly created named specialists remain persistent.
- Team outputs report execution mode, worker bound, partial failures, and the security boundary: no implicit shell, filesystem, or external-tool permissions.
- Added tests for parallel execution, sequential mode, and temporary-profile cleanup.

## 0.51.0 — Persistent specialist-agent factory

- Added a bounded SQLite registry for named specialist profiles with validated roles, descriptions, uniqueness, and a configurable hard cap.
- Added CLI operations to create, list, and run specialist agents using the configured provider.
- Added task-scoped team creation: architect, researcher, and reviewer profiles each contribute independently; a coordinator synthesizes successful outputs and exposes partial failures.
- Specialist outputs are treated as untrusted proposals. No shell, filesystem mutation, credentials, or external-tool permissions are granted implicitly.
- Agents are role profiles, not separate autonomous model instances; team runs are bounded and use the configured provider. No recursive spawning or unlimited agent creation is allowed.
- Added tests for persistence, invalid roles/names, duplicate names, provider delegation, team creation, and partial failures.


## 0.48.0 — Incremental knowledge synchronization

- Knowledge indexing now hashes file contents and skips unchanged files on repeat runs.
- Changed files replace their old chunks rather than accumulating stale versions.
- Added root-scoped source ownership metadata and stale-file cleanup after complete scans.
- Added `--index-sync PATH` for explicit synchronization; `--index-add` also refreshes incrementally.
- Truncated scans do not prune missing sources, and cleanup respects overlapping indexed roots.
- Added regression tests for unchanged files, changed files, deletion, root isolation, and scan truncation.


## 0.47.0 — Policy-aware autonomous web research

- Added optional SearXNG adapter for bounded public-web search during autonomous study.
- Added bounded extraction of HTML text and source URL/title/snippet provenance.
- Rejects non-HTTP(S), credential-bearing, local/private hostnames and targets resolving to non-public IP addresses before fetching pages.
- Disables automatic redirects to avoid following unvalidated redirect destinations.
- Checks `robots.txt` before fetching result pages and fails closed when the policy cannot be checked.
- Web research remains disabled unless `AURIX_SEARXNG_URL` is explicitly configured.
- Search results and page text remain untrusted input; findings remain learning candidates and training consent remains false.
- This adapter does not bypass logins, CAPTCHAs, robots directives, paywalls, or provider access controls.

## 0.46.0 — Autonomous study kernel foundation

- Added a durable SQLite topic queue with priorities, deduplication, bounded retries, and persistent daemon state.
- Added an autonomous study cycle that records model-generated notes only as unverified learning candidates; training consent remains false by default.
- Added bounded background-loop controls, randomized idle intervals, Linux available-memory guard, stop-file support, and max-cycle limits.
- Added optional research-adapter injection without implementing stealth scraping or bypassing access controls.
- Added CLI operations to enqueue/list topics, run one cycle, or start a supervised daemon.
- The daemon uses the configured provider for synthesis; internet research is not active unless a compliant research adapter is supplied.

## 0.45.0 — Automatic local RAG in agent tasks

- Integrated local SQLite knowledge retrieval into the orchestrator before the first model call.
- Retrieved snippets include relative source paths, chunk numbers, and ranking scores as untrusted evidence.
- Added bounded retrieval controls and an environment switch; local index failures do not stop tasks.
- Retrieval uses an existing `.aurix/knowledge.db`; it does not scan or index files implicitly.
- Added telemetry for retrieved evidence count and result-level knowledge provenance.

## 0.44.0 — Local retrieval and inference efficiency

- Added a dependency-free SQLite knowledge index for text and source files.
- Added BM25-like lexical retrieval with source-path and chunk references.
- Added CLI commands to index, search, and inspect the local index without invoking a model.
- Excluded common internal/build directories and symlinks from indexing.
- This is lexical RAG infrastructure; embeddings, SSM/BitNet model execution, and model-weight training are not implemented by this change.

## 0.43.0 — Continual learning foundation

- Added evidence-gated learning candidates and consent-separated training export.

## 0.57.0 — Dual-track digest-bound review

- Combined audits now include separate security and correctness/robustness heuristic review tracks, each bound to the exact proposal SHA-256 digest.
- The opt-in application gate now requires schema-v3 evidence with both review tracks low-risk and digest-matched, plus passing verification of the exact patch.
- Legacy audit records cannot satisfy the stronger gate; rerun the audit and verification to create current evidence.
- Added tests for dual-track digest binding and for correctness findings preventing an audit pass. These heuristics remain triage, not proof of safety or correctness.

## 0.84.0 — Read-only operation-lock inspection

- Added `inspect_operation_lock()` and `--inspect-operation-lock` to report absent, present, or malformed workspace locks without changing them.
- Reports a best-effort PID status but explicitly does not prove that a lock is stale, avoiding unsafe automatic cleanup after PID reuse or permission limitations.
- Added regression tests for read-only inspection and malformed duplicate-key lock records.
