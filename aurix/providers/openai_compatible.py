"""Adapter for servers exposing the OpenAI Chat Completions API.

Works with compatible local servers (for example llama.cpp server, LM Studio,
 vLLM) and hosted endpoints. The provider does not assume any vendor-specific
features beyond /v1/chat/completions.
"""

from __future__ import annotations

import os

import httpx


def _output_limit() -> int:
    try:
        return int(os.getenv("AURIX_MAX_OUTPUT_TOKENS", "2048"))
    except ValueError:
        return 2048


class OpenAICompatibleProvider:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model or os.getenv("AURIX_MODEL", "local-model")
        self.base_url = (
            base_url or os.getenv("AURIX_BASE_URL", "http://localhost:1234/v1")
        ).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("AURIX_API_KEY", "")
        self.timeout = max(1.0, float(timeout))

    def generate(self, prompt: str, *, system: str = "") -> str:
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=5.0)) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "max_tokens": max(1, min(_output_limit(), 32768)),
                    },
                )
                response.raise_for_status()
                payload = response.json()
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("Unexpected response from OpenAI-compatible model server") from exc
