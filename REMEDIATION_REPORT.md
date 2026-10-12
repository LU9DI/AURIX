# AURIX remediation log

Date: 2026-10-12  
Branch: `main`

## Changes in this remediation set

- Normalize the recovered Python project to the repository root while retaining the uploaded ZIP and historical archive area.
- Activate root-level CI for Python 3.11, compileall, Ruff, and pytest.
- Fix the `robots.txt` disallow branch by constructing the source summary before the branch can append it.
- Add a pinned outbound HTTP transport for research retrieval: resolve once per request, reject non-public answers, connect to the validated IP, preserve TLS hostname verification, disable redirects, and bound response buffering.
- Add scoped `delete` and `clear` operations to the memory protocol and SQLite/PostgreSQL backends, with tests.
- Strengthen response-cache invalidation by hashing file contents within explicit per-file and total byte budgets; add a regression test for same-size changes with preserved timestamps.
- Require HTTPS for remote OpenAI-compatible providers and allow plain HTTP only for loopback endpoints; add regression tests.
- Harden Docker test execution further: run as a non-root UID and mount the workspace read-only, in addition to disabling networking and dropping capabilities.
- Expand workspace secret exclusions to common credential directories (`.ssh`, `.aws`, `.azure`, `.gnupg`, `.docker`, `.kube`, `.terraform`, `.pulumi`) and token/credential files such as `.npmrc`, `.netrc`, `.pypirc`, Terraform state, and cloud service-account files, with regression coverage.
- Enforce ignored-directory policy on direct reads and line-range reads as well as recursive search/context building, preventing direct access to `.git/` metadata and `.venv/` contents through the workspace reader.
- Align execution-runner documentation and security notes with the actual read-only Docker workspace mount.
- Add a documented REA-assisted research workstream with a public-source target catalogue, evidence schema, license review, reproducibility requirements, and isolation boundaries.
- Inspect the upstream REA repository at pinned revision `1c37914306b3ff257d7a0360f11c9bf2a3f2cac7` (package `rea-agents` 6.4.0, MIT) and document the division of labor: use pinned source/tests for ordinary open-source harness audits, and REA for shipped artifacts or runtime evidence.
- Record a preliminary, source-only Aider harness review at pinned revision `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` (Apache-2.0), including repository-map caching, edit lifecycle, lint feedback, and shell execution boundaries. No Aider code or commands were executed.
- Normalize legacy formatting and configure CI to enforce syntax, unused-name/import, and core error checks while excluding the repository's existing long-line style debt.
- Update the root README and recovery report.

## Final validation (2026-10-12)

- Pull request #4 was merged into `main`; merge commit: `75699ddd3a3146016c5923f43b9c1560ed99ed49`.
- Latest root CI run after the direct-read hardening: [38301763383](https://github.com/LU9DI/AURIX/actions/runs/38301763383) — **success**.
- Research documentation and the preliminary Aider review also passed CI on [38302370787](https://github.com/LU9DI/AURIX/actions/runs/38302370787): compile and Ruff passed; **302 tests passed in 14.88 seconds**.
- `python -m compileall -q aurix tests`: passed.
- Correctness-focused Ruff gate: passed. The gate checks `E` and `F` rules and excludes `E501` long-line debt; it is not a full style-cleanliness claim.
- `pytest`: **302 passed in 9.98 seconds** on run [38301763383](https://github.com/LU9DI/AURIX/actions/runs/38301763383); compile and correctness-focused Ruff checks passed in the same run.
- The canonical source and tests are at the repository root. The duplicate `AURIX-backup-work/source/` tree was removed after the legacy restore workflow reintroduced it; that obsolete workflow was then removed to prevent recurrence.
- The complete uploaded backup and 84 historical release ZIPs remain preserved.

## Retained boundaries

- Historical archives remain recovery evidence, not the active working source.
- Original Git commit history cannot be reconstructed from source ZIPs.
- This remains research software, not production-ready autonomous engineering.
