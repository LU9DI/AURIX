"""Bounded context, conservative response caching, and token-budget helpers."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aurix.telemetry import estimate_tokens


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class ContextBudget:
    max_input_tokens: int = 12_000
    reserve_tokens: int = 1_000

    @property
    def usable_tokens(self) -> int:
        return max(256, self.max_input_tokens - self.reserve_tokens)

    def fit(self, prompt: str, *, fixed_tokens: int = 0) -> tuple[str, bool]:
        """Keep task/header and newest evidence within the budget after fixed system tokens."""
        budget = max(256, self.usable_tokens - max(0, int(fixed_tokens)))
        if estimate_tokens(prompt) <= budget:
            return prompt, False
        # Keep the first section (task and initial context) and the most recent tool evidence.
        max_chars = budget * 4
        marker = "\n\n[Earlier context compacted to respect AURIX context budget]\n\n"
        head_budget = max(256, int((max_chars - len(marker)) * 0.42))
        tail_budget = max(256, max_chars - len(marker) - head_budget)
        compacted = prompt[:head_budget] + marker + prompt[-tail_budget:]
        while estimate_tokens(compacted) > budget and tail_budget > 256:
            tail_budget = max(256, int(tail_budget * 0.85))
            compacted = prompt[:head_budget] + marker + prompt[-tail_budget:]
        return compacted, True


class ResponseCache:
    """Small process-local LRU cache for terminal model responses only.

    Tool calls are never cached. The cache stores response text in memory only and uses a
    workspace fingerprint so edits to project files invalidate prior entries.
    """

    def __init__(self, max_entries: int = 128, ttl_seconds: int = 300) -> None:
        self.max_entries = max(1, min(int(max_entries), 2048))
        self.ttl_seconds = max(1, min(int(ttl_seconds), 86_400))
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def workspace_fingerprint(workspace: Path) -> str:
        digest = hashlib.sha256()
        count = 0
        hashed_bytes = 0
        max_file_hash_bytes = 2_000_000
        max_total_hash_bytes = 50_000_000
        try:
            for path in sorted(workspace.rglob("*")):
                try:
                    rel = path.relative_to(workspace)
                    if any(
                        part in {".git", ".aurix", "__pycache__", ".pytest_cache"}
                        for part in rel.parts
                    ):
                        continue
                    if path.is_symlink() or not path.is_file():
                        continue
                    stat = path.stat()
                    digest.update(
                        f"{rel.as_posix()}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode()
                    )
                    if (
                        stat.st_size <= max_file_hash_bytes
                        and hashed_bytes + stat.st_size <= max_total_hash_bytes
                    ):
                        with path.open("rb") as stream:
                            content = stream.read(max_file_hash_bytes + 1)
                        if (
                            len(content) <= max_file_hash_bytes
                            and len(content) == stat.st_size
                            and hashed_bytes + len(content) <= max_total_hash_bytes
                        ):
                            digest.update(hashlib.sha256(content).digest())
                            hashed_bytes += len(content)
                        else:
                            digest.update(b"CONTENT_HASH_SKIPPED")
                    else:
                        digest.update(b"CONTENT_HASH_SKIPPED")
                    count += 1
                    if count >= 20_000:
                        digest.update(b"TRUNCATED")
                        break
                except OSError:
                    continue
        except OSError:
            digest.update(b"WORKSPACE_UNREADABLE")
        return digest.hexdigest()

    def make_key(self, provider: Any, system: str, prompt: str, workspace: Path) -> str:
        identity = ":".join(
            (
                type(provider).__module__,
                type(provider).__qualname__,
                str(getattr(provider, "model", "")),
                str(getattr(provider, "base_url", "")),
            )
        )
        content = "\0".join(
            (identity, str(workspace), self.workspace_fingerprint(workspace), system, prompt)
        )
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

    def get(self, key: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None or item[0] <= now:
                self._items.pop(key, None)
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return item[1]

    def put(self, key: str, response: str) -> None:
        with self._lock:
            self._items[key] = (time.monotonic() + self.ttl_seconds, response)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
