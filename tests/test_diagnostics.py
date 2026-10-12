from __future__ import annotations

from pathlib import Path

from aurix.diagnostics import run_diagnostics


class GoodProvider:
    def generate(self, prompt: str, *, system: str = "") -> str:
        return "AURIX_OK"


class FailingProvider:
    def generate(self, prompt: str, *, system: str = "") -> str:
        raise RuntimeError("secret=must-not-appear")


def test_diagnostics_are_read_only_and_report_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = run_diagnostics(tmp_path)
    assert result["workspace"] == str(tmp_path.resolve())
    assert any(item["name"] == "provider_probe" and item["status"] == "not_run"
               for item in result["checks"])
    assert not list(tmp_path.iterdir())


def test_live_provider_probe_succeeds_without_recording_response(tmp_path: Path):
    result = run_diagnostics(tmp_path, probe_provider=True, provider=GoodProvider())
    probe = next(item for item in result["checks"] if item["name"] == "provider_probe")
    assert probe["status"] == "ok"
    assert "AURIX_OK" not in str(result)


def test_provider_exception_details_are_not_exposed(tmp_path: Path):
    result = run_diagnostics(tmp_path, probe_provider=True, provider=FailingProvider())
    probe = next(item for item in result["checks"] if item["name"] == "provider_probe")
    assert probe["status"] == "fail"
    assert "must-not-appear" not in str(result)
