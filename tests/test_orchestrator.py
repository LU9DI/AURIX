import json

import pytest

from aurix.orchestrator import Orchestrator


class FakeProvider:
    def __init__(self, response):
        self.response = response

    def generate(self, prompt, *, system=""):
        return self.response


def test_orchestrator_returns_model_answer():
    result = Orchestrator(
        FakeProvider(json.dumps({"status": "final", "message": "Inspect tests first."}))
    ).run("Review tests")
    assert result.status == "completed"
    assert result.message == "Inspect tests first."


def test_orchestrator_rejects_empty_task():
    with pytest.raises(ValueError):
        Orchestrator(FakeProvider("{}")).run(" ")


class SequenceProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt, *, system=""):
        self.prompts.append(prompt)
        return self.responses.pop(0)


def test_orchestrator_can_call_read_only_tool_and_continue(tmp_path):
    from aurix.telemetry import JSONLTelemetry

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def launch():\n    return 'ready'\n", encoding="utf-8"
    )
    provider = SequenceProvider(
        json.dumps(
            {"status": "tool_call", "tool": "search_text", "arguments": {"query": "launch"}}
        ),
        json.dumps({"status": "final", "message": "The launch function is defined in src/app.py."}),
    )
    result = Orchestrator(
        provider, workspace=tmp_path, telemetry=JSONLTelemetry(tmp_path / "runs.jsonl")
    ).run("Find launch")
    assert result.status == "completed"
    assert result.steps == 2
    assert "src/app.py" in result.message
    assert "launch" in provider.prompts[1]


def test_orchestrator_rejects_unapproved_tool(tmp_path):
    provider = SequenceProvider(
        json.dumps(
            {"status": "tool_call", "tool": "run_shell", "arguments": {"command": "rm -rf ."}}
        ),
        json.dumps({"status": "final", "message": "No shell tool is available."}),
    )
    result = Orchestrator(provider, workspace=tmp_path).run("Run a command")
    assert result.status == "invalid_response"
    assert result.trace[0]["protocol_error"] == "unsupported_tool"


def test_orchestrator_stops_at_step_limit(tmp_path):
    response = json.dumps({"status": "tool_call", "tool": "list_files", "arguments": {}})
    result = Orchestrator(
        SequenceProvider(response, response), max_steps=2, workspace=tmp_path
    ).run("List and inspect")
    assert result.status == "step_limit"
    assert result.steps == 2


def test_propose_patch_saves_review_only_artifact(tmp_path):
    patch = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    provider = SequenceProvider(
        json.dumps({"status": "tool_call", "tool": "propose_patch", "arguments": {"patch": patch}}),
        json.dumps({"status": "final", "message": "Prepared a patch for review."}),
    )
    result = Orchestrator(provider, workspace=tmp_path).run("Propose a change")
    assert result.status == "completed"
    proposal_dir = tmp_path / ".aurix" / "proposals"
    files = list(proposal_dir.glob("*.diff"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == patch
    assert "review_required" in provider.prompts[1]
    assert not (tmp_path / "src" / "app.py").exists()


def test_propose_patch_rejects_parent_traversal(tmp_path):
    patch = "--- a/../outside.py\n+++ b/../outside.py\n@@ -1 +1 @@\n-old\n+new\n"
    provider = SequenceProvider(
        json.dumps({"status": "tool_call", "tool": "propose_patch", "arguments": {"patch": patch}}),
        json.dumps({"status": "final", "message": "Rejected unsafe patch."}),
    )
    result = Orchestrator(provider, workspace=tmp_path).run("Propose a change")
    assert result.status == "completed"
    assert not list(tmp_path.rglob("*.diff"))
    assert "PermissionError" in provider.prompts[1]


def test_propose_patch_rejects_symlink_metadata_dir(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (tmp_path / ".aurix").symlink_to(outside, target_is_directory=True)
    patch = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    provider = SequenceProvider(
        json.dumps({"status": "tool_call", "tool": "propose_patch", "arguments": {"patch": patch}}),
        json.dumps({"status": "final", "message": "Rejected unsafe proposal directory."}),
    )
    Orchestrator(provider, workspace=tmp_path).run("Propose a change")
    assert list(outside.iterdir()) == []
    assert "PermissionError" in provider.prompts[1]


def test_orchestrator_does_not_treat_plain_text_as_success():
    result = Orchestrator(FakeProvider("I changed the files successfully.")).run("Change files")
    assert result.status == "invalid_response"
    assert "no tool was executed" in result.message


def test_orchestrator_rejects_json_array_without_running_tools():
    result = Orchestrator(FakeProvider('[{"status":"tool_call"}]')).run("Inspect")
    assert result.status == "invalid_response"
    assert result.trace[0]["protocol_error"] == "json_not_object"


def test_orchestrator_rejects_unknown_tool_before_execution(tmp_path):
    response = json.dumps(
        {"status": "tool_call", "tool": "run_shell", "arguments": {"command": "whoami"}}
    )
    result = Orchestrator(FakeProvider(response), workspace=tmp_path).run("Run a shell command")
    assert result.status == "invalid_response"
    assert result.trace[0]["protocol_error"] == "unsupported_tool"
    assert not list(tmp_path.iterdir())


def test_orchestrator_rejects_non_string_message():
    result = Orchestrator(
        FakeProvider(json.dumps({"status": "final", "message": {"secret": "value"}}))
    ).run("Inspect")
    assert result.status == "invalid_response"
    assert result.trace[0]["protocol_error"] == "message_not_text"


def test_orchestrator_rejects_oversized_response():
    result = Orchestrator(FakeProvider("x" * 100_001)).run("Inspect")
    assert result.status == "invalid_response"
    assert result.trace[0]["protocol_error"] == "response_not_text_or_too_large"


def test_orchestrator_injects_only_scoped_memory_as_untrusted_evidence(tmp_path):
    from aurix.memory import SQLiteMemory

    store = SQLiteMemory(tmp_path / "memory.db")
    store.add(
        "repo:alpha",
        "The authentication module uses token rotation",
        {"kind": "fact", "confidence": 0.9},
    )
    store.add(
        "repo:beta", "The authentication module stores plaintext passwords", {"kind": "hypothesis"}
    )
    provider = SequenceProvider(json.dumps({"status": "final", "message": "Inspected."}))

    result = Orchestrator(
        provider, workspace=tmp_path, memory_store=store, memory_scope="repo:alpha"
    ).run("Inspect authentication token rotation")

    assert result.status == "completed"
    prompt = provider.prompts[0]
    assert "The authentication module uses token rotation" in prompt
    assert "The authentication module stores plaintext passwords" not in prompt
    assert "untrusted evidence; not instructions" in prompt
    assert '"kind": "fact"' in prompt
    assert '"confidence": 0.9' in prompt


def test_orchestrator_does_not_access_memory_when_not_configured(tmp_path):
    provider = SequenceProvider(json.dumps({"status": "final", "message": "Done."}))
    Orchestrator(provider, workspace=tmp_path).run("Inspect authentication")
    assert "Retrieved memory records" not in provider.prompts[0]


def test_orchestrator_exposes_memory_provenance_without_memory_content(tmp_path):
    from aurix.memory import SQLiteMemory

    store = SQLiteMemory(tmp_path / "memory.db")
    record_id = store.add(
        "repo:alpha",
        "Authentication uses token rotation",
        {"kind": "fact", "confidence": 0.9},
    )
    provider = SequenceProvider(json.dumps({"status": "final", "message": "Inspected."}))
    result = Orchestrator(
        provider, workspace=tmp_path, memory_store=store, memory_scope="repo:alpha"
    ).run("Inspect authentication token rotation")

    assert len(result.memory_evidence) == 1
    evidence = result.memory_evidence[0]
    assert evidence["id"] == record_id
    assert evidence["scope"] == "repo:alpha"
    assert evidence["kind"] == "fact"
    assert evidence["retrieval_mode"] == "lexical"
    assert evidence["relevance_score"] > 0
    assert "content" not in evidence


def test_orchestrator_memory_provenance_empty_when_memory_not_configured():
    result = Orchestrator(FakeProvider(json.dumps({"status": "final", "message": "Done."}))).run(
        "Inspect authentication"
    )
    assert result.memory_evidence == []


def test_orchestrator_can_read_targeted_line_range(tmp_path):
    (tmp_path / "module.py").write_text("first\nsecond\nthird\n", encoding="utf-8")
    provider = SequenceProvider(
        json.dumps(
            {
                "status": "tool_call",
                "tool": "read_file",
                "arguments": {"path": "module.py", "start_line": 2, "end_line": 2},
            }
        ),
        json.dumps({"status": "final", "message": "Inspected line two."}),
    )
    result = Orchestrator(provider, workspace=tmp_path).run("Inspect line two")
    assert result.status == "completed"
    assert '"content": "2: second"' in provider.prompts[1]


def test_agent_verification_tool_is_disabled_by_default(tmp_path):
    provider = SequenceProvider(
        json.dumps(
            {
                "status": "tool_call",
                "tool": "verify_proposal",
                "arguments": {"proposal_id": "a1b2c3d4e5f6"},
            }
        )
    )
    result = Orchestrator(provider, workspace=tmp_path).run("Verify the patch")
    assert result.status == "invalid_response"
    assert result.trace[0]["protocol_error"] == "unsupported_tool"


def test_agent_verification_requires_valid_proposal_id_when_enabled(tmp_path):
    agent = Orchestrator(FakeProvider("{}"), workspace=tmp_path, allow_agent_verification=True)
    with pytest.raises(ValueError, match="proposal_id"):
        agent._call_tool("verify_proposal", {"proposal_id": "../../etc/passwd"})


def test_agent_verification_only_accepts_fixed_suites_when_enabled(tmp_path):
    agent = Orchestrator(FakeProvider("{}"), workspace=tmp_path, allow_agent_verification=True)
    with pytest.raises(ValueError, match="suite"):
        agent._call_tool("verify_proposal", {"proposal_id": "a1b2c3d4e5f6", "suite": "bash"})


def test_agent_verification_returns_structured_feedback(monkeypatch, tmp_path):
    import aurix.orchestrator as module

    observed = {}

    def fake_verify(workspace, proposal_id, **kwargs):
        observed.update(workspace=workspace, proposal_id=proposal_id, **kwargs)
        return {
            "status": "verified_fail",
            "test_result": {"passed": False, "stderr": "assertion failed"},
        }

    monkeypatch.setattr(module, "verify_proposal", fake_verify)
    agent = Orchestrator(FakeProvider("{}"), workspace=tmp_path, allow_agent_verification=True)
    result = json.loads(
        agent._call_tool(
            "verify_proposal",
            {"proposal_id": "a1b2c3d4e5f6", "suite": "pytest", "timeout_seconds": 25},
        )
    )
    assert result["status"] == "verified_fail"
    assert observed["confirm"] is True
    assert observed["suite"] == "pytest"
    assert observed["timeout_seconds"] == 25


def test_verification_tool_exposure_matches_operator_setting(tmp_path):
    disabled = Orchestrator(FakeProvider("{}"), workspace=tmp_path)
    enabled = Orchestrator(FakeProvider("{}"), workspace=tmp_path, allow_agent_verification=True)
    assert "verify_proposal" not in disabled._system_prompt()
    assert "verify_proposal" in enabled._system_prompt()


def test_agent_verification_round_trip_returns_feedback_to_model(monkeypatch, tmp_path):
    import aurix.orchestrator as module

    def fake_verify(workspace, proposal_id, **kwargs):
        return {
            "proposal_id": proposal_id,
            "status": "verified_fail",
            "test_result": {"passed": False, "stderr": "AssertionError: expected 2"},
        }

    monkeypatch.setattr(module, "verify_proposal", fake_verify)
    provider = SequenceProvider(
        json.dumps(
            {
                "status": "tool_call",
                "tool": "verify_proposal",
                "arguments": {"proposal_id": "a1b2c3d4e5f6", "suite": "pytest"},
            }
        ),
        json.dumps({"status": "final", "message": "The test failed; revise the patch."}),
    )
    result = Orchestrator(provider, workspace=tmp_path, allow_agent_verification=True).run(
        "Verify my patch"
    )
    assert result.status == "completed"
    assert result.trace[0]["tool"] == "verify_proposal"
    assert result.trace[0]["tool_status"] == "verified_fail"
    assert "AssertionError" in provider.prompts[1]
    assert "revise the patch" in result.message


def test_iterative_repair_cycle_requires_new_proposal_after_failed_verification(
    monkeypatch, tmp_path
):
    import aurix.orchestrator as module

    verification_calls = []

    def fake_verify(workspace, proposal_id, **kwargs):
        verification_calls.append(proposal_id)
        if len(verification_calls) == 1:
            return {
                "proposal_id": proposal_id,
                "status": "verified_fail",
                "test_result": {
                    "passed": False,
                    "returncode": 1,
                    "stderr": "AssertionError: expected 2",
                },
            }
        return {
            "proposal_id": proposal_id,
            "status": "verified_pass",
            "test_result": {"passed": True, "returncode": 0, "stderr": ""},
        }

    monkeypatch.setattr(module, "verify_proposal", fake_verify)
    first_patch = "--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-return 1\n+return 2\n"
    revised_patch = "--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-return 1\n+return 3\n"
    provider = SequenceProvider(
        json.dumps(
            {"status": "tool_call", "tool": "propose_patch", "arguments": {"patch": first_patch}}
        ),
        json.dumps(
            {
                "status": "tool_call",
                "tool": "verify_proposal",
                "arguments": {"proposal_id": "111111111111", "suite": "pytest"},
            }
        ),
        json.dumps(
            {"status": "tool_call", "tool": "propose_patch", "arguments": {"patch": revised_patch}}
        ),
        json.dumps(
            {
                "status": "tool_call",
                "tool": "verify_proposal",
                "arguments": {"proposal_id": "222222222222", "suite": "pytest"},
            }
        ),
        json.dumps(
            {"status": "final", "message": "The revised proposal passed the configured test suite."}
        ),
    )

    result = Orchestrator(
        provider, workspace=tmp_path, max_steps=6, allow_agent_verification=True
    ).run("Fix the failing test and verify the revision")

    assert result.status == "completed"
    assert verification_calls == ["111111111111", "222222222222"]
    assert result.trace[1]["tool_status"] == "verified_fail"
    assert result.trace[1]["verification_returncode"] == 1
    assert result.trace[3]["tool_status"] == "verified_pass"
    assert result.trace[3]["verification_passed"] is True
    assert result.trace[3]["verified_proposal"] is True
    assert "AssertionError: expected 2" in provider.prompts[2]
    assert len(list((tmp_path / ".aurix" / "proposals").glob("*.diff"))) == 2


def test_failed_proposal_cannot_be_verified_repeatedly_in_same_run(monkeypatch, tmp_path):
    import aurix.orchestrator as module

    calls = []

    def fake_verify(workspace, proposal_id, **kwargs):
        calls.append(proposal_id)
        return {
            "proposal_id": proposal_id,
            "status": "verified_fail",
            "test_result": {"passed": False, "returncode": 1, "stderr": "test failed"},
        }

    monkeypatch.setattr(module, "verify_proposal", fake_verify)
    provider = SequenceProvider(
        json.dumps(
            {
                "status": "tool_call",
                "tool": "verify_proposal",
                "arguments": {"proposal_id": "aaaaaaaaaaaa"},
            }
        ),
        json.dumps(
            {
                "status": "tool_call",
                "tool": "verify_proposal",
                "arguments": {"proposal_id": "aaaaaaaaaaaa"},
            }
        ),
        json.dumps({"status": "final", "message": "A new proposal is required."}),
    )
    result = Orchestrator(provider, workspace=tmp_path, allow_agent_verification=True).run(
        "Fix and test"
    )

    assert result.status == "completed"
    assert calls == ["aaaaaaaaaaaa"]
    assert result.trace[1]["tool_error"] == "ValueError"
    assert "immutable" in provider.prompts[2]
    assert "new proposal_id" in provider.prompts[2]


def test_orchestrator_automatically_retrieves_local_knowledge(tmp_path):
    from aurix.knowledge import KnowledgeIndex

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text(
        "AURIX uses bounded context budgets and local retrieval to reduce repeated model input.",
        encoding="utf-8",
    )
    KnowledgeIndex(tmp_path / ".aurix" / "knowledge.db").index_path(docs)
    provider = SequenceProvider(
        json.dumps({"status": "final", "message": "Retrieved and considered."})
    )

    result = Orchestrator(provider, workspace=tmp_path).run(
        "How does local retrieval reduce model context?"
    )

    assert result.status == "completed"
    assert "Retrieved local knowledge" in provider.prompts[0]
    assert "bounded context budgets" in provider.prompts[0]
    assert result.knowledge_evidence
    assert result.knowledge_evidence[0]["source"] == "docs/architecture.md"


def test_orchestrator_knowledge_retrieval_can_be_disabled(tmp_path, monkeypatch):
    from aurix.knowledge import KnowledgeIndex

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("needle local knowledge retrieval", encoding="utf-8")
    KnowledgeIndex(tmp_path / ".aurix" / "knowledge.db").index_path(docs)
    monkeypatch.setenv("AURIX_RAG_ENABLED", "false")
    provider = SequenceProvider(json.dumps({"status": "final", "message": "Done."}))

    result = Orchestrator(provider, workspace=tmp_path).run("needle local knowledge")

    assert result.status == "completed"
    assert "Retrieved local knowledge" not in provider.prompts[0]
    assert result.knowledge_evidence == []


def test_orchestrator_ignores_corrupt_knowledge_index(tmp_path):
    metadata = tmp_path / ".aurix"
    metadata.mkdir()
    (metadata / "knowledge.db").write_bytes(b"not a sqlite database")
    provider = SequenceProvider(json.dumps({"status": "final", "message": "Still works."}))

    result = Orchestrator(provider, workspace=tmp_path).run(
        "Complete a task despite corrupt local index"
    )

    assert result.status == "completed"
    assert result.knowledge_evidence == []


def test_orchestrator_can_propose_then_review_patch_without_applying_it(tmp_path):
    import re
    import subprocess

    (tmp_path / "app.py").write_text("value = 'old'\n", encoding="utf-8")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "aurix-test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "AURIX test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "fixture"], check=True, capture_output=True
    )

    patch = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 'old'\n+value = eval('new')\n"

    class ReviewLoopProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, *, system=""):
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {"status": "tool_call", "tool": "propose_patch", "arguments": {"patch": patch}}
                )
            if self.calls == 2:
                match = re.search(r'"proposal_id": "([0-9a-f]{12})"', prompt)
                assert match, prompt
                return json.dumps(
                    {
                        "status": "tool_call",
                        "tool": "review_proposal",
                        "arguments": {"proposal_id": match.group(1)},
                    }
                )
            return json.dumps(
                {
                    "status": "final",
                    "message": "Proposal reviewed; manual approval and tests are still required.",
                }
            )

    provider = ReviewLoopProvider()
    result = Orchestrator(provider, workspace=tmp_path, enable_response_cache=False).run(
        "Propose and review a safe change"
    )
    assert result.status == "completed"
    assert provider.calls == 3
    assert "manual approval" in result.message
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "value = 'old'\n"
    assert any(item.get("tool") == "review_proposal" for item in result.trace)
    review_step = next(item for item in result.trace if item.get("tool") == "review_proposal")
    assert review_step.get("tool_status") == "review_required"


def test_review_proposal_rejects_extra_arguments(tmp_path):
    agent = Orchestrator(FakeProvider("{}"), workspace=tmp_path)
    with pytest.raises(ValueError, match="only a 12-character"):
        agent._call_tool("review_proposal", {"proposal_id": "a1b2c3d4e5f6", "apply": True})
