# AURIX recovery and repository normalization report

Updated: 2026-10-12

## Publication state

The recovered v0.85.0 project is normalized in the repository root as the canonical working tree:
- Python package: `aurix/`
- Tests: `tests/`
- Project configuration: `pyproject.toml`
- CI: `.github/workflows/ci.yml`
- Main documentation: `README.md`

The uploaded complete backup and historical snapshots remain preserved under `AURIX-backup-work/` and as the original ZIP at the repository root. Original Git history was not reconstructed because source archives do not preserve commit ancestry, authorship, branches, tags, or diffs.

## Validation

The previous recovery process checked the locally available archive manifest and historical ZIP structure. Those checks do not substitute for CI on the normalized working tree. The root CI workflow runs compileall, Ruff, and pytest on Python 3.11. The latest GitHub Actions result is the source of truth for whether all checks pass.

## Known limitations

- Historical source files may retain old version references.
- The project is in active development (pre-1.0) and has not had an independent security audit.
- Do not execute untrusted project code on the host; the default `trusted` verification mode is not an OS sandbox.
