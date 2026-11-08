from typing import ClassVar

from aurix.providers import ollama


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    instances: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        self.posts = []
        FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json):
        self.posts.append((url, json))
        return FakeResponse({"message": {"content": "ok"}})


def _provider(monkeypatch):
    monkeypatch.setattr(ollama.httpx, "Client", FakeClient)
    monkeypatch.delenv("AURIX_TEMPERATURE", raising=False)
    monkeypatch.delenv("AURIX_SEED", raising=False)
    FakeClient.instances = []
    return ollama.OllamaProvider(model="test-model", base_url="http://localhost:11434")


def test_ollama_requests_temperature_zero_and_fixed_seed(monkeypatch):
    provider = _provider(monkeypatch)

    assert provider.generate("hello", system="system") == "ok"

    request = FakeClient.instances[0].posts[0][1]
    assert request["options"]["temperature"] == 0.0
    assert request["options"]["seed"] == 0
    assert request["options"]["num_predict"] >= 1
    assert provider.generation_settings() == {
        "temperature": 0.0,
        "seed": 0,
        "max_output_tokens": 2048,
        "supported": {"temperature": True, "seed": True},
    }


def test_ollama_sampling_settings_can_be_overridden(monkeypatch):
    monkeypatch.setattr(ollama.httpx, "Client", FakeClient)
    monkeypatch.setenv("AURIX_TEMPERATURE", "0.2")
    monkeypatch.setenv("AURIX_SEED", "42")
    FakeClient.instances = []
    provider = ollama.OllamaProvider(model="test-model", base_url="http://localhost:11434")

    settings = provider.generation_settings()

    assert settings["temperature"] == 0.2
    assert settings["seed"] == 42
