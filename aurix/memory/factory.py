"""Construct the configured persistent memory backend."""

from __future__ import annotations

import os
from pathlib import Path

from aurix.memory.base import MemoryStore
from aurix.memory.sqlite import SQLiteMemory


def create_memory(
    backend: str | None = None,
    *,
    workspace: str | Path = ".",
) -> MemoryStore:
    """Create a memory store without making Neon a mandatory dependency.

    ``AURIX_MEMORY_BACKEND`` accepts ``sqlite`` (default) or ``postgres``.
    SQLite's default database lives under ``<workspace>/.aurix/memory.db``.
    PostgreSQL credentials are read only from ``DATABASE_URL``.
    """
    selected = (backend or os.getenv("AURIX_MEMORY_BACKEND", "sqlite")).strip().lower()
    root = Path(workspace).expanduser().resolve()
    if selected == "sqlite":
        configured_path = os.getenv("AURIX_MEMORY_PATH")
        path = (
            Path(configured_path).expanduser() if configured_path else root / ".aurix" / "memory.db"
        )
        if not path.is_absolute():
            path = root / path
        return SQLiteMemory(path)
    if selected in {"postgres", "neon"}:
        from aurix.memory.postgres import PostgresMemory

        return PostgresMemory()
    raise ValueError("memory backend must be 'sqlite' or 'postgres'")
