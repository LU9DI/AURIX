import pytest

from aurix.tools.commands import run_approved_command


def test_unapproved_command_is_blocked(tmp_path):
    with pytest.raises(PermissionError):
        run_approved_command(tmp_path, ["python", "-c", "print('no')"])


def test_allowed_command_runs_without_shell(tmp_path):
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    result = run_approved_command(tmp_path, ["git", "status", "--short"])
    assert result["returncode"] == 0
