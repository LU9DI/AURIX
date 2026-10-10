# AURIX backup and repository audit

Audit date: 2026-10-09 (workspace artifacts were timestamped around 2026-10-10 UTC).

## Findings

- Latest source snapshot identifies package version `0.85.0` in `pyproject.toml`.
- Snapshot includes the Python package, 32 test modules, CI workflow, README, CHANGELOG, architecture/safety docs, project metadata, and contributing/license files.
- README's release-status banner was stale (`v0.43.0`); the backup snapshot corrects that banner to `v0.85.0` while retaining the warning that this remains a research release and is not production-ready autonomous engineering software.
- The working folder had no `.git` directory, so it did not contain a local commit history.
- The GitHub repository `LU9DI/AURIX` exists and is public, but the repository API reports it as empty. No source code was published in this operation.
- The consolidated archive preserves the available historical ZIP release artifacts and Python wheels found in `/mnt/data`. These are release snapshots, not proof of a complete, lossless history of every change since project inception.
- Runtime state (`.aurix`), bytecode, test caches, build output, and egg-info are excluded from the clean source snapshot. No `.env`, private key, or token-named files were found in the inspected project tree.

## Validation

- Consolidated ZIP integrity: passed (`unzip -t`, no errors).
- Targeted regression tests: 87 tests passed across workspace, verification, patch, and audit test modules.
- Full test suite: execution reached approximately 97% in the available run but did not return a final summary before the execution environment timed out. Therefore, a full-suite pass is **not** claimed.
- Ruff lint: not run successfully because Ruff is not installed in the execution environment. It is declared in the project's development dependencies and configured in GitHub Actions.
- SHA-256 manifest: included for the files inside this backup (excluding the manifest itself).

## Next step for GitHub publication

The repository is empty and the available GitHub connector supports individual Git object/file operations, but no bulk local-directory push operation was available in this execution environment. To avoid publishing a misleading partial repository, this operation creates a verified offline backup instead of uploading only a subset of files.
