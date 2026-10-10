import asyncio
import json
from pathlib import Path

from aurix.autonomy import AutonomousKernel, StudyQueue


class FakeProvider:
    def __init__(self, response=None):
        self.response = response or json.dumps({
            "summary": "A concise note.",
            "key_points": ["A point"],
            "uncertainties": ["Needs independent verification"],
            "follow_up_topics": ["Rust async cancellation", "Rust async cancellation safety"],
            "sources": [],
        })
        self.calls = 0

    def generate(self, prompt, *, system=""):
        self.calls += 1
        assert "untrusted data" in system.lower() or "untrusted" in prompt.lower()
        return self.response


def test_queue_deduplicates_and_prioritizes(tmp_path: Path):
    queue = StudyQueue(tmp_path / "autonomy.db")
    first = queue.enqueue("  Rust   async ", priority=1)
    duplicate = queue.enqueue("Rust async", priority=4)
    queue.enqueue("SQLite WAL", priority=3)
    assert first["id"] == duplicate["id"]
    assert queue.claim_next()["topic"] == "SQLite WAL"


def test_study_once_creates_candidate_and_followup(tmp_path: Path):
    queue = StudyQueue(tmp_path / ".aurix" / "autonomy.db")
    queue.enqueue("Rust async cancellation")
    provider = FakeProvider()
    kernel = AutonomousKernel(provider, tmp_path)
    result = kernel.study_once()
    assert result["status"] == "candidate_created"
    assert result["review_required"] is True
    assert result["follow_up_topics_enqueued"] == 1
    assert provider.calls == 1
    status = queue.status()
    assert status["counts"]["completed"] == 1
    assert status["counts"]["pending"] == 1


def test_invalid_model_json_is_saved_as_review_candidate(tmp_path: Path):
    queue = StudyQueue(tmp_path / ".aurix" / "autonomy.db")
    queue.enqueue("Topic")
    kernel = AutonomousKernel(FakeProvider("not json"), tmp_path)
    result = kernel.study_once()
    assert result["status"] == "candidate_created"
    from aurix.learning import LearningStore
    records = LearningStore(tmp_path / ".aurix" / "learning.db").list_records(scope="autonomous-study")
    assert len(records) == 1
    assert records[0]["status"] == "candidate"
    assert records[0]["consent_to_train"] is False


def test_empty_queue_does_not_call_provider(tmp_path: Path):
    provider = FakeProvider()
    kernel = AutonomousKernel(provider, tmp_path)
    assert kernel.study_once()["status"] == "idle"
    assert provider.calls == 0


def test_daemon_stops_after_bounded_cycles(tmp_path: Path):
    queue = StudyQueue(tmp_path / ".aurix" / "autonomy.db")
    queue.enqueue("Topic")
    kernel = AutonomousKernel(FakeProvider(), tmp_path, min_interval_seconds=60,
                              max_interval_seconds=60, max_cycles=1)
    result = asyncio.run(kernel.run())
    assert result["status"] == "stopped"
    assert result["cycles"] == 1
    assert queue.status()["counts"]["completed"] == 1


def test_study_persists_retrieved_source_separately_from_hypothesis(tmp_path: Path):
    from aurix.research_memory import ResearchMemory

    queue = StudyQueue(tmp_path / ".aurix" / "autonomy.db")
    queue.enqueue("SQLite WAL")
    provider = FakeProvider(json.dumps({"summary": "WAL separates readers and writers.",
        "key_points": [], "uncertainties": ["Check official docs"], "follow_up_topics": [],
        "sources": ["https://sqlite.org/wal.html"]}))
    notes = ("SOURCE: https://sqlite.org/wal.html\nTITLE: Write-Ahead Logging\n"
             "SEARCH SNIPPET: Official documentation\nPAGE EXTRACT: Readers and writers can proceed concurrently.\n")
    kernel = AutonomousKernel(provider, tmp_path, research_adapter=lambda topic: notes)
    result = kernel.study_once()
    records = ResearchMemory(tmp_path / ".aurix" / "research_memory.db").list_records()
    assert result["retrieved_sources_stored"] == 1
    assert {r["kind"] for r in records} == {"retrieved_evidence", "model_hypothesis"}
    assert all(r["status"] == "candidate" for r in records)
    assert any(r["url"] == "https://sqlite.org/wal.html" for r in records)


def test_study_uses_reviewed_memory_and_falls_back_after_research_error(tmp_path: Path):
    from aurix.research_memory import ResearchMemory

    memory = ResearchMemory(tmp_path / ".aurix" / "research_memory.db")
    reviewed = memory.add(topic="SQLite WAL", kind="retrieved_evidence", title="WAL docs",
                          content="SQLite WAL supports concurrent readers", url="https://sqlite.org/wal.html")
    memory.review(reviewed["id"], decision="accepted")
    StudyQueue(tmp_path / ".aurix" / "autonomy.db").enqueue("SQLite WAL")
    calls = []

    def adapter(query):
        calls.append(query)
        if len(calls) == 1:
            raise RuntimeError("temporary search failure")
        return ("SOURCE: https://sqlite.org/wal.html\nTITLE: WAL\n"
                "SEARCH SNIPPET: SQLite WAL documentation\nPAGE EXTRACT: Readers and writers.\n")

    class CapturingProvider(FakeProvider):
        last_prompt = ""

        def generate(self, prompt, *, system=""):
            self.last_prompt = prompt
            return super().generate(prompt, system=system)

    provider = CapturingProvider()
    result = AutonomousKernel(provider, tmp_path, research_adapter=adapter).study_once()
    assert result["status"] == "candidate_created"
    assert result["prior_validated_memory_used"] == 1
    assert len(result["research_attempts"]) == 2
    assert len(calls) == 2
    assert "Operator-reviewed memory is prior context" in provider.last_prompt
    assert "SQLite WAL supports concurrent readers" in provider.last_prompt
