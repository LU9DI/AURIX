import json

from aurix.orchestrator import Orchestrator
from aurix.protocol import (
    ProtocolDiagnostics,
    build_repair_prompt,
    parse_protocol_response,
)
from aurix.telemetry import JSONLTelemetry


class SequenceProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, prompt, *, system=""):
        self.calls.append((prompt, system))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _orchestrator(tmp_path, provider, **kwargs):
    return Orchestrator(
        provider,
        workspace=tmp_path,
        telemetry=JSONLTelemetry(tmp_path / "runs.jsonl"),
        **kwargs,
    )


def test_valid_json_with_status_is_accepted():
    parsed = parse_protocol_response('{"status":"final","message":"done"}')

    assert parsed.ok
    assert parsed.extraction_method == "direct"


def test_json_without_status_is_a_conformance_error_never_success():
    parsed = parse_protocol_response('{"message":"done"}')

    assert not parsed.ok
    assert parsed.error == "missing_status"


def test_markdown_fenced_json_is_extracted_strictly():
    parsed = parse_protocol_response('```json\n{"status":"final","message":"done"}\n```')

    assert parsed.ok
    assert parsed.extraction_method == "markdown_fence"


def test_json_with_prose_prefix_and_one_object_is_extracted():
    parsed = parse_protocol_response('Here is the result:\n{"status":"final","message":"done"}')

    assert parsed.ok
    assert parsed.extraction_method == "single_object"


def test_malformed_json_is_rejected():
    parsed = parse_protocol_response('{"status": "final", "message": }')

    assert not parsed.ok
    assert parsed.error == "invalid_json"


def test_truncated_response_is_rejected():
    parsed = parse_protocol_response(
        '{"status":"tool_call","tool":"propose_patch","arguments":{"patch":"--- a/x'
    )

    assert not parsed.ok
    assert parsed.error == "invalid_json"


def test_multiple_json_objects_are_rejected():
    parsed = parse_protocol_response('{"status":"final"} {"status":"final"}')

    assert not parsed.ok
    assert parsed.error == "invalid_json"


def test_repair_prompt_requests_exactly_one_object():
    prompt = build_repair_prompt("not json", "invalid_json")

    assert "exactly one JSON object" in prompt
    assert "Do not use Markdown fences" in prompt
    assert "Do not generate, rewrite, or extend a patch" in prompt
    assert "TASK" not in prompt


def test_orchestrator_repairs_missing_status_once(tmp_path):
    provider = SequenceProvider(
        '{"message":"MARKER_ORIGINAL_123"}',
        '{"status":"final","message":"repaired response"}',
    )

    result = _orchestrator(tmp_path, provider).run("Inspect the task")

    assert result.status == "completed"
    assert result.message == "repaired response"
    assert len(provider.calls) == 2
    trace = result.trace[0]
    assert trace["protocol_attempts"] == 2
    assert trace["protocol_outcome"] == "valid_after_repair"
    assert trace["original_protocol_error"] == "missing_status"
    assert trace["original_response_chars"] > 0
    assert trace["repaired_response_chars"] > 0
    assert "original_response_sha256" in trace
    assert "repaired_response_sha256" in trace
    assert "MARKER_ORIGINAL_123" not in json.dumps(result.trace)


def test_orchestrator_extracts_markdown_fence_without_extra_model_call(tmp_path):
    provider = SequenceProvider('```json\n{"status":"final","message":"done"}\n```')

    result = _orchestrator(tmp_path, provider).run("Inspect the task")

    assert result.status == "completed"
    assert len(provider.calls) == 1
    trace = result.trace[0]
    assert trace["protocol_outcome"] == "valid_extracted"
    assert trace["protocol_extraction"] == "markdown_fence"
    assert trace["protocol_attempts"] == 1


def test_second_conformance_failure_stops_after_one_repair(tmp_path):
    provider = SequenceProvider("not json", "still not json")

    result = _orchestrator(tmp_path, provider).run("Inspect the task")

    assert result.status == "invalid_response"
    assert len(provider.calls) == 2
    trace = result.trace[0]
    assert trace["protocol_attempts"] == 2
    assert trace["protocol_outcome"] == "repair_failed"
    assert trace["protocol_error"] == "invalid_json"
    assert trace["repair_error"] == "invalid_json"


def test_provider_failure_is_recorded_without_crashing(tmp_path):
    provider = SequenceProvider(RuntimeError("timed out for sk-abcdefgh12345"))

    result = _orchestrator(tmp_path, provider).run("Inspect the task")

    assert result.status == "invalid_response"
    assert len(provider.calls) == 1
    trace = result.trace[0]
    assert trace["provider_error"] == "RuntimeError"
    assert trace["protocol_outcome"] == "provider_error"
    assert "timed out" in trace["provider_error_detail"]
    assert "sk-abcdefgh12345" not in json.dumps(result.trace)


def test_repair_provider_failure_is_recorded_without_crashing(tmp_path):
    provider = SequenceProvider('{"message":"missing status"}', TimeoutError("timed out"))

    result = _orchestrator(tmp_path, provider).run("Inspect the task")

    assert result.status == "invalid_response"
    assert len(provider.calls) == 2
    trace = result.trace[0]
    assert trace["repair_attempted"] is True
    assert trace["repair_error"] == "provider_error"
    assert trace["provider_error"] == "TimeoutError"
    assert trace["protocol_outcome"] == "repair_failed"
    assert trace["protocol_attempts"] == 2


def test_protocol_diagnostics_are_opt_in_and_redacted(tmp_path):
    diagnostics = ProtocolDiagnostics(tmp_path, enabled=True)
    diagnostics.record(
        step=1,
        attempt=1,
        outcome="invalid",
        raw='{"api_key":"sk-abcdefgh12345","email":"person@example.com"}',
        error="invalid_json",
    )

    assert diagnostics.path is not None
    content = diagnostics.path.read_text(encoding="utf-8")
    assert "sk-abcdefgh12345" not in content
    assert "person@example.com" not in content
    assert "[REDACTED]" in content

    disabled = ProtocolDiagnostics(tmp_path / "disabled", enabled=False)
    disabled.record(step=1, attempt=1, outcome="invalid", raw="secret", error="invalid_json")
    assert disabled.path is None
    assert not (tmp_path / "disabled").exists()
