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
