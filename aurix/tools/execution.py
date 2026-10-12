"""Explicitly approved, bounded test execution for trusted workspaces or Docker sandboxes.

The default trusted mode is defense-in-depth only. Docker mode requires a locally
available, operator-selected image and fails closed; it never pulls images or falls
back to host execution. The image must already contain the project's test tools/deps.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

TestSuite = Literal["pytest", "ruff"]
IsolationMode = Literal["trusted", "docker"]
_MAX_OUTPUT_CHARS = 20_000
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")


def _safe_environment() -> dict[str, str]:
    """Pass only basic runtime variables; drop common credentials and app config."""
    keep = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_NO_INPUT"] = "1"
    # Honor an explicit operator choice for deterministic/offline pytest runs.
    # By default pytest plugin autoload remains unchanged for project compatibility.
    if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1":
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def _docker_command(
    root: Path,
    suite: TestSuite,
    image: str,
    container_name: str,
    test_paths: Sequence[str] | None = None,
) -> list[str]:
    """Build a network-disabled, read-only-root Docker invocation with one writable mount."""
    if not isinstance(image, str) or not _IMAGE_RE.fullmatch(image) or image.startswith("-"):
        raise ValueError(
            "Invalid Docker image reference; provide a simple operator-controlled image name"
        )
    if ".." in image or any(char.isspace() for char in image):
        raise ValueError("Invalid Docker image reference")
    command = (
        ["python", "-m", "pytest", "-q", *(test_paths or [])]
        if suite == "pytest"
        else ["python", "-m", "ruff", "check", "."]
    )
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--pull=never",
        "--network=none",
        "--read-only",
        "--user=65532:65532",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=128",
        "--memory=2g",
        "--cpus=2",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "--mount",
        f"type=bind,src={root},dst=/workspace,readonly",
        "--workdir",
        "/workspace",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONIOENCODING=utf-8",
        "--env",
        "HOME=/tmp",
        "--env",
        "TMPDIR=/tmp",
        image,
        *command,
    ]


def run_test_suite(
    workspace: Path | str,
    suite: TestSuite = "pytest",
    *,
    confirm: bool = False,
    timeout_seconds: int = 120,
    isolation: IsolationMode = "trusted",
    sandbox_image: str | None = None,
    test_paths: Sequence[str] | None = None,
) -> dict[str, object]:
    """Run fixed test commands after explicit approval.

    ``trusted`` executes on the host and is not a sandbox. ``docker`` uses an
    already-present image, disables networking, drops Linux capabilities, makes
    the container root filesystem read-only, and mounts only the workspace. It
    still exposes the mounted workspace read/write and is not a perfect security
    boundary; use a dedicated daemon and operator-reviewed image for hostile code.
    """
    if not confirm:
        raise PermissionError("Explicit confirmation is required to execute tests")
    if suite not in {"pytest", "ruff"}:
        raise ValueError("Unsupported test suite; choose 'pytest' or 'ruff'")
    if test_paths is not None:
        if suite != "pytest" or not isinstance(test_paths, (list, tuple)) or not test_paths:
            raise ValueError("test_paths must be a non-empty list for pytest")
        for item in test_paths:
            if (
                not isinstance(item, str)
                or not item
                or Path(item).is_absolute()
                or ".." in Path(item).parts
                or "\\" in item
            ):
                raise ValueError("Invalid relative test path")
    if isolation not in {"trusted", "docker"}:
        raise ValueError("Unsupported isolation mode; choose 'trusted' or 'docker'")
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be a directory")
    timeout = max(1, min(int(timeout_seconds), 120))
    if isolation == "docker":
        if not sandbox_image:
            raise ValueError(
                "Docker isolation requires an explicit --sandbox-image already available locally"
            )
        container_name = f"aurix-test-{uuid.uuid4().hex[:16]}"
        # Resolve the operator-provided tag to an immutable local image ID, then run by ID.
        # This avoids a mutable tag being retargeted between inspection and container start.
        # Fail closed: no implicit docker pull, and no fallback to host execution.
        try:
            image_check = subprocess.run(
                ["docker", "image", "inspect", "--format={{.Id}}", sandbox_image],
                env=_safe_environment(),
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=10,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Docker CLI is unavailable; sandbox execution refused without host fallback"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Timed out checking the local Docker image; sandbox execution refused"
            ) from exc
        image_id = image_check.stdout.strip()
        if image_check.returncode != 0:
            raise RuntimeError(
                "Sandbox image is not available locally; pull/build it manually and retry"
            )
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise RuntimeError(
                "Docker did not return a valid immutable image ID; refusing sandbox execution"
            )
        command = _docker_command(root, suite, image_id, container_name, test_paths)
        security_note = (
            "Docker isolation enabled using the inspected immutable image ID: network disabled, "
            "container root filesystem read-only, "
            "capabilities dropped, resource limits applied, workspace mounted writable. "
            "Image dependencies must be preinstalled; no image pull or host fallback occurs."
        )
    else:
        container_name = None
        image_id = None
        command = (
            [sys.executable, "-m", "pytest", "-q", *(test_paths or [])]
            if suite == "pytest"
            else [sys.executable, "-m", "ruff", "check", "."]
        )
        security_note = "Trusted workspace only; this runner is not a sandbox."

    if test_paths is not None:
        for relative in test_paths:
            original = root / relative
            if original.is_symlink():
                raise ValueError("Test path must not be a symlink")
            candidate = original.resolve(strict=True)
            if root not in candidate.parents or not candidate.is_file():
                raise ValueError("Test path must be an existing regular file inside the workspace")
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=root if isolation == "trusted" else None,
            env=_safe_environment(),
            shell=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "suite": suite,
            "isolation": isolation,
            "sandbox_image": sandbox_image if isolation == "docker" else None,
            "sandbox_image_id": image_id,
            "runtime_fingerprint": {
                "python_version": platform.python_version(),
                "python_implementation": platform.python_implementation(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
            "command": command,
            "returncode": result.returncode,
            "passed": result.returncode == 0,
            "timed_out": False,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "stdout": result.stdout[-_MAX_OUTPUT_CHARS:],
            "stderr": result.stderr[-_MAX_OUTPUT_CHARS:],
            "output_truncated": len(result.stdout) > _MAX_OUTPUT_CHARS
            or len(result.stderr) > _MAX_OUTPUT_CHARS,
            "security_note": security_note,
        }
    except FileNotFoundError as exc:
        if isolation == "docker":
            raise RuntimeError(
                "Docker CLI is unavailable; sandbox execution refused without host fallback"
            ) from exc
        raise
    except subprocess.TimeoutExpired as exc:
        if isolation == "docker" and container_name:
            # A timed-out Docker client can leave its container running; force-remove it.
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    env=_safe_environment(),
                    shell=False,
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass

        def tail(value: str | bytes | None) -> str:
            if value is None:
                return ""
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            return value[-_MAX_OUTPUT_CHARS:]

        return {
            "suite": suite,
            "isolation": isolation,
            "sandbox_image": sandbox_image if isolation == "docker" else None,
            "sandbox_image_id": image_id,
            "runtime_fingerprint": {
                "python_version": platform.python_version(),
                "python_implementation": platform.python_implementation(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
            "command": command,
            "returncode": None,
            "passed": False,
            "timed_out": True,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "stdout": tail(exc.stdout),
            "stderr": tail(exc.stderr),
            "output_truncated": True,
            "security_note": security_note,
        }
