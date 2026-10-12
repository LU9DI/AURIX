# AURIX remediation log

Date: 2026-10-12  
Branch: `fix/audit-gaps-repository-hardening`

## Changes in this remediation set

- Normalize the recovered Python project to the repository root while retaining the uploaded ZIP and historical archive area.
- Activate root-level CI for Python 3.11, compileall, Ruff, and pytest.
- Fix the `robots.txt` disallow branch by constructing the source summary before the branch can append it.
- Add a pinned outbound HTTP transport for research retrieval: resolve once per request, reject non-public answers, connect to the validated IP, preserve TLS hostname verification, disable redirects, and bound response buffering.
- Add scoped `delete` and `clear` operations to the memory protocol and SQLite/PostgreSQL backends, with tests.
- Strengthen response-cache invalidation by hashing file contents within explicit per-file and total byte budgets; add a regression test for same-size changes with preserved timestamps.
- Require HTTPS for remote OpenAI-compatible providers and allow plain HTTP only for loopback endpoints; add regression tests.
- Normalize legacy formatting and configure CI to enforce syntax, unused-name/import, and core error checks while excluding the repository's existing long-line style debt.
- Update the root README and recovery report.

## Validation gate

Do not merge until the root CI workflow finishes successfully. Compile success alone does not establish test correctness or security. Any Ruff or pytest failures must be corrected. Production use still requires network egress controls; the default trusted test mode is not a sandbox.

## Retained boundaries

- Historical archives remain recovery evidence, not the active working source.
- Original Git commit history cannot be reconstructed from source ZIPs.
- This remains research software, not production-ready autonomous engineering.
