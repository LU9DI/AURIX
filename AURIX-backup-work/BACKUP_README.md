# AURIX consolidated backup

This archive contains:

- `source/`: sanitized snapshot of the AURIX v0.85.0 source tree (README release status corrected to v0.85.0; excludes caches, build output, `.aurix` runtime state, and egg-info).
- `history/releases/`: previously generated version ZIPs found in the workspace.
- `history/wheels/`: previously generated Python wheels found in the workspace.
- `MANIFEST.sha256`: SHA-256 hashes for every file included, excluding the manifest itself.
- `INVENTORY.txt`: counts and a listing of the archived historical release artifacts.

Important limitation: the historical ZIPs are release snapshots, not a Git commit history. The available files do not prove that every intermediate edit from the beginning of the project is represented. This backup preserves the available evidence and artifacts without claiming otherwise. Runtime state and credentials are deliberately excluded.
