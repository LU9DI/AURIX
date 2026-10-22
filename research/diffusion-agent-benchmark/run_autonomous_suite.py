"""Run the isolated diffusion-research task suite against the configured AURIX provider.

Example:
  AURIX_PROVIDER=ollama AURIX_MODEL=qwen2.5-coder:7b python research/diffusion-agent-benchmark/run_autonomous_suite.py --confirm

This invokes a model and executes pytest in disposable copies. Trusted mode is not an OS sandbox.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurix.evaluation.autonomous import run_autonomous_benchmark
from aurix.providers.factory import create_provider


ROOT = Path(__file__).resolve().parent
SUITE = ROOT / "suite" / "suite.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true", help="confirm model calls and test execution")
    parser.add_argument("--provider", default=None, help="provider name; defaults to AURIX_PROVIDER")
    parser.add_argument("--timeout", type=int, default=30, help="test timeout per task (1-120 seconds)")
    parser.add_argument("--max-steps", type=int, default=8, help="agent step limit (2-20)")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "latest.json")
    args = parser.parse_args()

    if not args.confirm:
        parser.error("refusing to call a model or run tests without --confirm")
    provider = create_provider(args.provider)
    report = run_autonomous_benchmark(
        SUITE,
        provider,
        confirm=True,
        timeout_seconds=args.timeout,
        max_steps=args.max_steps,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
    }, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
