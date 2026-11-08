"""Run the isolated diffusion-research task suite against the configured AURIX provider.

Example:
  AURIX_PROVIDER=ollama AURIX_MODEL=qwen2.5-coder:7b \
    python research/diffusion-agent-benchmark/run_autonomous_suite.py --confirm

The default suite is suite_v2.json (23 tasks). Pass ``--suite`` explicitly when
running the original three-task smoke suite. This invokes a model and executes
pytest in disposable copies. Trusted mode is not an OS sandbox.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aurix.evaluation.autonomous import run_autonomous_benchmark  # noqa: E402
from aurix.providers.factory import create_provider  # noqa: E402

SUITE = ROOT / "suite" / "suite_v2.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true", help="confirm model calls and test execution")
    parser.add_argument("--provider", default=None, help="provider name; defaults to AURIX_PROVIDER")
    parser.add_argument(
        "--suite",
        type=Path,
        default=SUITE,
        help="suite JSON (default: suite/suite_v2.json, 23 tasks; use suite.json for the 3-task smoke)",
    )
    parser.add_argument("--timeout", type=int, default=30, help="test timeout per task (1-120 seconds)")
    parser.add_argument("--max-steps", type=int, default=8, help="agent step limit (2-20)")
    parser.add_argument("--isolation", choices=("trusted", "docker"), default="trusted")
    parser.add_argument("--sandbox-image", default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "latest.json")
    parser.add_argument(
        "--protocol-diagnostics",
        action="store_true",
        help="write opt-in redacted raw protocol responses to a temporary directory",
    )
    args = parser.parse_args()

    if not args.confirm:
        parser.error("refusing to call a model or run tests without --confirm")
    if args.isolation == "docker" and not args.sandbox_image:
        parser.error("--isolation docker requires --sandbox-image")
    if args.isolation == "trusted" and args.sandbox_image:
        parser.error("--sandbox-image requires --isolation docker")
    suite = args.suite.expanduser().resolve()
    if not suite.is_file():
        parser.error(f"suite does not exist: {suite}")

    if args.protocol_diagnostics:
        os.environ["AURIX_PROTOCOL_DIAGNOSTICS"] = "1"

    provider = create_provider(args.provider)
    report = run_autonomous_benchmark(
        suite,
        provider,
        confirm=True,
        timeout_seconds=args.timeout,
        max_steps=args.max_steps,
        isolation=args.isolation,
        sandbox_image=args.sandbox_image,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "report": str(args.output),
        "benchmark": report["benchmark"],
        "cases": report["cases"],
        "passed": report["passed"],
        "failed": report["failed"],
        "pass_rate": report["pass_rate"],
        "duration_ms": report["duration_ms"],
        "provider_class": report["metadata"]["provider_class"],
        "suite_sha256": report["metadata"]["suite_sha256"],
        "isolation": report["metadata"]["isolation"],
        "generation_settings": report["metadata"]["generation_settings"],
        "protocol_diagnostics_enabled": os.getenv("AURIX_PROTOCOL_DIAGNOSTICS", "0"),
        "protocol_diagnostics_dir": os.getenv("AURIX_PROTOCOL_DIAGNOSTICS_DIR", ""),
    }, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
