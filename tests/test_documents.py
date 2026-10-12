from pathlib import Path

import pytest

from aurix.documents import analyze_document, _chunks


class FakeProvider:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, *, system=""):
        self.calls.append(prompt)
        # Return short outputs so the test exercises hierarchical reduction too.
        return "Key point: revenue rose 12%; see pages cited in source."


def test_chunks_preserve_source_page_ranges():
    chunks = _chunks([(1, "a" * 8), (2, "b" * 8), (3, "c" * 8)], 12)
    assert chunks[0]["start_page"] == 1
    assert "[SOURCE PAGE 1]" in chunks[0]["text"]
    assert chunks[-1]["end_page"] == 3
    assert all(chunk["text"] for chunk in chunks)


def test_analyze_text_document_hierarchically_and_tracks_calls(tmp_path: Path):
    source = tmp_path / "large.txt"
    source.write_text(("Revenue rose 12 percent. Risk remains elevated.\n" * 90), encoding="utf-8")
    provider = FakeProvider()
    result = analyze_document(source, provider, max_chunk_chars=2000, max_workers=2)
    assert result["status"] == "completed"
    assert result["page_count"] >= 1
    assert result["chunk_count"] >= 2
    assert result["model_calls"] == len(provider.calls)
    assert result["source_sha256"]
    assert "12%" in result["summary"]


def test_rejects_empty_document(tmp_path: Path):
    source = tmp_path / "empty.txt"
    source.write_text("   ", encoding="utf-8")
    with pytest.raises(ValueError, match="No extractable text"):
        analyze_document(source, FakeProvider())


def test_rejects_unsupported_extension(tmp_path: Path):
    source = tmp_path / "doc.bin"
    source.write_bytes(b"data")
    with pytest.raises(ValueError, match="Unsupported format"):
        analyze_document(source, FakeProvider())


def test_rejects_bad_worker_count(tmp_path: Path):
    source = tmp_path / "text.md"
    source.write_text("some useful text", encoding="utf-8")
    with pytest.raises(ValueError, match="max_workers"):
        analyze_document(source, FakeProvider(), max_workers=17)
