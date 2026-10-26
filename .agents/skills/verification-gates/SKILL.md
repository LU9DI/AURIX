---
name: verification-gates
description: Apply spec-first planning, small reversible changes, automated verification, and evidence-of-done reporting to engineering tasks.
---

# Verification Gates

Use for code changes, experiments, CI repairs, security reviews, data pipelines, and releases.

## Required workflow

1. State the intended behavior, constraints, and observable acceptance checks before editing.
2. Inspect the current implementation and existing tests; do not infer missing behavior from filenames alone.
3. Make one narrow, reversible change at a time. Preserve existing public contracts unless the task explicitly authorizes a change.
4. Add or update tests that demonstrate the behavior and cover relevant failure paths.
5. Run the most targeted checks first, then the repository's full required validation when practical.
6. Report exact commands/checks and their outcomes. Separate passed, failed, skipped, and not-run checks.
7. Treat a green unit test as evidence only for the tested behavior; do not infer production readiness or successful deployment.
8. Never bypass a failing gate by weakening assertions, disabling security checks, suppressing errors, or claiming a check passed when it did not.
9. Do not deploy, publish, delete data, rotate production credentials, or trigger real external side effects without explicit authorization.
10. When evidence is incomplete, state what remains unknown and stop short of declaring completion.

## Completion report

- Change summary
- Files changed
- Tests and checks run, with exact result
- Risks and unverified assumptions
- Follow-up required
