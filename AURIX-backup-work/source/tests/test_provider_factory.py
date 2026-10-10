import pytest

from aurix.providers.factory import create_provider
from aurix.providers.ollama import OllamaProvider
from aurix.providers.openai_compatible import OpenAICompatibleProvider


def test_default_provider_is_local_ollama(monkeypatch):
    monkeypatch.delenv("AURIX_PROVIDER", raising=False)
    monkeypatch.delenv("AURIX_BASE_URL", raising=False)
    monkeypatch.delenv("AURIX_MODEL", raising=False)
    provider = create_provider()
    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == "http://localhost:11434"
    assert provider.model == "qwen2.5-coder:7b"


def test_openai_compatible_is_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("AURIX_PROVIDER", "openai-compatible")
    monkeypatch.setenv("AURIX_BASE_URL", "http://localhost:1234/v1")
    provider = create_provider()
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "http://localhost:1234/v1"


def test_ollama_can_be_explicitly_configured(monkeypatch):
    monkeypatch.setenv("AURIX_PROVIDER", "ollama")
    monkeypatch.setenv("AURIX_BASE_URL", "http://localhost:11434")
    assert isinstance(create_provider(), OllamaProvider)


def test_unknown_provider_fails_closed(monkeypatch):
    monkeypatch.setenv("AURIX_PROVIDER", "magic")
    with pytest.raises(ValueError, match="Unknown AURIX_PROVIDER"):
        create_provider()
