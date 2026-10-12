"""Privacy-conscious JSONL telemetry for local AURIX runs.

Records metadata only; prompts and completions are deliberately never persisted.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def estimate_tokens(text: str) -> int:
    """Cheap, language-agnostic rough estimate; not a tokenizer or billing figure."""
    return (len(text) + 3) // 4


class JSONLTelemetry:
    def __init__(self, path: str | Path | None = None) -> None:
        configured = path or os.getenv("AURIX_TELEMETRY_PATH", ".aurix/runs.jsonl")
        self.path = Path(configured)

    def record(self, event: dict[str, Any]) -> None:
        safe = dict(event)
        safe.setdefault("timestamp", datetime.now(UTC).isoformat())
        line = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
