import json

import pytest

from aurix import collaboration


class FakeProvider:
    def __init__(self, name):
        self.name = name

    def generate(self, prompt, *, system=""):
        return f"answer from {self.name}: {prompt[-80:]}"


def test_no_peers_is_safe_and_explicit(monkeypatch):
    monkeypatch.setenv("AURIX_PEER_PROVIDERS", "[]")
    result = collaboration.consult_other_ais("review this")
    assert result["status"] == "not_configured"
    assert result["consultations"] == []


def test_consults_configured_peers_in_parallel_and_preserves_identity(monkeypatch):
    monkeypatch.setenv("AURIX_PEER_PROVIDERS", json.dumps([
        {"name": "peer-a", "provider": "ollama", "model": "m-a"},
        {"name": "peer-b", "provider": "openai-compatible", "base_url": "http://localhost:1234/v1", "model": "m-b"},
    ]))
    monkeypatch.setattr(collaboration, "_make_provider", lambda config: FakeProvider(config["name"]))
    result = collaboration.consult_other_ais("Analyze this bug", max_peers=2)
    assert result["status"] == "completed"
    assert result["successful"] == 2
    assert [r["peer"] for r in result["consultations"]] == ["peer-a", "peer-b"]
    assert all(r["status"] == "ok" for r in result["consultations"])


def test_rejects_bad_config_and_duplicate_names(monkeypatch):
    monkeypatch.setenv("AURIX_PEER_PROVIDERS", "not-json")
    with pytest.raises(ValueError, match="JSON array"):
        collaboration.consult_other_ais("task")
    monkeypatch.setenv("AURIX_PEER_PROVIDERS", json.dumps([
        {"name": "same", "provider": "ollama"}, {"name": "same", "provider": "ollama"}
    ]))
    with pytest.raises(ValueError, match="Duplicate"):
        collaboration.consult_other_ais("task")


def test_limits_peer_count_and_task_size(monkeypatch):
    monkeypatch.setenv("AURIX_PEER_PROVIDERS", "[]")
    with pytest.raises(ValueError, match="max_peers"):
        collaboration.consult_other_ais("task", max_peers=5)
    with pytest.raises(ValueError, match="12000"):
        collaboration.consult_other_ais("x" * 12001)


def test_openai_compatible_peer_must_have_explicit_endpoint(monkeypatch):
    monkeypatch.setenv("AURIX_PEER_PROVIDERS", json.dumps([
        {"name": "peer", "provider": "openai-compatible", "model": "m"}
    ]))
    with pytest.raises(ValueError, match="explicitly set base_url"):
        collaboration.consult_other_ais("task")
