"""Backend-independent memory interface used by AURIX."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryStore(Protocol):
    """Minimal contract shared by local SQLite and PostgreSQL/Neon stores."""

    def add(self, scope: str, content: str, metadata: dict[str, Any] | None = None) -> int:
        """Persist one explicitly supplied memory and return its identifier."""
        ...

    def search(
        self, query: str, *, scope: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return recent matching records, optionally constrained to a scope."""
        ...

    def delete(self, memory_id: int, *, scope: str | None = None) -> bool:
        """Delete one record, optionally requiring that it belongs to a scope."""
        ...

    def clear(self, *, scope: str | None = None) -> int:
        """Delete all records, or all records in one scope; return the count."""
        ...
