import pytest

from aurix.tools.workspace import read_text, safe_path


def test_safe_path_rejects_escape(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    with pytest.raises(ValueError):
        safe_path(workspace, "../outside")


def test_read_text(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    assert read_text(tmp_path, "hello.txt") == "hello"


def test_context_reads_source_but_skips_environment_secrets(tmp_path):
    from aurix.tools.workspace import build_workspace_context

    (tmp_path / "README.md").write_text("Project overview", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=do-not-leak", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    context = build_workspace_context(tmp_path)
    assert "Project overview" in context
    assert "print('hello')" in context
    assert "do-not-leak" not in context


def test_context_is_bounded(tmp_path):
    from aurix.tools.workspace import build_workspace_context

    (tmp_path / "README.md").write_text("x" * 10000, encoding="utf-8")
    context = build_workspace_context(tmp_path, max_chars=500)
    assert len(context) <= 600


def test_read_text_rejects_sensitive_files(tmp_path):
    from aurix.tools.workspace import read_text

    (tmp_path / "credentials.json").write_text('{"token":"secret"}', encoding="utf-8")
    with pytest.raises(PermissionError):
        read_text(tmp_path, "credentials.json")


def test_search_text_is_case_insensitive_and_bounded(tmp_path):
    from aurix.tools.workspace import search_text

    (tmp_path / "main.py").write_text("Alpha\nbeta alpha\n", encoding="utf-8")
    (tmp_path / ".env").write_text("alpha=secret", encoding="utf-8")
    matches = search_text(tmp_path, "ALPHA", limit=1)
    assert len(matches) == 1
    assert matches[0]["path"] == "main.py"


def test_safe_path_rejects_symlink_components(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "real.txt").write_text("inside", encoding="utf-8")
    try:
        (workspace / "alias.txt").symlink_to(workspace / "real.txt")
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on this platform")
    with pytest.raises(PermissionError):
        safe_path(workspace, "alias.txt")



def test_workspace_reads_require_regular_files(tmp_path):
    from aurix.tools.workspace import read_text, read_text_lines

    (tmp_path / "folder").mkdir()
    with pytest.raises(FileNotFoundError):
        read_text(tmp_path, "folder")
    with pytest.raises(FileNotFoundError):
        read_text_lines(tmp_path, "folder")


def test_read_text_lines_returns_numbered_targeted_range(tmp_path):
    from aurix.tools.workspace import read_text_lines

    (tmp_path / "module.py").write_text("a\nb\nc\nd\n", encoding="utf-8")
    result = read_text_lines(tmp_path, "module.py", start_line=2, end_line=3)
    assert result["content"] == "2: b\n3: c"
    assert result["total_lines"] == 4
    assert result["truncated"] is True


def test_read_text_lines_rejects_invalid_ranges_and_large_requests(tmp_path):
    from aurix.tools.workspace import read_text_lines

    (tmp_path / "module.py").write_text("x\n" * 600, encoding="utf-8")
    with pytest.raises(ValueError):
        read_text_lines(tmp_path, "module.py", start_line=0)
    with pytest.raises(ValueError, match="500 lines"):
        read_text_lines(tmp_path, "module.py", start_line=1, end_line=501)

 
def test_workspace_tools_skip_common_credential_locations_and_files(tmp_path):
    from aurix.tools.workspace import build_workspace_context, list_files, read_text, search_text

    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_ecdsa").write_text("PRIVATE_KEY_SENTINEL", encoding="utf-8")
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "credentials").write_text("AWS_SECRET_SENTINEL", encoding="utf-8")
    (tmp_path / ".docker").mkdir()
    (tmp_path / ".docker" / "config.json").write_text("DOCKER_AUTH_SENTINEL", encoding="utf-8")
    (tmp_path / ".npmrc").write_text("//registry.example/:_authToken=NPM_SECRET_SENTINEL", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('safe')", encoding="utf-8")

    context = build_workspace_context(tmp_path)
    listed = list_files(tmp_path)
    searched = search_text(tmp_path, "SENTINEL")

    for secret in ("PRIVATE_KEY_SENTINEL", "AWS_SECRET_SENTINEL", "DOCKER_AUTH_SENTINEL", "NPM_SECRET_SENTINEL"):
        assert secret not in context
    assert not any(path.startswith((".ssh/", ".aws/", ".docker/")) for path in listed)
    assert ".npmrc" not in listed
    assert searched == []
    with pytest.raises(PermissionError):
        read_text(tmp_path, ".aws/credentials")
    with pytest.raises(PermissionError):
        read_text(tmp_path, ".npmrc")

 
def test_workspace_tools_skip_kubernetes_and_terraform_secrets(tmp_path):
    from aurix.tools.workspace import build_workspace_context, read_text, search_text

    (tmp_path / ".kube").mkdir()
    (tmp_path / ".kube" / "config").write_text("KUBE_TOKEN_SENTINEL", encoding="utf-8")
    (tmp_path / ".terraform").mkdir()
    (tmp_path / ".terraform" / "terraform.tfstate").write_text(
        "TERRAFORM_SECRET_SENTINEL", encoding="utf-8"
    )
    context = build_workspace_context(tmp_path)
    assert "KUBE_TOKEN_SENTINEL" not in context
    assert "TERRAFORM_SECRET_SENTINEL" not in context
    assert search_text(tmp_path, "SENTINEL") == []
    with pytest.raises(PermissionError):
        read_text(tmp_path, ".kube/config")
    with pytest.raises(PermissionError):
        read_text(tmp_path, ".terraform/terraform.tfstate")


def test_direct_reads_reject_ignored_metadata_and_dependency_directories(tmp_path):
    from aurix.tools.workspace import read_text, read_text_lines

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[remote]", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "credentials.txt").write_text("LOCAL_SECRET", encoding="utf-8")
    for relative in (".git/config", ".venv/credentials.txt"):
        with pytest.raises(PermissionError, match="ignored"):
            read_text(tmp_path, relative)
        with pytest.raises(PermissionError, match="ignored"):
            read_text_lines(tmp_path, relative)



def test_workspace_ignored_directories_are_case_insensitive(tmp_path):
    from aurix.tools.workspace import (
        build_workspace_context,
        list_files,
        read_text,
        read_text_lines,
        search_text,
    )

    (tmp_path / ".GIT").mkdir()
    (tmp_path / ".GIT" / "config").write_text("CASE_VARIANT_GIT_SENTINEL", encoding="utf-8")
    (tmp_path / ".VENV").mkdir()
    (tmp_path / ".VENV" / "credentials.txt").write_text(
        "CASE_VARIANT_VENV_SENTINEL", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text("safe source", encoding="utf-8")

    context = build_workspace_context(tmp_path)
    listed = list_files(tmp_path)
    matches = search_text(tmp_path, "SENTINEL")

    assert "CASE_VARIANT_GIT_SENTINEL" not in context
    assert "CASE_VARIANT_VENV_SENTINEL" not in context
    assert not any(path.lower().startswith((".git/", ".venv/")) for path in listed)
    assert matches == []
    for relative in (".GIT/config", ".VENV/credentials.txt"):
        with pytest.raises(PermissionError, match="ignored"):
            read_text(tmp_path, relative)
        with pytest.raises(PermissionError, match="ignored"):
            read_text_lines(tmp_path, relative)



def test_search_text_rejects_nonpositive_or_noninteger_file_limits(tmp_path):
    from aurix.tools.workspace import search_text

    (tmp_path / "main.py").write_text("safe", encoding="utf-8")
    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="max_file_bytes must be a positive integer"):
            search_text(tmp_path, "safe", max_file_bytes=value)


def test_guarded_reader_rejects_invalid_byte_limits(tmp_path):
    from aurix.tools.workspace import _read_regular_file_no_follow

    target = tmp_path / "main.py"
    target.write_text("safe", encoding="utf-8")
    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="max_bytes must be a positive integer"):
            _read_regular_file_no_follow(target, max_bytes=value)



def test_workspace_walk_prunes_ignored_and_symlink_directories(tmp_path, monkeypatch):
    import os
    from pathlib import Path

    from aurix.tools import workspace as workspace_tools

    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / ".git" / "objects" / "hidden.py").write_text("SECRET", encoding="utf-8")
    (tmp_path / "node_modules" / "package").mkdir(parents=True)
    (tmp_path / "node_modules" / "package" / "hidden.js").write_text("SECRET", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "safe.py").write_text("safe", encoding="utf-8")
    try:
        (tmp_path / "linked").symlink_to(tmp_path / "src", target_is_directory=True)
    except (OSError, NotImplementedError):
        pass

    original_walk = os.walk
    visited = []

    def tracked_walk(*args, **kwargs):
        for current, directories, files in original_walk(*args, **kwargs):
            visited.append(Path(current).relative_to(tmp_path).as_posix())
            yield current, directories, files

    monkeypatch.setattr(workspace_tools.os, "walk", tracked_walk)
    listed = workspace_tools.list_files(tmp_path)

    assert "src/safe.py" in listed
    assert not any(path.startswith((".git", "node_modules")) for path in visited)
    assert "linked" not in visited
    assert not any("hidden" in path for path in listed)



def test_workspace_context_rejects_invalid_limits(tmp_path):
    from aurix.tools.workspace import build_workspace_context

    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="max_chars must be a positive integer"):
            build_workspace_context(tmp_path, max_chars=value)
        with pytest.raises(ValueError, match="max_files must be a positive integer"):
            build_workspace_context(tmp_path, max_files=value)
