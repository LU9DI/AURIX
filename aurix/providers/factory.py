"""Central provider selection; the core stays independent of inference vendors."""

from __future__ import annotations

import os

from aurix.providers.base import Provider
from aurix.providers.ngram import NgramProvider
from aurix.providers.ollama import OllamaProvider
from aurix.providers.openai_compatible import OpenAICompatibleProvider


def create_provider(name: str | None = None) -> Provider:
    provider = (name or os.getenv("AURIX_PROVIDER", "ollama")).strip().lower()
    if provider == "ollama":
        return OllamaProvider()
    if provider in {"openai-compatible", "openai_compatible", "compatible"}:
        return OpenAICompatibleProvider()
    if provider in {"ngram", "cpu-ngram"}:
        return NgramProvider()
    raise ValueError(
        f"Unknown AURIX_PROVIDER={provider!r}. "
        "Supported providers: ollama, openai-compatible, ngram."
    )
