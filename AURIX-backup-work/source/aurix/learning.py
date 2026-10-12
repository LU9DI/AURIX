"""Evidence-gated continual-learning primitives for AURIX.

This module deliberately separates persistent memory, user feedback, and training
eligibility. It never trains model weights by itself and never treats arbitrary
web/model output as trusted truth. Training export is opt-in per record.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = {"candidate", "accepted", "rejected"}
SOURCES = {"user_feedback", "task_outcome", "peer_model", "web_research", "local_tool"}


class LearningStore:
    """Local store for learning candidates, feedback, and explicitly approved examples."""

    def __init__(self, path: str | Path = ".aurix/learning.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS learning_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'candidate',
                quality REAL,
                consent_to_train INTEGER NOT NULL DEFAULT 0,
                evidence TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            )""")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_candidate(
        self,
        content: str,
        *,
        scope: str = "default",
        source: str = "task_outcome",
        quality: float | None = None,
        evidence: list[str] | None = None,
        consent_to_train: bool = False,
    ) -> int:
        """Record a candidate insight; candidate status is never trusted by default."""
        if not isinstance(content, str) or not content.strip() or len(content) > 100_000:
            raise ValueError("content must be non-empty text of at most 100000 characters")
        if not isinstance(scope, str) or not scope.strip() or len(scope) > 200:
            raise ValueError("scope must be non-empty text of at most 200 characters")
        if source not in SOURCES:
            raise ValueError(f"source must be one of: {', '.join(sorted(SOURCES))}")
        if quality is not None and (isinstance(quality, bool) or not isinstance(quality, (int, float)) or not 0 <= quality <= 1):
            raise ValueError("quality must be between 0 and 1")
        if type(consent_to_train) is not bool:
            raise ValueError("consent_to_train must be a boolean")
        evidence = evidence or []
        if not isinstance(evidence, list) or any(not isinstance(item, str) or len(item) > 2000 for item in evidence):
            raise ValueError("evidence must be a list of strings, each at most 2000 characters")
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO learning_records(scope, source, content, status, quality, consent_to_train, evidence, created_at) VALUES (?, ?, ?, 'candidate', ?, ?, ?, ?)",
                (scope, source, content, quality, int(consent_to_train), json.dumps(evidence, ensure_ascii=False), timestamp),
            )
            return int(cur.lastrowid)

    def review(self, record_id: int, *, decision: str, quality: float | None = None) -> bool:
        """Accept/reject a candidate after review; acceptance alone does not imply training consent."""
        if decision not in {"accepted", "rejected"}:
            raise ValueError("decision must be 'accepted' or 'rejected'")
        if quality is not None and (isinstance(quality, bool) or not isinstance(quality, (int, float)) or not 0 <= quality <= 1):
            raise ValueError("quality must be between 0 and 1")
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE learning_records SET status = ?, quality = COALESCE(?, quality), reviewed_at = ? WHERE id = ? AND status = 'candidate'",
                (decision, quality, timestamp, int(record_id)),
            )
            return cur.rowcount == 1

    def list_records(self, *, scope: str | None = None, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")
        clauses: list[str] = []
        params: list[Any] = []
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        query = "SELECT * FROM learning_records"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row(row) for row in rows]

    def export_training_jsonl(self, destination: str | Path, *, min_quality: float = 0.8, scope: str | None = None) -> int:
        """Export only accepted records with explicit training consent and sufficient quality."""
        if isinstance(min_quality, bool) or not isinstance(min_quality, (int, float)) or not 0 <= min_quality <= 1:
            raise ValueError("min_quality must be between 0 and 1")
        clauses = ["status = 'accepted'", "consent_to_train = 1", "quality >= ?"]
        params: list[Any] = [min_quality]
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM learning_records WHERE " + " AND ".join(clauses) + " ORDER BY id", params).fetchall()
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps({"text": row["content"], "source": row["source"], "scope": row["scope"], "quality": row["quality"], "evidence": json.loads(row["evidence"])}, ensure_ascii=False) + "\n")
        return len(rows)

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "scope": row["scope"], "source": row["source"], "content": row["content"],
                "status": row["status"], "quality": row["quality"], "consent_to_train": bool(row["consent_to_train"]),
                "evidence": json.loads(row["evidence"]), "created_at": row["created_at"], "reviewed_at": row["reviewed_at"]}
