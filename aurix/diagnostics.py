"""Read-only readiness checks for an AURIX installation."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_diagnostics(workspace: Path | str = ".", *, probe_provider: bool = False,
                    provider: Any | None = None) -> dict[str, Any]:
    """Inspect local readiness without printing environment values or secrets.

    A live provider probe is opt-in because it can consume model compute or API
    credits. Probe output is reduced to a boolean/status and never includes the
    model response or endpoint credentials.
    """
    root = Path(workspace).expanduser().resolve()
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    add("python", "ok" if sys.version_info >= (3, 11) else "fail",
        f"Python {sys.version_info.major}.{sys.version_info.minor}; requires 3.11+")
    add("workspace", "ok" if root.is_dir() else "fail",
        "Workspace directory is available" if root.is_dir() else "Workspace directory does not exist")
    add("git", "ok" if shutil.which("git") else "missing",
        "Git executable found" if shutil.which("git") else "Git executable not found")

    if root.is_dir() and shutil.which("git"):
        git = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root,
                             capture_output=True, text=True, timeout=5, check=False)
        add("git_repository", "ok" if git.returncode == 0 else "warning",
            "Workspace is inside a Git repository" if git.returncode == 0 else "Workspace is not inside a Git repository")
    else:
        add("git_repository", "skipped", "Requires an existing workspace and Git")

    for module, label in (("httpx", "httpx dependency"), ("dotenv", "python-dotenv dependency"),
                          ("pytest", "pytest test runner"), ("ruff", "ruff linter")):
        present = importlib.util.find_spec(module) is not None
        optional = module in {"pytest", "ruff"}
        add(label, "ok" if present else ("warning" if optional else "fail"),
            f"{module} is available" if present else f"{module} is not installed")

    engine = os.getenv("AURIX_PROVIDER", "ollama").strip().lower()
    default_model = "qwen2.5-coder:7b" if engine == "ollama" else "local-model"
    default_url = "http://localhost:11434" if engine == "ollama" else "http://localhost:1234/v1"
    model = os.getenv("AURIX_MODEL", default_model).strip()
    base_url = os.getenv("AURIX_BASE_URL", default_url).strip()
    supported = engine in {"openai-compatible", "openai_compatible", "compatible", "ollama"}
    add("provider_configuration", "ok" if supported and bool(model) and bool(base_url) else "fail",
        f"Provider type: {engine or '(empty)'}; model/base URL configured: {bool(model) and bool(base_url)}")
    add("neon_configuration", "configured" if os.getenv("DATABASE_URL", "").strip() else "optional",
        "DATABASE_URL is configured (value hidden)" if os.getenv("DATABASE_URL", "").strip()
        else "Neon/Postgres is optional; SQLite can be used instead")

    if probe_provider:
        if provider is None:
            add("provider_probe", "fail", "No provider instance was supplied")
        else:
            try:
                response = provider.generate("Reply with exactly AURIX_OK.",
                                             system="This is a connectivity check. Reply exactly AURIX_OK.")
                success = "AURIX_OK" in response
                add("provider_probe", "ok" if success else "warning",
                    "Provider returned the expected marker" if success else "Provider responded, but marker was not found")
            except Exception as exc:  # Do not leak exception text; it may contain endpoint details.
                add("provider_probe", "fail", f"Provider request failed ({type(exc).__name__}); details hidden")
    else:
        add("provider_probe", "not_run", "Use --probe-provider to make a live model request")

    failed = sum(item["status"] == "fail" for item in checks)
    warnings = sum(item["status"] in {"warning", "missing"} for item in checks)
    return {"status": "fail" if failed else ("warning" if warnings else "ready"),
            "workspace": str(root), "checks": checks,
            "summary": {"total": len(checks), "failed": failed, "warnings": warnings}}
