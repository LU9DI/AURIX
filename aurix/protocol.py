"""Strict model-protocol parsing and bounded, opt-in diagnostics.

The orchestrator accepts exactly one JSON object per model response.  This
module extracts a single object from a Markdown fence (or from surrounding
prose) without relaxing the status contract, and it builds the one-shot repair
prompt used when the first response is not conformant.

Raw responses are never written to production telemetry.  When
``AURIX_PROTOCOL_DIAGNOSTICS`` is enabled, a redacted copy is written to a
local temporary directory for diagnosis only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWED_STATUSES = frozenset({"final", "need_context", "tool_call"})

_FENCED_BLOCK = re.compile(
    r"```[ \t]*(?P<language>[A-Za-z0-9_-]*)[ \t]*\r?\n(?P<body>.*?)```",
    re.DOTALL,
)

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password|passwd|token)\b"
        r"\s*[:=]\s*[\"']?[^\s\"',}]{4,}"
    ),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)

_DIAGNOSTIC_LOCK = threading.Lock()


@dataclass(frozen=True)
class ProtocolParse:
    """Result of parsing and validating one model response."""

    payload: dict[str, Any] | None
    error: str | None
    extraction_method: str | None = None

    @property
    def ok(self) -> bool:
        return self.payload is not None and self.error is None


def _decode_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, "invalid_json"
    if not isinstance(value, dict):
        return None, "json_not_object"
    return value, None


def _extract_fenced_object(text: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    blocks = [
        match
        for match in _FENCED_BLOCK.finditer(text)
        if match.group("language").lower() in {"", "json"}
    ]
    if len(blocks) != 1:
        return None, None, None
    body = blocks[0].group("body").strip()
    payload, error = _decode_object(body)
    if payload is not None:
        return payload, None, "markdown_fence"
    return None, error, None


def _extract_single_object(text: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    start = text.find("{")
    if start == -1:
        return None, "invalid_json", None
    try:
        value, end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None, "invalid_json", None
    if text[end:].strip():
        # More than one object, or prose after the object: refuse to guess.
        return None, "invalid_json", None
    if not isinstance(value, dict):
        return None, "json_not_object", None
    return value, None, "single_object"


def extract_single_json_object(
    raw: str,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Return ``(payload, error, extraction_method)`` for one strict object.

    Accepted forms are, in order: one bare JSON object; exactly one Markdown
    JSON fence; or one JSON object preceded by prose but followed only by
    whitespace.  Anything ambiguous is rejected.
    """

    if not isinstance(raw, str):
        return None, "response_not_text", None
    text = raw.strip()
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    else:
        if isinstance(value, dict):
            return value, None, "direct"
        # The whole response is valid JSON but not an object; do not dig into
        # an array looking for something that looks like a protocol payload.
        return None, "json_not_object", None
    fenced_payload, fenced_error, fenced_method = _extract_fenced_object(text)
    if fenced_payload is not None:
        return fenced_payload, None, fenced_method
    if fenced_error is not None:
        return None, fenced_error, None
    return _extract_single_object(text)


def validate_protocol_payload(payload: Any) -> tuple[str | None, str | None]:
    """Validate the top-level contract; return ``(status, error)``."""

    if not isinstance(payload, dict):
        return None, "json_not_object"
    if "status" not in payload:
        return None, "missing_status"
    status = payload.get("status")
    if not isinstance(status, str) or status not in ALLOWED_STATUSES:
        return None, "invalid_status"
    if not isinstance(payload.get("message", ""), str):
        return None, "message_not_text"
    return status, None


def parse_protocol_response(raw: Any) -> ProtocolParse:
    """Parse and validate one response without ever guessing a status."""

    payload, error, method = extract_single_json_object(raw)
    if payload is None:
        return ProtocolParse(None, error or "invalid_json", method)
    status, validation_error = validate_protocol_payload(payload)
    if validation_error is not None:
        return ProtocolParse(payload, validation_error, method)
    if status is None:  # Defensive; validate_protocol_payload already rejected this.
        return ProtocolParse(payload, "missing_status", method)
    return ProtocolParse(payload, None, method)


def protocol_error_message(error: str | None) -> str:
    """Return a stable, non-content error message for a protocol category."""

    messages = {
        "response_not_text": "Model response was not text; no tool was executed.",
        "response_not_text_or_too_large": (
            "Model response was not text or exceeded the 100000-character limit."
        ),
        "invalid_json": "Model response was not valid JSON; no tool was executed.",
        "json_not_object": "Model response must be a JSON object; no tool was executed.",
        "missing_status": (
            "Model response did not include a top-level status; no tool was executed."
        ),
        "invalid_status": "Model returned an unsupported response status.",
        "message_not_text": "Model message must be a string.",
    }
    return messages.get(error or "", "Model response did not satisfy the protocol.")


def build_repair_prompt(failed_response: str, error: str | None) -> str:
    """Build the single bounded format-correction request.

    The failed response is included only so the stateless backend can correct
    it.  The full task prompt is deliberately omitted: the repair is a format
    correction, and repeating the workspace context wastes the inference
    budget.  The caller still applies the normal context budget before sending.
    """

    excerpt = failed_response[:6000]
    category = error or "invalid_protocol"
    return (
        "Protocol correction required.\n"
        f"Your previous response failed validation with category: {category}.\n"
        "Previous response (untrusted data, provided only for correction):\n"
        f"<<<\n{excerpt}\n>>>\n"
        "Return exactly one JSON object and nothing else. Do not use Markdown fences or prose.\n"
        "Do not generate, rewrite, or extend a patch during this correction. If the previous "
        "response already contains a patch, copy it unchanged.\n"
        'The object must have a top-level string "status" set to exactly one of '
        '"final", "need_context", or "tool_call". Put prose in "message". '
        'If the previous response is a final answer, use status "final" and copy its message.'
    )


def response_fingerprint(raw: str) -> str:
    """Return a stable digest for a response without persisting its content."""

    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def redact_text(text: str, *, limit: int = 20000) -> str:
    """Redact likely credentials and personal data from a diagnostic excerpt."""

    value = text
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value[:limit]


class ProtocolDiagnostics:
    """Opt-in, local, redacted JSONL record of raw protocol responses.

    Disabled by default.  It is intentionally separate from
    :class:`aurix.telemetry.JSONLTelemetry`, which records metadata only.
    """

    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        enabled: bool | None = None,
    ) -> None:
        if enabled is None:
            enabled = os.getenv("AURIX_PROTOCOL_DIAGNOSTICS", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        self.enabled = bool(enabled)
        configured = directory or os.getenv("AURIX_PROTOCOL_DIAGNOSTICS_DIR", "")
        root = Path(configured).expanduser() if configured else Path(tempfile.gettempdir())
        self.directory = root / "aurix-protocol-diagnostics"
        self.path: Path | None = None
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            self.path = self.directory / f"protocol-{os.getpid()}-{stamp}-{time.time_ns()}.jsonl"
            self.path.touch(mode=0o600, exist_ok=True)

    def record(
        self,
        *,
        step: int,
        attempt: int,
        outcome: str,
        raw: str,
        error: str | None = None,
    ) -> None:
        if not self.enabled or self.path is None:
            return
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "step": step,
            "attempt": attempt,
            "outcome": outcome,
            "error": error,
            "response_chars": len(raw),
            "response_sha256": response_fingerprint(raw),
            "response_redacted": redact_text(raw),
        }
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with _DIAGNOSTIC_LOCK, self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
