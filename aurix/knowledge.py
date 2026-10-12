"""Local, dependency-free retrieval for AURIX knowledge bases.

This is lexical retrieval (not a vector database): it works offline, requires no
embeddings or model tokens, preserves source paths, and never executes indexed content.
"""

from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path
from typing import Any

SUPPORTED_SUFFIXES = {
    ".txt",
    ".md",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".log",
    ".csv",
}
EXCLUDED_PARTS = {
    ".git",
    ".aurix",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
}
WORD_RE = re.compile(r"[\w.-]{2,}", re.UNICODE)


def _terms(text: str) -> list[str]:
    return [w.casefold() for w in WORD_RE.findall(text)]


def _chunks(text: str, size: int = 1800, overlap: int = 180) -> list[str]:
    if not 300 <= size <= 8000 or not 0 <= overlap < size:
        raise ValueError("chunk size must be 300..8000 and overlap must be smaller than size")
    text = text.replace("\r\n", "\n")
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


class KnowledgeIndex:
    """Persistent SQLite index with a small BM25-like ranker."""

    def __init__(self, path: str | Path = ".aurix/knowledge.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, fingerprint TEXT NOT NULL,
                chunk_no INTEGER NOT NULL, content TEXT NOT NULL, terms TEXT NOT NULL,
                UNIQUE(source, fingerprint, chunk_no))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)")
            conn.execute("""CREATE TABLE IF NOT EXISTS indexed_sources (
                root TEXT NOT NULL, source TEXT NOT NULL, fingerprint TEXT NOT NULL,
                PRIMARY KEY(root, source))""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_indexed_sources_root ON indexed_sources(root)"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def index_path(
        self,
        path: str | Path,
        *,
        max_file_bytes: int = 5_000_000,
        max_files: int = 20_000,
        chunk_chars: int = 1800,
    ) -> dict[str, Any]:
        """Incrementally index a file or directory and remove stale entries for that root.

        Unchanged files are not re-read into SQLite. Deletions are applied only after a
        complete scan; if the file limit truncates a scan, stale-source cleanup is skipped.
        Symlinks and excluded directories are never traversed or indexed.
        """
        import hashlib

        requested_root = Path(path).expanduser()
        if requested_root.is_symlink():
            raise ValueError("index path must exist and must not be a symlink")
        root = requested_root.resolve()
        if not root.exists():
            raise ValueError("index path must exist and must not be a symlink")
        root_key = str(root)
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        indexed_files = unchanged_files = skipped_files = indexed_chunks = removed_files = 0
        seen_sources: set[str] = set()
        scanned_supported = 0
        scan_complete = True

        for candidate in candidates:
            try:
                if (
                    candidate.is_symlink()
                    or not candidate.is_file()
                    or candidate.suffix.lower() not in SUPPORTED_SUFFIXES
                ):
                    continue
                rel_parts = candidate.relative_to(root if root.is_dir() else root.parent).parts
                if any(part in EXCLUDED_PARTS for part in rel_parts):
                    continue
                source = str(candidate.resolve())
                seen_sources.add(source)
                scanned_supported += 1
                if scanned_supported > max_files:
                    scan_complete = False
                    break
                if candidate.stat().st_size > max_file_bytes:
                    skipped_files += 1
                    continue
                raw = candidate.read_text(encoding="utf-8", errors="replace")
                if not raw.strip() or "\x00" in raw[:4096]:
                    skipped_files += 1
                    continue
                fingerprint = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
                with self._connect() as conn:
                    previous = conn.execute(
                        "SELECT fingerprint FROM indexed_sources WHERE root = ? AND source = ?",
                        (root_key, source),
                    ).fetchone()
                    if previous is not None and previous["fingerprint"] == fingerprint:
                        unchanged_files += 1
                        continue
                    chunks = _chunks(raw, size=chunk_chars)
                    conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
                    for i, chunk in enumerate(chunks):
                        conn.execute(
                            "INSERT INTO chunks(source, fingerprint, chunk_no, content, terms) VALUES (?, ?, ?, ?, ?)",
                            (source, fingerprint, i, chunk, " ".join(_terms(chunk))),
                        )
                    conn.execute(
                        "INSERT INTO indexed_sources(root, source, fingerprint) VALUES (?, ?, ?) "
                        "ON CONFLICT(root, source) DO UPDATE SET fingerprint = excluded.fingerprint",
                        (root_key, source, fingerprint),
                    )
                indexed_files += 1
                indexed_chunks += len(chunks)
            except (OSError, UnicodeError, ValueError):
                skipped_files += 1

        # Never prune after a truncated scan. Scope cleanup to the exact root so indexing
        # overlapping roots cannot accidentally delete each other's source registrations.
        if root.is_file():
            active_sources = {str(root)} if root.exists() else set()
        else:
            active_sources = seen_sources
        if scan_complete:
            with self._connect() as conn:
                tracked = conn.execute(
                    "SELECT source FROM indexed_sources WHERE root = ?", (root_key,)
                ).fetchall()
                stale = [row["source"] for row in tracked if row["source"] not in active_sources]
                for source in stale:
                    conn.execute(
                        "DELETE FROM indexed_sources WHERE root = ? AND source = ?",
                        (root_key, source),
                    )
                    other_owner = conn.execute(
                        "SELECT 1 FROM indexed_sources WHERE source = ? LIMIT 1", (source,)
                    ).fetchone()
                    if other_owner is None:
                        conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
                # Migrate legacy entries created before root ownership metadata existed.
                # Restrict the cleanup to paths physically inside this root.
                if root.is_dir():
                    all_sources = conn.execute("SELECT DISTINCT source FROM chunks").fetchall()
                    for row in all_sources:
                        source = row["source"]
                        try:
                            inside_root = Path(source).is_relative_to(root)
                        except (OSError, ValueError):
                            inside_root = False
                        if inside_root and source not in active_sources:
                            owner = conn.execute(
                                "SELECT 1 FROM indexed_sources WHERE source = ? LIMIT 1", (source,)
                            ).fetchone()
                            if owner is None:
                                conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
                                removed_files += 1
                else:
                    # A single-file sync has an exact source identity.
                    if str(root) not in active_sources:
                        owner = conn.execute(
                            "SELECT 1 FROM indexed_sources WHERE source = ? LIMIT 1", (str(root),)
                        ).fetchone()
                        if owner is None:
                            conn.execute("DELETE FROM chunks WHERE source = ?", (str(root),))
                removed_files = max(removed_files, len(stale))

        return {
            "indexed_files": indexed_files,
            "unchanged_files": unchanged_files,
            "indexed_chunks": indexed_chunks,
            "removed_files": removed_files,
            "skipped_files": skipped_files,
            "scan_complete": scan_complete,
            "database": str(self.path),
        }

    def search(self, query: str, *, limit: int = 5, max_chars: int = 1800) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be non-empty text")
        limit = max(1, min(int(limit), 20))
        terms = list(dict.fromkeys(_terms(query)))
        if not terms:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, source, chunk_no, content, terms FROM chunks"
            ).fetchall()
        if not rows:
            return []
        n = len(rows)
        df = {term: sum(1 for row in rows if term in set(row["terms"].split())) for term in terms}
        scored = []
        for row in rows:
            doc_terms = row["terms"].split()
            if not doc_terms:
                continue
            counts: dict[str, int] = {}
            for term in doc_terms:
                counts[term] = counts.get(term, 0) + 1
            score = 0.0
            for term in terms:
                freq = counts.get(term, 0)
                if freq:
                    idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                    score += (
                        idf * (freq * 2.2) / (freq + 1.2 * (0.25 + 0.75 * len(doc_terms) / 300))
                    )
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["source"], pair[1]["chunk_no"]))
        return [
            {
                "source": row["source"],
                "chunk": row["chunk_no"] + 1,
                "score": round(score, 4),
                "content": row["content"][:max_chars],
            }
            for score, row in scored[:limit]
        ]

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS chunks, COUNT(DISTINCT source) AS files FROM chunks"
            ).fetchone()
        return {"files": int(row["files"]), "chunks": int(row["chunks"])}
