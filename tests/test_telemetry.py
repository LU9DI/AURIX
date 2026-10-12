import json

from aurix.telemetry import JSONLTelemetry, estimate_tokens


def test_telemetry_records_metadata_without_content(tmp_path):
    path = tmp_path / "runs.jsonl"
    telemetry = JSONLTelemetry(path)
    telemetry.record({"event": "generation_completed", "prompt_chars": 42})
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["event"] == "generation_completed"
    assert record["prompt_chars"] == 42
    assert "prompt" not in record
    assert "timestamp" in record


def test_token_estimate_is_bounded_and_documented_approximation():
    assert estimate_tokens("") == 0
    assert estimate_tokens("12345") == 2
