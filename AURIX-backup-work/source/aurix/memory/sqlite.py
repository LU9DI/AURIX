import json
import sqlite3
from pathlib import Path
from typing import Any

from aurix.memory.schema import validate_metadata


class SQLiteMemory:
    """Local memory store; only explicitly supplied records are persisted."""

    def __init__(self, path: str | Path = ".aurix/memory.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, scope: str, content: str, metadata: dict[str, Any] | None = None) -> int:
        if not isinstance(scope, str) or not isinstance(content, str) or not scope.strip() or not content.strip():
            raise ValueError("scope and content must be non-empty strings")
        metadata = validate_metadata(metadata)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO memories(scope, content, metadata) VALUES (?, ?, ?)",
                (scope, content, json.dumps(metadata, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def search(self, query: str, *, scope: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        terms = [t for t in query.lower().split() if len(t) > 1][:8]
        sql, params, clauses = "SELECT * FROM memories", [], []
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if terms:
            clauses.append("(" + " OR ".join("lower(content) LIKE ?" for _ in terms) + ")")
            params.extend(f"%{term}%" for term in terms)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{"id": r["id"], "scope": r["scope"], "content": r["content"],
                 "metadata": json.loads(r["metadata"]), "created_at": r["created_at"]} for r in rows]
