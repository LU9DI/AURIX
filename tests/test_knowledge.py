from pathlib import Path

import pytest

from aurix.knowledge import KnowledgeIndex


def test_index_and_search_without_provider(tmp_path: Path):
    project = tmp_path / "docs"
    project.mkdir()
    (project / "python.md").write_text(
        "Python testing uses pytest fixtures and assertions.\n", encoding="utf-8"
    )
    (project / "database.md").write_text(
        "SQLite stores local records and structured knowledge.\n", encoding="utf-8"
    )
    index = KnowledgeIndex(tmp_path / ".aurix" / "knowledge.db")
    result = index.index_path(project)
    assert result["indexed_files"] == 2
    found = index.search("pytest testing fixtures")
    assert found
    assert found[0]["source"].endswith("python.md")
    assert index.stats() == {"files": 2, "chunks": 2}


def test_reject_empty_query(tmp_path: Path):
    index = KnowledgeIndex(tmp_path / "knowledge.db")
    with pytest.raises(ValueError):
        index.search("   ")


def test_skips_hidden_aurix_and_git_dirs(tmp_path: Path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".aurix").mkdir()
    (root / "src").mkdir()
    (root / ".git" / "secret.md").write_text("needle secret", encoding="utf-8")
    (root / ".aurix" / "internal.md").write_text("needle internal", encoding="utf-8")
    (root / "src" / "code.py").write_text("needle implementation", encoding="utf-8")
    index = KnowledgeIndex(tmp_path / "db.sqlite")
    index.index_path(root)
    found = index.search("needle")
    assert len(found) == 1
    assert found[0]["source"].endswith("code.py")


def test_incremental_sync_skips_unchanged_and_updates_changed_files(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    doc = root / "guide.md"
    doc.write_text("alpha original knowledge", encoding="utf-8")
    index = KnowledgeIndex(tmp_path / "knowledge.db")

    first = index.index_path(root)
    second = index.index_path(root)
    assert first["indexed_files"] == 1
    assert second["indexed_files"] == 0
    assert second["unchanged_files"] == 1

    doc.write_text("beta revised knowledge", encoding="utf-8")
    third = index.index_path(root)
    assert third["indexed_files"] == 1
    assert not index.search("alpha original")
    assert index.search("beta revised")


def test_incremental_sync_removes_deleted_files_only_in_its_root(tmp_path: Path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    stale = first_root / "stale.md"
    retained = second_root / "retained.md"
    stale.write_text("unique needle from first root", encoding="utf-8")
    retained.write_text("unique needle from second root", encoding="utf-8")
    index = KnowledgeIndex(tmp_path / "knowledge.db")
    index.index_path(first_root)
    index.index_path(second_root)

    stale.unlink()
    result = index.index_path(first_root)
    assert result["removed_files"] == 1
    matches = index.search("unique needle")
    sources = {item["source"] for item in matches}
    assert str(stale) not in sources
    assert str(retained) in sources


def test_sync_does_not_prune_after_max_files_truncates_scan(tmp_path: Path):
    root = tmp_path / "many"
    root.mkdir()
    for name in ("a.md", "b.md", "c.md"):
        (root / name).write_text(f"content {name}", encoding="utf-8")
    index = KnowledgeIndex(tmp_path / "knowledge.db")
    index.index_path(root)
    result = index.index_path(root, max_files=1)
    assert result["scan_complete"] is False
    assert result["removed_files"] == 0
    assert index.stats()["files"] == 3


def test_rejects_symlink_as_index_root(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "doc.md").write_text("some content", encoding="utf-8")
    link = tmp_path / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    index = KnowledgeIndex(tmp_path / "knowledge.db")
    with pytest.raises(ValueError, match="symlink"):
        index.index_path(link)
