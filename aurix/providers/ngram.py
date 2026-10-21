"""CPU-only code-continuation provider: no GPU, no neural network, no tokens, no network.

A byte-level n-gram language model (interpolated absolute discounting, orders 0..K) is built
from source files under a workspace root and used to continue a text prefix.

What it is: a *completion* engine over the project's own code. It reproduces and recombines
patterns that already exist in the corpus, at essentially zero compute (table lookups).

What it is not: an instruction-following model. ``system`` is ignored and the ``prompt`` is
treated as a code prefix, not as a request. Use it behind a tiered provider for routine
completions and keep a real language model for tasks that need instruction following.

Cost is memory, not FLOPs: tables grow with the corpus, so the corpus is capped.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_EXTENSIONS = (".py", ".js", ".ts", ".tsx", ".rs", ".go", ".java", ".sql", ".sh")
SKIPPED_DIRS = {
    ".git",
    ".hg",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".aurix",
    "dist",
    "build",
    "target",
}
SEPARATOR = b"\n\x00\n"
HARD_MAX_OUTPUT_BYTES = 4096
MAX_ORDER = 16
EXACT_ORDER = 7  # contexts up to 7 bytes are exact; longer ones use a 56-bit rolling hash
_PRIME = 0x100000001B3
_MASK64 = (1 << 64) - 1
_M1 = 0xBF58476D1CE4E5B9  # splitmix64 finaliser constants
_M2 = 0x94D049BB133111EB


def _mix(h: int) -> int:
    """Avalanche a 64-bit value so every input bit influences the high bits we keep."""
    h ^= h >> 30
    h = (h * _M1) & _MASK64
    h ^= h >> 27
    h = (h * _M2) & _MASK64
    h ^= h >> 31
    return h


def _numpy():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "The 'ngram' provider needs numpy. Install it with: pip install 'aurix-agent[cpu-lm]'"
        ) from exc
    return np


def collect_corpus(
    root: str | os.PathLike[str],
    *,
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    max_file_bytes: int = 300_000,
    max_total_bytes: int = 3_000_000,
) -> bytes:
    """Read UTF-8 source files under ``root`` deterministically.

    Symlinks (files and directories) are never followed, so the corpus cannot escape ``root``.
    Files that are empty, too large or not valid UTF-8 are skipped; exact duplicates are dropped.
    """
    base = Path(root).resolve()
    chunks: list[bytes] = []
    seen: set[bytes] = set()
    total = 0
    skipped = {name.casefold() for name in SKIPPED_DIRS}
    allowed_extensions = {ext.casefold() for ext in extensions}
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if d.casefold() not in skipped and not (Path(dirpath) / d).is_symlink()
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.casefold() not in allowed_extensions or path.is_symlink():
                continue
            try:
                if path.stat().st_size > max_file_bytes:
                    continue
                data = path.read_bytes()
                data.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if not data or data in seen:
                continue
            if total + len(data) > max_total_bytes:
                return SEPARATOR.join(chunks)
            seen.add(data)
            chunks.append(data)
            total += len(data) + len(SEPARATOR)
    return SEPARATOR.join(chunks)


class NgramModel:
    """Byte n-gram model with interpolated absolute discounting."""

    def __init__(self, data: bytes, order: int = 6, discount: float | None = 0.75) -> None:
        if not data:
            raise ValueError("empty corpus")
        if not 1 <= order <= MAX_ORDER:
            raise ValueError(f"order must be between 1 and {MAX_ORDER}")
        if discount is not None and not 0.0 < discount < 1.0:
            raise ValueError("discount must be between 0 and 1")
        np = _numpy()
        self._np = np
        self.order = order
        self.discount = (
            discount  # None -> estimate per order from count-of-counts (measured worse here)
        )
        self.discounts: list[float] = []
        x = np.frombuffer(data, dtype=np.uint8)
        self._tables = []
        for k in range(order + 1):
            ctx = self._contexts(x, k)
            keys = ctx * np.uint64(256) + x.astype(np.uint64)
            uniq, counts = np.unique(keys, return_counts=True)
            uctx, inverse = np.unique(uniq // np.uint64(256), return_inverse=True)
            totals = np.bincount(inverse, weights=counts)
            distinct = np.bincount(inverse)
            self._tables.append((uniq, counts.astype(np.int32), uctx, totals, distinct))
            if discount is not None:
                self.discounts.append(discount)
            else:
                n1 = float((counts == 1).sum())
                n2 = float((counts == 2).sum())
                est = n1 / (n1 + 2.0 * n2) if n1 + n2 else 0.75
                self.discounts.append(min(0.95, max(0.05, est)))

    def _contexts(self, x, k: int):
        """Context id of the ``k`` bytes before each position (zero padded at the start)."""
        np = self._np
        if k == 0:
            return np.zeros(len(x), dtype=np.uint64)
        padded = np.concatenate([np.zeros(k, dtype=np.uint8), x]).astype(np.uint64)
        ctx = np.zeros(len(x), dtype=np.uint64)
        if k <= EXACT_ORDER:
            for j in range(k):
                ctx = ctx * np.uint64(256) + padded[j : j + len(x)]
            return ctx
        prime = np.uint64(_PRIME)
        with np.errstate(over="ignore"):
            for j in range(k):
                ctx = ctx * prime + (padded[j : j + len(x)] + np.uint64(1))
            ctx ^= ctx >> np.uint64(30)
            ctx *= np.uint64(_M1)
            ctx ^= ctx >> np.uint64(27)
            ctx *= np.uint64(_M2)
            ctx ^= ctx >> np.uint64(31)
        return ctx >> np.uint64(8)

    def _context_value(self, history: bytes, k: int) -> int:
        if k == 0:
            return 0
        tail = history[-k:]
        padded = b"\x00" * (k - len(tail)) + tail
        if k <= EXACT_ORDER:
            value = 0
            for byte in padded:
                value = value * 256 + byte
            return value
        h = 0
        for byte in padded:
            h = (h * _PRIME + byte + 1) & _MASK64
        return _mix(h) >> 8

    def next_distribution(self, history: bytes):
        """Return a length-256 probability vector for the byte following ``history``."""
        np = self._np
        p = np.full(256, 1.0 / 256.0)
        for k in range(self.order + 1):
            uniq, counts, uctx, totals, distinct = self._tables[k]
            ctx = np.uint64(self._context_value(history, k))
            i = int(np.searchsorted(uctx, ctx))
            if i >= len(uctx) or uctx[i] != ctx:
                continue  # unseen context at this order: keep the lower-order estimate
            lo = int(np.searchsorted(uniq, ctx * np.uint64(256)))
            hi = lo + int(distinct[i])
            seen = np.zeros(256)
            seen[(uniq[lo:hi] - ctx * np.uint64(256)).astype(np.int64)] = counts[lo:hi]
            total = float(totals[i])
            n1 = float(distinct[i])
            d = self.discounts[k]
            p = np.maximum(seen - d, 0.0) / total + (d * n1 / total) * p
        return p

    def bits_per_byte(self, data: bytes) -> float:
        """Average -log2 P(byte | previous bytes) over ``data`` (vectorised)."""
        np = self._np
        if not data:
            raise ValueError("empty data")
        x = np.frombuffer(data, dtype=np.uint8)
        xb = x.astype(np.uint64)
        p = np.full(len(x), 1.0 / 256.0)
        for k in range(self.order + 1):
            uniq, counts, uctx, totals, distinct = self._tables[k]
            ctx = self._contexts(x, k)
            i = np.searchsorted(uctx, ctx)
            i[i >= len(uctx)] = 0
            seen_ctx = uctx[i] == ctx
            key = ctx * np.uint64(256) + xb
            j = np.searchsorted(uniq, key)
            j[j >= len(uniq)] = 0
            cc = np.where(uniq[j] == key, counts[j], 0).astype(float)
            total = np.where(seen_ctx, totals[i], 1.0)
            n1 = np.where(seen_ctx, distinct[i], 0.0)
            d = self.discounts[k]
            pk = np.maximum(cc - d, 0.0) / total + (d * n1 / total) * p
            p = np.where(seen_ctx, pk, p)
        return float(-np.log2(p).sum() / len(x))


class NgramProvider:
    """Provider that continues the prompt with the n-gram model. Runs on CPU only."""

    name = "ngram"

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        *,
        order: int | None = None,
        max_output_bytes: int | None = None,
        max_corpus_bytes: int | None = None,
        seed: int | None = None,
    ) -> None:
        self.root = Path(root or os.getenv("AURIX_NGRAM_ROOT") or os.getenv("AURIX_WORKSPACE", "."))
        self.order = order if order is not None else _env_int("AURIX_NGRAM_ORDER", 12, 1, MAX_ORDER)
        self.max_output_bytes = min(
            HARD_MAX_OUTPUT_BYTES,
            max_output_bytes
            if max_output_bytes is not None
            else _env_int("AURIX_NGRAM_MAX_BYTES", 400, 1, HARD_MAX_OUTPUT_BYTES),
        )
        self.max_corpus_bytes = (
            max_corpus_bytes
            if max_corpus_bytes is not None
            else _env_int("AURIX_NGRAM_MAX_CORPUS_BYTES", 3_000_000, 1_000, 50_000_000)
        )
        self.seed = seed  # None -> greedy and fully deterministic
        self._model: NgramModel | None = None

    def _ensure_model(self) -> NgramModel:
        if self._model is None:
            corpus = collect_corpus(self.root, max_total_bytes=self.max_corpus_bytes)
            if not corpus:
                raise RuntimeError("ngram provider found no readable source files to learn from")
            self._model = NgramModel(corpus, order=self.order)
        return self._model

    def generate(self, prompt: str, *, system: str = "") -> str:
        """Continue ``prompt`` as code. ``system`` is ignored (this is not an instruct model)."""
        model = self._ensure_model()
        np = model._np
        rng = np.random.default_rng(self.seed) if self.seed is not None else None
        history = prompt.encode("utf-8")
        out = bytearray()
        while len(out) < self.max_output_bytes:
            dist = model.next_distribution(bytes(history[-model.order :]))
            nxt = int(dist.argmax()) if rng is None else int(rng.choice(256, p=dist / dist.sum()))
            if nxt == 0:
                break  # corpus file separator: the learned file ended here
            out.append(nxt)
            history = history + bytes([nxt])
            if out.endswith(b"\n\n\n"):
                break
        return bytes(out).decode("utf-8", errors="ignore")


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(low, min(high, value))
