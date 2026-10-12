"""Bounded, read-only Git inspection tools for the AURIX agent loop."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 16_000


def _git(
    workspace: Path, args: list[str], *, timeout_seconds: int = 8
) -> subprocess.CompletedProcess[str]:
    root = workspace.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be a directory")
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "core.pager=cat",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-c",
                "diff.external=",
                *args,
            ],
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, min(int(timeout_seconds), 15)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Git inspection exceeded its time limit") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-1000:].strip()
        raise RuntimeError(detail or "Git inspection failed")
    return result


def _require_workspace_root(workspace: Path) -> Path:
    root = workspace.expanduser().resolve(strict=True)
    result = _git(root, ["rev-parse", "--show-toplevel"])
    top = Path(result.stdout.strip()).resolve()
    if top != root:
        raise PermissionError(
            "Git inspection requires the configured workspace to be the repository root"
        )
    return root


def git_status(workspace: Path) -> dict[str, Any]:
    """Return bounded porcelain status, including untracked files."""
    root = _require_workspace_root(workspace)
    result = _git(root, ["status", "--short", "--branch", "--untracked-files=normal"])
    output = result.stdout[:MAX_OUTPUT_CHARS]
    return {
        "status": "completed",
        "tool": "git_status",
        "workspace": str(root),
        "output": output,
        "truncated": len(result.stdout) > MAX_OUTPUT_CHARS,
    }


def git_diff(workspace: Path, *, staged: bool = False) -> dict[str, Any]:
    """Return bounded text diff. No external diff driver or pager is invoked."""
    if not isinstance(staged, bool):
        raise ValueError("staged must be a boolean")
    root = _require_workspace_root(workspace)
    args = ["--no-pager", "diff", "--no-ext-diff", "--no-color", "--unified=3"]
    if staged:
        args.append("--cached")
    args.extend(["--", "."])
    result = _git(root, args)
    output = result.stdout[:MAX_OUTPUT_CHARS]
    return {
        "status": "completed",
        "tool": "git_diff",
        "workspace": str(root),
        "staged": staged,
        "output": output,
        "truncated": len(result.stdout) > MAX_OUTPUT_CHARS,
    }
