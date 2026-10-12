import json

import pytest

from aurix.learning import LearningStore


def test_candidate_is_not_automatically_accepted_or_trainable(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    record_id = store.add_candidate("A useful strategy", source="task_outcome", quality=0.99)
    record = store.list_records()[0]
    assert record["id"] == record_id
    assert record["status"] == "candidate"
    assert record["consent_to_train"] is False
    out = tmp_path / "train.jsonl"
    assert store.export_training_jsonl(out) == 0
    assert out.read_text() == ""


def test_training_export_requires_acceptance_consent_and_quality(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    allowed = store.add_candidate("approved example", source="user_feedback", quality=0.95, consent_to_train=True)
    no_consent = store.add_candidate("private example", source="user_feedback", quality=0.99, consent_to_train=False)
    low_quality = store.add_candidate("weak example", source="peer_model", quality=0.3, consent_to_train=True)
    assert store.review(allowed, decision="accepted")
    assert store.review(no_consent, decision="accepted")
    assert store.review(low_quality, decision="accepted")
    target = tmp_path / "training" / "data.jsonl"
    assert store.export_training_jsonl(target, min_quality=0.8) == 1
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert rows == [{"text": "approved example", "source": "user_feedback", "scope": "default", "quality": 0.95, "evidence": []}]


def test_review_only_changes_candidates_and_validates_inputs(tmp_path):
    store = LearningStore(tmp_path / "learning.db")
    record_id = store.add_candidate("candidate", source="local_tool")
    assert store.review(record_id, decision="rejected")
    assert not store.review(record_id, decision="accepted")
    with pytest.raises(ValueError):
        store.review(record_id, decision="maybe")
    with pytest.raises(ValueError):
        store.add_candidate("candidate", source="unknown")
    with pytest.raises(ValueError):
        store.add_candidate("candidate", consent_to_train=1)
