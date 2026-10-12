import subprocess

import pytest

from aurix.tools.execution import _safe_environment, run_test_suite


def test_execution_requires_confirmation(tmp_path):
    with pytest.raises(PermissionError, match="confirmation"):
        run_test_suite(tmp_path, "pytest")


def test_only_fixed_suites_are_accepted(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        run_test_suite(tmp_path, "shell; rm -rf /", confirm=True)


def test_timeout_is_bounded_and_workspace_must_exist(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_test_suite(tmp_path / "missing", confirm=True)
    # Even a huge requested timeout is clamped; assert through a fake process.
    original = subprocess.run
    seen = {}

    def fake_run(*args, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(args[0], 0, "ok", "")

    subprocess.run = fake_run
    try:
        result = run_test_suite(tmp_path, "pytest", confirm=True, timeout_seconds=999)
    finally:
        subprocess.run = original
    assert seen["timeout"] == 120
    assert result["passed"] is True


def test_runner_drops_secret_like_environment_variables(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    env = _safe_environment()
    assert "OPENAI_API_KEY" not in env
    assert "DATABASE_URL" not in env
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_runner_reports_nonzero_exit(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, "failure", "trace")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_test_suite(tmp_path, "pytest", confirm=True)
    assert result["passed"] is False
    assert result["returncode"] == 1
    assert result["stderr"] == "trace"


def test_docker_mode_requires_explicit_local_image(tmp_path):
    with pytest.raises(ValueError, match="sandbox-image"):
        run_test_suite(tmp_path, confirm=True, isolation="docker")


def test_docker_image_reference_rejects_option_injection():
    from aurix.tools.execution import _docker_command

    with pytest.raises(ValueError, match="Invalid Docker image"):
        _docker_command(
            __import__("pathlib").Path("/tmp/work"), "pytest", "--privileged", "aurix-test-unit"
        )


def test_docker_mode_is_network_disabled_and_never_pulls(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command, 0, "sha256:" + "a" * 64 if "inspect" in command else "ok", ""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_test_suite(
        tmp_path, "pytest", confirm=True, isolation="docker", sandbox_image="aurix-test:local"
    )
    assert result["passed"] is True
    assert result["isolation"] == "docker"
    assert "--network=none" in calls[1][0]
    assert "--read-only" in calls[1][0]
    assert "--user=65532:65532" in calls[1][0]
    mount = calls[1][0][calls[1][0].index("--mount") + 1]
    assert mount.endswith("dst=/workspace,readonly")
    assert ",rw" not in mount
    assert "--cap-drop=ALL" in calls[1][0]
    assert "--pull=never" in calls[1][0]
    assert "--name" in calls[1][0]
    assert calls[0][0][:4] == ["docker", "image", "inspect", "--format={{.Id}}"]
    assert calls[1][0][-5] == "sha256:" + "a" * 64
    assert result["sandbox_image_id"] == "sha256:" + "a" * 64
    assert calls[1][1]["shell"] is False


def test_docker_mode_fails_closed_if_docker_missing(monkeypatch, tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="without host fallback"):
        run_test_suite(tmp_path, confirm=True, isolation="docker", sandbox_image="aurix-test:local")


def test_docker_timeout_attempts_to_remove_container(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, "sha256:" + "b" * 64, "")
        if command[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(command, 1, output="partial")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_test_suite(
        tmp_path,
        confirm=True,
        timeout_seconds=1,
        isolation="docker",
        sandbox_image="aurix-test:local",
    )
    assert result["timed_out"] is True
    assert any(command[:3] == ["docker", "rm", "-f"] for command in calls)


def test_docker_mode_refuses_unparseable_image_id_before_running(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "not-an-image-id", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="immutable image ID"):
        run_test_suite(tmp_path, confirm=True, isolation="docker", sandbox_image="aurix-test:local")
    assert len(calls) == 1
    assert calls[0][:3] == ["docker", "image", "inspect"]


def test_trusted_execution_records_runtime_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "ok", ""),
    )
    result = run_test_suite(tmp_path, confirm=True)
    fingerprint = result["runtime_fingerprint"]
    assert fingerprint["python_version"]
    assert fingerprint["python_implementation"]
    assert fingerprint["system"]
    assert result["sandbox_image_id"] is None


def test_runner_accepts_only_existing_relative_test_files(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_test_suite(tmp_path, "pytest", confirm=True, test_paths=["tests/test_ok.py"])
    assert result["passed"] is True
    assert seen["command"][-1] == "tests/test_ok.py"
    with pytest.raises(ValueError, match="Invalid relative"):
        run_test_suite(tmp_path, "pytest", confirm=True, test_paths=["../outside.py"])
