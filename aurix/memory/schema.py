"""Validation helpers for evidence-aware memory records."""

from __future__ import annotations

from typing import Any

MEMORY_KINDS = ("fact", "hypothesis", "decision", "test_result", "observation")


def validate_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Copy metadata and validate reserved evidence fields without restricting custom keys."""
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ValueError("memory metadata must be a dictionary")
    normalized = dict(metadata)
    kind = normalized.get("kind")
    if kind is not None and kind not in MEMORY_KINDS:
        raise ValueError(f"memory kind must be one of: {', '.join(MEMORY_KINDS)}")
    confidence = normalized.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("memory confidence must be a number between 0 and 1")
        if not 0 <= confidence <= 1:
            raise ValueError("memory confidence must be between 0 and 1")
        normalized["confidence"] = float(confidence)
    return normalized
