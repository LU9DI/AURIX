"""Durable, provenance-aware memory for autonomous research discoveries.

Retrieved web excerpts and model-generated hypotheses are always untrusted candidates.
Only an explicit operator review can promote a record to validated knowledge.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

KINDS = {"retrieved_evidence", "model_hypothesis", "validated_knowledge"}
STATUSES = {"candidate", "accepted", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value.strip()[:2048]


def parse_research_blocks(source_notes: str) -> list[dict[str, str]]:
    """Parse adapter output into bounded source records without treating text as trusted."""
    blocks: list[dict[str, str]] = []
    for raw in re.split(r"\n\s*---\s*\n", source_notes or "")[:10]:
        fields: dict[str, str] = {}
        current = None
        for line in raw.splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                if key in {"SOURCE", "TITLE", "SEARCH SNIPPET", "PAGE EXTRACT"}:
                    current = key
                    fields[key] = value[:6000]
                    continue
            if current in {"SEARCH SNIPPET", "PAGE EXTRACT"} and line.strip():
                fields[current] = (fields.get(current, "") + " " + line.strip())[:6000]
        url = _safe_url(fields.get("SOURCE"))
        if not url:
            continue
        blocks.append({"url": url, "title": fields.get("TITLE", "Untitled")[:300],
                       "snippet": fields.get("SEARCH SNIPPET", "")[:1200],
                       "excerpt": fields.get("PAGE EXTRACT", "")[:6000]})
    return blocks


class ResearchMemory:
    def __init__(self, path: str | Path = ".aurix/research_memory.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS discoveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                topic TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'candidate',
                url TEXT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                reviewed_at TEXT,
                learning_record_id INTEGER,
                metadata TEXT NOT NULL DEFAULT '{}'
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_discoveries_status_time ON discoveries(status, captured_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_discoveries_topic ON discoveries(topic)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def add(self, *, topic: str, kind: str, title: str, content: str, url: str | None = None,
            learning_record_id: int | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(KINDS))}")
        if not isinstance(topic, str) or not topic.strip() or len(topic) > 500:
            raise ValueError("topic must be non-empty and at most 500 characters")
        if not isinstance(content, str) or not content.strip() or len(content) > 12000:
            raise ValueError("content must be non-empty and at most 12000 characters")
        safe_url = _safe_url(url)
        # Source URLs deduplicate by canonical URL + content; hypotheses by topic + content.
        identity = (safe_url or "").casefold() + "\0" + kind + "\0" + " ".join(content.split()).casefold()
        if not safe_url:
            identity = topic.casefold() + "\0" + kind + "\0" + " ".join(content.split()).casefold()
        fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO discoveries(fingerprint, topic, kind, status, url, title, content, captured_at, learning_record_id, metadata) VALUES (?, ?, ?, 'candidate', ?, ?, ?, ?, ?, ?)",
                         (fingerprint, " ".join(topic.split()), kind, safe_url, (title or "Untitled")[:300], content[:12000],
                          _now(), learning_record_id, json.dumps(metadata or {}, ensure_ascii=False)[:4000]))
            row = conn.execute("SELECT * FROM discoveries WHERE fingerprint = ?", (fingerprint,)).fetchone()
        return self._row(row)

    def review(self, record_id: int, *, decision: str) -> bool:
        if decision not in {"accepted", "rejected"}:
            raise ValueError("decision must be accepted or rejected")
        with self._connect() as conn:
            cur = conn.execute("UPDATE discoveries SET status = ?, kind = CASE WHEN ? = 'accepted' THEN 'validated_knowledge' ELSE kind END, reviewed_at = ? WHERE id = ? AND status = 'candidate'",
                               (decision, decision, _now(), int(record_id)))
            return cur.rowcount == 1

    def list_records(self, *, status: str | None = None, topic: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")
        limit = max(1, min(int(limit), 500))
        clauses, params = [], []
        if status:
            clauses.append("status = ?"); params.append(status)
        if topic:
            clauses.append("topic LIKE ?"); params.append("%" + topic[:200] + "%")
        sql = "SELECT * FROM discoveries" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [self._row(row) for row in conn.execute(sql, params).fetchall()]

    def search_relevant(self, query: str, *, accepted_only: bool = True, limit: int = 5,
                        max_content_chars: int = 1800) -> list[dict[str, Any]]:
        """Bounded lexical retrieval; excludes unreviewed candidates by default."""
        terms = {token.casefold() for token in re.findall(r"[\w.-]{2,}", query, flags=re.UNICODE)}
        if not terms:
            return []
        limit = max(1, min(int(limit), 20))
        max_content_chars = max(100, min(int(max_content_chars), 6000))
        with self._connect() as conn:
            if accepted_only:
                rows = conn.execute("SELECT * FROM discoveries WHERE status = 'accepted' ORDER BY id DESC LIMIT 500").fetchall()
            else:
                rows = conn.execute("SELECT * FROM discoveries WHERE status != 'rejected' ORDER BY id DESC LIMIT 500").fetchall()
        ranked = []
        for row in rows:
            content = f"{row['topic']} {row['title']} {row['content']}"
            found = terms & {token.casefold() for token in re.findall(r"[\w.-]{2,}", content, flags=re.UNICODE)}
            if not found:
                continue
            item = self._row(row)
            item["relevance_score"] = round(len(found) / len(terms), 4)
            item["content"] = item["content"][:max_content_chars]
            ranked.append(item)
        ranked.sort(key=lambda item: (item["relevance_score"], item["id"]), reverse=True)
        return ranked[:limit]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT kind, status, COUNT(*) AS n FROM discoveries GROUP BY kind, status").fetchall()
        return {f"{row['kind']}:{row['status']}": int(row['n']) for row in rows}

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": int(row["id"]), "topic": row["topic"], "kind": row["kind"], "status": row["status"],
                "url": row["url"], "title": row["title"], "content": row["content"],
                "captured_at": row["captured_at"], "reviewed_at": row["reviewed_at"],
                "learning_record_id": row["learning_record_id"], "metadata": json.loads(row["metadata"])}
