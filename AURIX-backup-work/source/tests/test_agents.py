import pytest

from aurix.agents import AgentManager


class FakeProvider:
    def __init__(self, output="ok"):
        self.output = output
        self.calls = []

    def generate(self, prompt, *, system=""):
        self.calls.append((prompt, system))
        return self.output


def test_agent_registry_persists_and_lists(tmp_path):
    path = tmp_path / ".aurix" / "agents.db"
    manager = AgentManager(path)
    created = manager.create("sec_review", "security", "Threat-model APIs")
    assert created["name"] == "sec_review"
    assert AgentManager(path).get("sec_review")["role"] == "security"
    assert AgentManager(path).list()[0]["description"] == "Threat-model APIs"


def test_agent_registry_rejects_invalid_and_duplicate_profiles(tmp_path):
    manager = AgentManager(tmp_path / "agents.db")
    with pytest.raises(ValueError):
        manager.create("bad name", "reviewer")
    with pytest.raises(ValueError):
        manager.create("not_allowed", "superuser")
    manager.create("review", "reviewer")
    with pytest.raises(ValueError, match="already exists"):
        manager.create("review", "reviewer")


def test_agent_run_uses_role_and_bounded_task(tmp_path):
    manager = AgentManager(tmp_path / "agents.db")
    manager.create("test_agent", "tester", "Regression testing")
    provider = FakeProvider("test plan")
    result = manager.run("test_agent", "Write a test plan", lambda: provider)
    assert result["status"] == "completed"
    assert result["output"] == "test plan"
    assert "Regression testing" in provider.calls[0][0]
    assert "failure cases" in provider.calls[0][1]
    with pytest.raises(ValueError):
        manager.run("test_agent", "", lambda: provider)


def test_team_creates_specialists_and_synthesizes(tmp_path):
    manager = AgentManager(tmp_path / "agents.db")
    providers = []

    def factory():
        provider = FakeProvider(f"answer-{len(providers)}")
        providers.append(provider)
        return provider

    result = manager.create_team("Design a resilient cache", factory)
    assert result["status"] == "completed"
    assert result["successful_agents"] == 3
    assert {agent["role"] for agent in result["agents_created"]} == {"architect", "researcher", "reviewer"}
    assert len(manager.list()) == 0  # task-scoped team profiles are cleaned up
    assert result["synthesis"] == "answer-3"


def test_team_reports_partial_failures(tmp_path):
    manager = AgentManager(tmp_path / "agents.db")
    calls = 0

    class FailingProvider:
        def generate(self, prompt, *, system=""):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("simulated")
            return "ok"

    result = manager.create_team("Review an API", lambda: FailingProvider())
    assert result["status"] == "completed"
    assert result["successful_agents"] == 2
    assert any(row["status"] == "error" for row in result["specialist_results"])


def test_team_runs_specialists_in_parallel_and_cleans_temporary_profiles(tmp_path):
    import threading
    import time

    manager = AgentManager(tmp_path / "agents.db")
    lock = threading.Lock()
    active = 0
    peak = 0

    class ConcurrentProvider:
        def generate(self, prompt, *, system=""):
            nonlocal active, peak
            if prompt.startswith("Specialist profile:"):
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.04)
                with lock:
                    active -= 1
                return "specialist contribution"
            return "synthesized result"

    result = manager.create_team("Design a safe task queue", lambda: ConcurrentProvider(), max_workers=3)
    assert result["status"] == "completed"
    assert result["execution_mode"] == "parallel"
    assert result["max_workers"] == 3
    assert peak > 1
    assert manager.list() == []


def test_team_sequential_mode_and_custom_worker_bound(tmp_path):
    manager = AgentManager(tmp_path / "agents.db")
    result = manager.create_team("Review the architecture", lambda: FakeProvider("ok"),
                                 parallel=False, max_workers=99)
    assert result["status"] == "completed"
    assert result["execution_mode"] == "sequential"
    assert result["max_workers"] == 1
    assert manager.list() == []


def test_agent_tool_protocol_executes_only_role_allowed_read_only_tools(tmp_path):
    import json

    class ToolCallingProvider:
        def __init__(self, outputs):
            self.outputs = iter(outputs)
            self.calls = []

        def generate(self, prompt, *, system=""):
            self.calls.append((prompt, system))
            return next(self.outputs)

    (tmp_path / "README.md").write_text("AURIX safe workspace", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=do-not-read", encoding="utf-8")
    provider = ToolCallingProvider([
        json.dumps({"tool_calls": [{"name": "search_workspace", "arguments": {"query": "AURIX", "limit": 5}}]}),
        "The README mentions AURIX. No secrets were read.",
    ])
    manager = AgentManager(tmp_path / ".aurix" / "agents.db")
    manager.create("research_agent", "researcher", "Inspect local repository evidence")
    result = manager.run("research_agent", "Find project references", lambda: provider, workspace=tmp_path)
    assert result["status"] == "completed"
    assert result["tool_calls"] == 1
    assert result["tool_results"][0]["status"] == "completed"
    assert "search_workspace" in result["tools_available"]
    assert "read_file" not in result["tools_available"]
    assert len(provider.calls) == 2
    assert "do-not-read" not in provider.calls[1][0]


def test_agent_tool_permissions_reject_forbidden_tools(tmp_path):
    from aurix.agent_tools import AgentToolbox

    toolbox = AgentToolbox(tmp_path)
    with pytest.raises(PermissionError):
        toolbox.execute("researcher", "read_file", {"path": "README.md"})
    with pytest.raises(ValueError):
        toolbox.execute("coder", "list_files", {"path": ".", "limit": 100, "unexpected": True})


def test_agent_tool_request_parser_is_strict_and_bounded():
    import json
    from aurix.agent_tools import MAX_TOOL_CALLS, parse_tool_request

    assert parse_tool_request("ordinary answer") is None
    assert parse_tool_request(json.dumps({"tool_calls": [{"name": "list_files", "arguments": {}}]})) == [
        {"name": "list_files", "arguments": {}}
    ]
    too_many = {"tool_calls": [{"name": "list_files", "arguments": {}} for _ in range(MAX_TOOL_CALLS + 1)]}
    assert parse_tool_request(json.dumps(too_many)) is None


def test_agent_read_tool_blocks_internal_state_and_git_metadata(tmp_path):
    from aurix.agent_tools import AgentToolbox

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("remote secret", encoding="utf-8")
    (tmp_path / ".aurix").mkdir()
    (tmp_path / ".aurix" / "state.txt").write_text("private internal state", encoding="utf-8")
    toolbox = AgentToolbox(tmp_path)
    with pytest.raises(PermissionError):
        toolbox.execute("coder", "read_file", {"path": ".git/config"})
    with pytest.raises(PermissionError):
        toolbox.execute("coder", "read_file", {"path": ".aurix/state.txt"})
