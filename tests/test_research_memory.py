from pathlib import Path

from aurix.research_memory import ResearchMemory, parse_research_blocks


def test_parse_research_blocks_preserves_provenance_and_bounds():
    blocks = parse_research_blocks(
        "SOURCE: https://example.org/docs\nTITLE: Example docs\n"
        "SEARCH SNIPPET: A short summary\nPAGE EXTRACT: A longer excerpt\n\n---\n\n"
        "SOURCE: file:///etc/passwd\nTITLE: unsafe\nPAGE EXTRACT: no"
    )
    assert len(blocks) == 1
    assert blocks[0]["url"] == "https://example.org/docs"
    assert blocks[0]["title"] == "Example docs"
    assert "longer excerpt" in blocks[0]["excerpt"]


def test_discovery_dedup_and_review_promotion(tmp_path: Path):
    memory = ResearchMemory(tmp_path / "research.db")
    first = memory.add(
        topic="SQLite WAL",
        kind="retrieved_evidence",
        title="Docs",
        url="https://example.org/wal",
        content="WAL allows readers and writers to coexist.",
    )
    duplicate = memory.add(
        topic="Other phrasing",
        kind="retrieved_evidence",
        title="Docs copy",
        url="https://example.org/wal",
        content="WAL allows readers and writers to coexist.",
    )
    assert first["id"] == duplicate["id"]
    assert first["status"] == "candidate"
    assert first["kind"] == "retrieved_evidence"
    assert memory.review(first["id"], decision="accepted") is True
    reviewed = memory.list_records()[0]
    assert reviewed["status"] == "accepted"
    assert reviewed["kind"] == "validated_knowledge"
    assert memory.review(first["id"], decision="rejected") is False


def test_hypothesis_never_auto_promoted_and_invalid_url_removed(tmp_path: Path):
    memory = ResearchMemory(tmp_path / "research.db")
    item = memory.add(
        topic="Topic",
        kind="model_hypothesis",
        title="Generated",
        url="file:///secret",
        content="Needs independent verification.",
    )
    assert item["url"] is None
    assert item["kind"] == "model_hypothesis"
    assert item["status"] == "candidate"


def test_review_requires_explicit_valid_decision(tmp_path: Path):
    memory = ResearchMemory(tmp_path / "research.db")
    item = memory.add(
        topic="Topic", kind="model_hypothesis", title="Generated", content="A hypothesis."
    )
    try:
        memory.review(item["id"], decision="validated")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid decision should be rejected")


def test_search_relevant_excludes_unreviewed_candidates_by_default(tmp_path):
    memory = ResearchMemory(tmp_path / "research.db")
    candidate = memory.add(
        topic="SQLite WAL",
        kind="model_hypothesis",
        title="WAL",
        content="SQLite WAL improves reader writer concurrency",
    )
    accepted = memory.add(
        topic="SQLite WAL",
        kind="retrieved_evidence",
        title="Official WAL docs",
        content="SQLite WAL allows readers and writers concurrently",
        url="https://sqlite.org/wal.html",
    )
    assert memory.review(accepted["id"], decision="accepted")
    results = memory.search_relevant("SQLite WAL readers writers")
    assert [row["id"] for row in results] == [accepted["id"]]
    all_candidates = memory.search_relevant("SQLite WAL", accepted_only=False)
    assert {row["id"] for row in all_candidates} == {candidate["id"], accepted["id"]}
