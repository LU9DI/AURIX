"""Bounded lexical and optional embedding-assisted memory retrieval."""
from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any, Protocol

from aurix.memory.base import MemoryStore

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class TextEmbedder(Protocol):
    """Small adapter contract for any local or remote text embedding engine."""

    def embed(self, text: str) -> Sequence[float]: ...


def _tokens(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(value) if len(token) > 1]


def _vector(value: Sequence[float], *, label: str) -> tuple[float, ...]:
    try:
        vector = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} embedding must be a numeric sequence") from exc
    if not vector or any(not math.isfinite(item) for item in vector):
        raise ValueError(f"{label} embedding must be non-empty and finite")
    if not any(item != 0 for item in vector):
        raise ValueError(f"{label} embedding must not be a zero vector")
    return vector


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    similarity = sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
    # Map cosine [-1, 1] to [0, 1] so the hybrid score is easy to interpret.
    return max(0.0, min(1.0, (similarity + 1.0) / 2.0))


def retrieve_memories(
    store: MemoryStore,
    query: str,
    *,
    scope: str,
    limit: int = 10,
    candidate_limit: int = 100,
    max_content_chars: int = 4_000,
    embedder: TextEmbedder | None = None,
    lexical_weight: float = 0.65,
) -> list[dict[str, Any]]:
    """Rank recent scoped records using lexical overlap, optionally blended with embeddings.

    With no embedder, ranking is deterministic and lexical. When an embedder is
    supplied, all candidates are scored semantically too, allowing relevant
    records with no shared tokens to be returned. The adapter is injected by
    the caller so AURIX does not require a specific embedding vendor/model.

    A scope is a query filter, not an authorization boundary. Candidate search
    is bounded to recent records returned by the backend.
    """
    query_tokens = list(dict.fromkeys(_tokens(query)))
    if not query_tokens:
        raise ValueError("memory query must contain at least one token of 2+ characters")
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("memory scope must not be empty")
    limit = max(1, min(int(limit), 50))
    candidate_limit = max(limit, min(int(candidate_limit), 500))
    max_content_chars = max(100, min(int(max_content_chars), 20_000))
    lexical_weight = float(lexical_weight)
    if not math.isfinite(lexical_weight) or not 0.0 <= lexical_weight <= 1.0:
        raise ValueError("lexical_weight must be between 0 and 1")
    if embedder is not None and (lexical_weight <= 0.0 or lexical_weight >= 1.0):
        raise ValueError("hybrid retrieval requires lexical_weight strictly between 0 and 1")

    candidates = store.search("", scope=scope, limit=candidate_limit)
    query_set = set(query_tokens)
    query_phrase = " ".join(query_tokens)
    query_vector = _vector(embedder.embed(query), label="query") if embedder else None
    ranked: list[tuple[float, int, dict[str, Any]]] = []

    for record in candidates:
        content = str(record.get("content", ""))
        content_tokens = _tokens(content)
        content_set = set(content_tokens)
        matched = [token for token in query_tokens if token in content_set]
        lexical_score = len(set(matched)) / len(query_set)
        normalized_content = " ".join(content_tokens)
        if matched and query_phrase in normalized_content:
            lexical_score += 0.25
        lexical_score = min(1.25, lexical_score)
        if embedder is None and not matched:
            continue

        item = dict(record)
        item["content"] = content[:max_content_chars]
        if len(content) > max_content_chars:
            item["content_truncated"] = True
        item["matched_terms"] = matched
        item["lexical_score"] = round(lexical_score, 4)
        if embedder is None:
            score = lexical_score
            item["retrieval_mode"] = "lexical"
        else:
            assert query_vector is not None
            doc_vector = _vector(embedder.embed(content), label="document")
            semantic_score = _cosine(query_vector, doc_vector)
            normalized_lexical_score = min(1.0, lexical_score / 1.25)
            score = lexical_weight * normalized_lexical_score + (1.0 - lexical_weight) * semantic_score
            item["semantic_score"] = round(semantic_score, 4)
            item["retrieval_mode"] = "hybrid"

        try:
            recency = int(record.get("id", 0))
        except (TypeError, ValueError):
            recency = 0
        item["relevance_score"] = round(score, 4)
        ranked.append((score, recency, item))

    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return [entry[2] for entry in ranked[:limit]]


def evaluate_retrieval(
    results: Sequence[dict[str, Any]], relevant_ids: set[int | str], *, k: int = 5
) -> dict[str, float | int]:
    """Calculate lightweight retrieval metrics against manually labeled relevant IDs."""
    if k < 1:
        raise ValueError("k must be at least 1")
    top = list(results[:k])
    found = [index for index, record in enumerate(top, start=1) if record.get("id") in relevant_ids]
    relevant_found = sum(1 for record in top if record.get("id") in relevant_ids)
    precision = relevant_found / k
    recall = relevant_found / len(relevant_ids) if relevant_ids else 0.0
    reciprocal_rank = 1.0 / found[0] if found else 0.0
    return {
        f"precision_at_{k}": round(precision, 4),
        f"recall_at_{k}": round(recall, 4),
        "reciprocal_rank": round(reciprocal_rank, 4),
        "relevant_found": relevant_found,
        "relevant_total": len(relevant_ids),
    }
