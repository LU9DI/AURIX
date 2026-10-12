import json

from aurix.orchestrator import Orchestrator
from aurix.runtime import ContextBudget, ResponseCache


class CountingProvider:
    model = "fake-model"
    base_url = "fake://local"

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, *, system=""):
        self.calls += 1
        return json.dumps({"status": "final", "message": "done"})


def test_context_budget_compacts_long_prompt_and_keeps_edges():
    budget = ContextBudget(max_input_tokens=512, reserve_tokens=64)
    prompt = (
        "TASK: preserve this objective\n"
        + ("middle context " * 3000)
        + "LATEST EVIDENCE: keep this"
    )
    fitted, compacted = budget.fit(prompt)
    assert compacted
    assert "TASK: preserve this objective" in fitted
    assert "LATEST EVIDENCE: keep this" in fitted
    from aurix.telemetry import estimate_tokens

    assert estimate_tokens(fitted) <= budget.usable_tokens


def test_response_cache_reuses_only_terminal_response_for_same_workspace(tmp_path):
    provider = CountingProvider()
    cache = ResponseCache(max_entries=4, ttl_seconds=60)
    first = Orchestrator(provider, workspace=tmp_path, response_cache=cache).run("same task")
    second = Orchestrator(provider, workspace=tmp_path, response_cache=cache).run("same task")
    assert first.message == second.message == "done"
    assert provider.calls == 1
    assert second.trace[0]["cache_hit"] is True


def test_workspace_change_invalidates_response_cache(tmp_path):
    provider = CountingProvider()
    cache = ResponseCache(max_entries=4, ttl_seconds=60)
    Orchestrator(provider, workspace=tmp_path, response_cache=cache).run("same task")
    (tmp_path / "changed.py").write_text("x = 1\n", encoding="utf-8")
    Orchestrator(provider, workspace=tmp_path, response_cache=cache).run("same task")
    assert provider.calls == 2


def test_cache_never_returns_tool_calls_as_cached_entries():
    cache = ResponseCache(max_entries=2, ttl_seconds=60)
    cache.put("key", json.dumps({"status": "final", "message": "terminal"}))
    assert json.loads(cache.get("key"))["status"] == "final"
