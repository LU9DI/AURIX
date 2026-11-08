import os

import httpx


def _output_limit() -> int:
    try:
        return int(os.getenv("AURIX_MAX_OUTPUT_TOKENS", "2048"))
    except ValueError:
        return 2048


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class OllamaProvider:
    """Minimal adapter for Ollama's local /api/chat endpoint."""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self.model = model or os.getenv("AURIX_MODEL", "qwen2.5-coder:7b")
        self.base_url = (base_url or os.getenv("AURIX_BASE_URL", "http://localhost:11434")).rstrip(
            "/"
        )
        self.temperature = _float_env("AURIX_TEMPERATURE", 0.0)
        self.seed = _int_env("AURIX_SEED", 0)

    def generation_settings(self) -> dict[str, object]:
        """Expose determinism settings for reports without storing prompts."""

        return {
            "temperature": self.temperature,
            "seed": self.seed,
            "max_output_tokens": max(1, min(_output_limit(), 32768)),
            "supported": {"temperature": True, "seed": True},
        }

    def generate(self, prompt: str, *, system: str = "") -> str:
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            response = client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": max(1, min(_output_limit(), 32768)),
                        "temperature": self.temperature,
                        "seed": self.seed,
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
        try:
            return str(payload["message"]["content"])
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Unexpected response from local model server") from exc
