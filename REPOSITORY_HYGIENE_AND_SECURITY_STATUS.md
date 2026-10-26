# AURIX repository hygiene and security status

Review date: 2026-10-26
Scope: repository tree, package metadata, CI workflow, and the archived audit notes. Static review only.

## Current verified state

- The active Python package is at repository root: `pyproject.toml` and `aurix/`.
- The root CI workflow is `.github/workflows/ci.yml`; it installs `.[dev]`, compiles source/tests, runs Ruff, and runs pytest.
- `AURIX-backup-work/` contains a consolidated backup, historical ZIP releases, wheels, inventory, and a SHA-256 manifest. It is archival material, not the active package source.
- `AURIX-backup-work/AUDIT_REPORT.md` and `AUDIT_FINDINGS_2026-10-09.md` contain historical statements that conflict with the current root package/workflow layout (including statements that the repository is empty or that the package only exists inside the backup). Treat those statements as historical snapshots, not current-state evidence.
- The package supports Python 3.11+ and declares bounded major-version ranges, but no fully resolved dependency lockfile was found in the root tree.

## Organization recommendations

1. Preserve `AURIX-backup-work/` until the manifest and historical artifacts have been independently verified and a retention decision is documented.
2. Keep active source, tests, package metadata, and CI at repository root. Do not copy source back out of the archive unless the active root files are missing.
3. In future cleanup, consider moving historical release ZIPs and wheels to GitHub Releases or external artifact storage to reduce repository weight, while retaining the manifest and provenance.
4. Add a reproducible dependency lock strategy for CI and release builds; avoid unpinned transitive dependency resolution for release artifacts.
5. Re-run the SSRF, robots.txt, workspace boundary, and execution-sandbox regression tests against the current source before relying on older audit results.

## Scope limitations

The older audit findings were not assumed to still apply. This review confirmed the current root package layout and the public-IP-pinning transport in `aurix/research.py`, but did not execute the test suite, pip-audit, or a live network security test. No claim of production readiness or zero vulnerabilities is made.
