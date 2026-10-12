import pytest

from aurix.memory.sqlite import SQLiteMemory


def test_memory_add_and_search(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.db")
    record_id = memory.add("repo:demo", "Fix the flaky authentication test", {"source": "test"})
    results = memory.search("authentication", scope="repo:demo")
    assert results[0]["id"] == record_id
    assert results[0]["metadata"]["source"] == "test"


def test_memory_rejects_empty_values(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.db")
    with pytest.raises(ValueError):
        memory.add("", "content")


def test_retrieval_ranks_relevant_records_above_recent_irrelevant(tmp_path):
    from aurix.memory.retrieval import retrieve_memories

    memory = SQLiteMemory(tmp_path / "memory.db")
    memory.add("repo:demo", "authentication bug fixed by refreshing JWT")
    memory.add("repo:demo", "unrelated documentation cleanup")
    memory.add("repo:demo", "authentication regression in token refresh")
    results = retrieve_memories(memory, "authentication regression", scope="repo:demo")
    assert len(results) == 2
    assert results[0]["content"] == "authentication regression in token refresh"
    assert results[0]["relevance_score"] > results[1]["relevance_score"]
    assert results[0]["matched_terms"] == ["authentication", "regression"]


def test_retrieval_is_scope_filtered_and_bounded(tmp_path):
    from aurix.memory.retrieval import retrieve_memories

    memory = SQLiteMemory(tmp_path / "memory.db")
    memory.add("repo:one", "authentication " + "detail " * 300)
    memory.add("repo:two", "authentication in another repository")
    results = retrieve_memories(
        memory, "authentication", scope="repo:one", limit=1, max_content_chars=100
    )
    assert len(results) == 1
    assert results[0]["scope"] == "repo:one"
    assert len(results[0]["content"]) == 100
    assert results[0]["content_truncated"] is True


def test_retrieval_rejects_query_without_tokens(tmp_path):
    from aurix.memory.retrieval import retrieve_memories

    memory = SQLiteMemory(tmp_path / "memory.db")
    with pytest.raises(ValueError, match="at least one token"):
        retrieve_memories(memory, "!!!", scope="repo:demo")


def test_hybrid_retrieval_can_find_semantic_match_without_shared_terms(tmp_path):
    from aurix.memory.retrieval import retrieve_memories

    class FakeEmbedder:
        def embed(self, text):
            vectors = {
                "car repair": [1.0, 0.0],
                "automobile mechanic diagnosis": [1.0, 0.0],
                "car repair guide": [-1.0, 0.0],
            }
            return vectors[text]

    memory = SQLiteMemory(tmp_path / "memory.db")
    memory.add("repo:demo", "automobile mechanic diagnosis")
    memory.add("repo:demo", "car repair guide")
    results = retrieve_memories(
        memory, "car repair", scope="repo:demo", embedder=FakeEmbedder(), lexical_weight=0.4
    )
    assert results[0]["content"] == "automobile mechanic diagnosis"
    assert results[0]["retrieval_mode"] == "hybrid"
    assert results[0]["matched_terms"] == []
    assert results[0]["semantic_score"] == 1.0


def test_hybrid_retrieval_rejects_mismatched_embedding_dimensions(tmp_path):
    from aurix.memory.retrieval import retrieve_memories

    class BadEmbedder:
        def embed(self, text):
            return [1.0] if text == "auth regression" else [1.0, 0.0]

    memory = SQLiteMemory(tmp_path / "memory.db")
    memory.add("repo:demo", "auth regression detected")
    with pytest.raises(ValueError, match="dimensions do not match"):
        retrieve_memories(memory, "auth regression", scope="repo:demo", embedder=BadEmbedder())


def test_retrieval_evaluation_metrics(tmp_path):
    from aurix.memory.retrieval import evaluate_retrieval

    results = [{"id": 9}, {"id": 4}, {"id": 3}]
    metrics = evaluate_retrieval(results, {4, 9}, k=2)
    assert metrics == {
        "precision_at_2": 1.0,
        "recall_at_2": 1.0,
        "reciprocal_rank": 1.0,
        "relevant_found": 2,
        "relevant_total": 2,
    }


def test_retrieval_evaluation_rejects_nonpositive_k():
    from aurix.memory.retrieval import evaluate_retrieval

    with pytest.raises(ValueError, match="at least 1"):
        evaluate_retrieval([], set(), k=0)


def test_memory_evidence_metadata_is_persisted_and_validated(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.db")
    record_id = memory.add(
        "repo:demo",
        "The regression test passed",
        {"kind": "test_result", "confidence": 1.0, "source": "ci"},
    )
    result = memory.search("regression", scope="repo:demo")[0]
    assert result["id"] == record_id
    assert result["metadata"]["kind"] == "test_result"
    assert result["metadata"]["confidence"] == 1.0
    assert result["metadata"]["source"] == "ci"


@pytest.mark.parametrize(
    "metadata",
    [
        {"kind": "certainty"},
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"confidence": True},
        {"confidence": "0.9"},
    ],
)
def test_memory_rejects_invalid_evidence_metadata(tmp_path, metadata):
    memory = SQLiteMemory(tmp_path / "memory.db")
    with pytest.raises(ValueError):
        memory.add("repo:demo", "A memory", metadata)


def test_memory_accepts_legacy_custom_metadata(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.db")
    memory.add("repo:demo", "Legacy metadata remains valid", {"source": "old-client", "custom": 7})
    assert memory.search("Legacy", scope="repo:demo")[0]["metadata"] == {
        "source": "old-client",
        "custom": 7,
    }


def test_memory_delete_and_clear_are_scope_limited(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.db")
    first = memory.add("repo:one", "first memory")
    second = memory.add("repo:one", "second memory")
    other = memory.add("repo:two", "other memory")
    assert memory.delete(first, scope="repo:wrong") is False
    assert memory.delete(first, scope="repo:one") is True
    assert memory.delete(first) is False
    assert [item["id"] for item in memory.search("memory", scope="repo:one")] == [second]
    assert memory.clear(scope="repo:one") == 1
    assert [item["id"] for item in memory.search("memory")] == [other]


def test_memory_delete_rejects_invalid_identifier(tmp_path):
    memory = SQLiteMemory(tmp_path / "memory.db")
    with pytest.raises(ValueError, match="positive integer"):
        memory.delete(True)
