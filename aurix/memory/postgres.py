"""Optional PostgreSQL/Neon backend. Install with `pip install -e ".[neon]"`."""

import json
import os
from typing import Any

from aurix.memory.schema import validate_metadata


class PostgresMemory:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL is required")
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError('Install the optional dependency: pip install -e ".[neon]"') from exc
        self._psycopg = psycopg
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS aurix_memories (
                id BIGSERIAL PRIMARY KEY, scope TEXT NOT NULL, content TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS aurix_memories_scope_idx ON aurix_memories(scope)"
            )

    def _connect(self):
        return self._psycopg.connect(self.database_url, connect_timeout=5)

    def add(self, scope: str, content: str, metadata: dict[str, Any] | None = None) -> int:
        if (
            not isinstance(scope, str)
            or not isinstance(content, str)
            or not scope.strip()
            or not content.strip()
        ):
            raise ValueError("scope and content must be non-empty strings")
        metadata = validate_metadata(metadata)
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO aurix_memories(scope, content, metadata) VALUES (%s, %s, %s::jsonb) RETURNING id",
                (scope, content, json.dumps(metadata, ensure_ascii=False)),
            ).fetchone()
            return int(row[0])

    def search(
        self, query: str, *, scope: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        pattern = "%" + query.strip().replace("%", r"\%").replace("_", r"\_") + "%"
        with self._connect() as conn:
            if scope:
                rows = conn.execute(
                    "SELECT id,scope,content,metadata,created_at FROM aurix_memories WHERE scope=%s AND content ILIKE %s ORDER BY id DESC LIMIT %s",
                    (scope, pattern, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id,scope,content,metadata,created_at FROM aurix_memories WHERE content ILIKE %s ORDER BY id DESC LIMIT %s",
                    (pattern, limit),
                ).fetchall()
        return [
            {
                "id": r[0],
                "scope": r[1],
                "content": r[2],
                "metadata": r[3],
                "created_at": r[4].isoformat(),
            }
            for r in rows
        ]

    def delete(self, memory_id: int, *, scope: str | None = None) -> bool:
        if isinstance(memory_id, bool) or not isinstance(memory_id, int) or memory_id < 1:
            raise ValueError("memory_id must be a positive integer")
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM aurix_memories WHERE id = %s"
                if scope is None
                else "DELETE FROM aurix_memories WHERE id = %s AND scope = %s",
                (memory_id,) if scope is None else (memory_id, scope),
            )
            return cursor.rowcount == 1

    def clear(self, *, scope: str | None = None) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM aurix_memories"
                if scope is None
                else "DELETE FROM aurix_memories WHERE scope = %s",
                () if scope is None else (scope,),
            )
            return int(cursor.rowcount)
