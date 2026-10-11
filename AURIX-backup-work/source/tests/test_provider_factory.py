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


import pytest as _pytest_provider


@_pytest_provider.mark.parametrize("url", [
    "http://localhost:1234/v1", "http://127.0.0.1:8000/v1", "http://192.168.1.20:8080/v1",
    "http://llm.local/v1", "https://api.example.com/v1",
])
def test_api_key_is_allowed_over_https_or_local_http(url):
    from aurix.providers.openai_compatible import OpenAICompatibleProvider

    assert OpenAICompatibleProvider(base_url=url, api_key="secret").base_url == url


@_pytest_provider.mark.parametrize("url", ["http://api.example.com/v1", "http://8.8.8.8/v1"])
def test_api_key_over_plaintext_http_to_a_public_host_is_refused(url):
    from aurix.providers.openai_compatible import OpenAICompatibleProvider

    with _pytest_provider.raises(ValueError, match="plaintext HTTP"):
        OpenAICompatibleProvider(base_url=url, api_key="secret")


def test_plaintext_http_without_a_key_is_still_allowed():
    from aurix.providers.openai_compatible import OpenAICompatibleProvider

    assert OpenAICompatibleProvider(base_url="http://api.example.com/v1", api_key="").api_key == ""
