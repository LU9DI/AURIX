import json
import sys

from aurix.cli import main
from aurix.memory import create_memory


def test_memory_factory_defaults_to_workspace_scoped_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("AURIX_MEMORY_BACKEND", raising=False)
    monkeypatch.delenv("AURIX_MEMORY_PATH", raising=False)
    store = create_memory(workspace=tmp_path)
    record_id = store.add("repo:demo", "remember the auth regression")
    assert record_id == 1
    assert (tmp_path / ".aurix" / "memory.db").is_file()


def test_memory_factory_rejects_unknown_backend(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="memory backend"):
        create_memory("unknown", workspace=tmp_path)


def test_cli_add_and_search_memory_are_scope_isolated(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AURIX_MEMORY_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setattr(sys, "argv", ["aurix", "--workspace", str(tmp_path), "--memory-add",
                                      "authentication regression", "--memory-scope", "repo:one", "--json"])
    main()
    added = json.loads(capsys.readouterr().out)
    assert added["status"] == "stored"
    assert added["scope"] == "repo:one"

    store = create_memory("sqlite", workspace=tmp_path)
    store.add("repo:two", "authentication regression in other repository")
    monkeypatch.setattr(sys, "argv", ["aurix", "--workspace", str(tmp_path), "--memory-search",
                                      "authentication", "--memory-scope", "repo:one", "--json"])
    main()
    searched = json.loads(capsys.readouterr().out)
    assert searched["count"] == 1
    assert searched["records"][0]["scope"] == "repo:one"
    assert searched["records"][0]["content"] == "authentication regression"
