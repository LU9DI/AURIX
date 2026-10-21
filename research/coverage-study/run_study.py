"""Run the coverage classifier and attach reproducibility metadata to each JSONL row.

Usage:
    python research/coverage-study/run_study.py OUTPUT.jsonl REPO [REPO ...]

The script is intentionally offline: it analyzes the checked-out snapshots supplied by
the caller and never clones repositories or silently changes their revisions.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


HERE = Path(__file__).resolve().parent
CLASSIFIER = HERE / "classify.py"


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
    ).stdout.strip()


def safe_origin(origin):
    """Remove URL user-info so snapshots never persist embedded credentials."""
    if not origin or "://" not in origin:
        return origin
    parsed = urlsplit(origin)
    if parsed.username is None and parsed.password is None:
        return origin
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def snapshot_metadata(repo):
    root = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
    try:
        origin = safe_origin(git(root, "remote", "get-url", "origin"))
    except subprocess.CalledProcessError:
        origin = None
    return {
        "snapshot_path": str(root),
        "origin_url": origin,
        "snapshot_commit": git(root, "rev-parse", "HEAD"),
        "is_shallow": git(root, "rev-parse", "--is-shallow-repository") == "true",
        "history_depth_commits": int(git(root, "rev-list", "--count", "HEAD")),
    }


def analyze(repo):
    metadata = snapshot_metadata(repo)
    completed = subprocess.run(
        [sys.executable, str(CLASSIFIER), str(repo)],
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
    )
    rows = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError(f"classifier must emit exactly one JSON object for {repo}")
    metrics = json.loads(rows[0])
    metrics.update(metadata)
    metrics["classifier_sha256"] = hashlib.sha256(CLASSIFIER.read_bytes()).hexdigest()
    return metrics


def main(argv):
    if len(argv) < 3:
        raise SystemExit(
            "usage: run_study.py OUTPUT.jsonl REPO [REPO ...]"
        )
    output = Path(argv[1])
    repos = argv[2:]
    # Fail before replacing output if any supplied path is not a Git repository.
    results = [analyze(repo) for repo in repos]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for row in results:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv)
