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

## Dependency audit result and remediation

The first audit attempt scanned the runner's global Python environment and reported unrelated system packages; that result was discarded. The corrected isolated audit identified `pytest 8.4.2` in the project's development dependencies as affected by `PYSEC-2026-1845`, with `pytest 9.0.3` listed as the fix. This PR raises the development constraint to `pytest>=9.0.3,<10`; the CI and isolated audit must pass on the updated commit before the remediation is considered verified.

## Scope limitations

The older audit findings were not assumed to still apply. This review confirmed the current root package layout and the public-IP-pinning transport in `aurix/research.py`. No live network security test or production penetration test was performed, and no claim of production readiness is made.
