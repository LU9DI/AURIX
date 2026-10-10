import subprocess
from pathlib import Path

DEFAULT_ALLOWED = {
    ("pytest",), ("python", "-m", "pytest"), ("ruff", "check"),
    ("git", "status", "--short"), ("git", "diff", "--"),
}


def run_approved_command(workspace: Path, argv: list[str], *, timeout_seconds: int = 60,
                          allowed_prefixes: set[tuple[str, ...]] | None = None) -> dict[str, object]:
    """Run allowlisted argv without a shell. This is not a sandbox."""
    if not argv or any("\x00" in arg for arg in argv):
        raise ValueError("Invalid command")
    allowed = allowed_prefixes if allowed_prefixes is not None else DEFAULT_ALLOWED
    if not any(tuple(argv[:len(prefix)]) == prefix for prefix in allowed):
        raise PermissionError(f"Command is not on the allowlist: {argv[0]}")
    timeout_seconds = max(1, min(int(timeout_seconds), 120))
    try:
        result = subprocess.run(argv, cwd=workspace.resolve(), shell=False, text=True,
                                capture_output=True, timeout=timeout_seconds, check=False)
        return {"returncode": result.returncode, "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-12000:], "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        return {"returncode": None, "stdout": str(exc.stdout or "")[-12000:],
                "stderr": str(exc.stderr or "")[-12000:], "timed_out": True}
