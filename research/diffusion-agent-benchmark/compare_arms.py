"""Stage C driver: compare two decoding arms (e.g. autoregressive vs diffusion) on the suite.

Each arm is an OpenAI-compatible endpoint (or ollama). Verified pass rate and wall-clock are
counted per attempt, failures stay in the denominator. Pre-registered rule: arm B is
non-inferior to arm A if the lower bound of (pass_B - pass_A) 95% bootstrap CI >= -5 points.

  python compare_arms.py --confirm --repeats 10 \
    --arm ar,openai-compatible,http://localhost:1234/v1,qwen2.5-coder-7b \
    --arm diff,openai-compatible,http://localhost:1235/v1,<diffusion-model>

VERIFY the backend of the 'diff' arm really does iterative denoising and record its step budget
in --note; a chat API can hide the decoding algorithm. Use --stub to test the plumbing offline.
"""
from __future__ import annotations
import argparse, json, platform, random, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUITE = ROOT / "suite" / "suite.json"

class StubProvider:  # plumbing test only: never solves anything
    def generate(self, prompt, *, system=""): return "no patch"

def make_provider(kind, url, model):
    from aurix.providers.ollama import OllamaProvider
    from aurix.providers.openai_compatible import OpenAICompatibleProvider
    if kind == "stub": return StubProvider()
    if kind == "ollama": return OllamaProvider(model=model) if model else OllamaProvider()
    return OpenAICompatibleProvider(model=model, base_url=url)

def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 1.0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); w = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - w) / d, (c + w) / d)

def run_arm(spec, repeats, timeout, max_steps, suite=SUITE):
    from aurix.evaluation.autonomous import run_autonomous_benchmark
    name, kind, url, model = (spec.split(",") + ["", "", ""])[:4]
    prov = make_provider(kind, url, model); rows = []
    for r in range(repeats):
        t0 = time.perf_counter()
        rep = run_autonomous_benchmark(suite, prov, confirm=True, timeout_seconds=timeout, max_steps=max_steps)
        wall = time.perf_counter() - t0
        per = rep.get("results") or rep.get("cases_detail") or []
        rows.append({"arm": name, "rep": r, "cases": rep["cases"], "passed": rep["passed"], "wall_s": wall,
                     "suite_sha256": rep["metadata"]["suite_sha256"]})
    return name, rows

def bootstrap_diff(a, b, n=5000, seed=0):  # a,b: per-attempt pass lists (task-level)
    rnd = random.Random(seed); ds = []
    for _ in range(n):
        ra = [rnd.choice(a) for _ in a]; rb = [rnd.choice(b) for _ in b]
        ds.append(sum(rb) / len(rb) - sum(ra) / len(ra))
    ds.sort(); return ds[int(.025 * n)], ds[int(.975 * n)]

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", action="append", required=True, help="name,kind,base_url,model (kind: openai-compatible|ollama|stub)")
    ap.add_argument("--repeats", type=int, default=5); ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--max-steps", type=int, default=8); ap.add_argument("--note", default=""); ap.add_argument("--suite", type=Path, default=SUITE, help="e.g. suite/suite_v2.json (23 tasks)")
    ap.add_argument("--margin", type=float, default=0.05); ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--output", type=Path, default=ROOT / "results" / "compare_arms.json")
    a = ap.parse_args()
    if not a.confirm: ap.error("refusing to call models / run tests without --confirm")
    if len(a.arm) != 2: ap.error("exactly two --arm (A = baseline first, B = candidate second)")
    arms = dict(run_arm(s, a.repeats, a.timeout, a.max_steps, a.suite) for s in a.arm)
    (na, ra), (nb, rb) = list(arms.items())
    out = {"arms": {}, "env": {"python": sys.version.split()[0], "platform": platform.platform(), "note": a.note},
           "margin": a.margin, "raw": ra + rb}
    pl = {}
    for n, rows in arms.items():
        k = sum(r["passed"] for r in rows); N = sum(r["cases"] for r in rows); w = sorted(r["wall_s"] for r in rows)
        pl[n] = [1] * k + [0] * (N - k)
        out["arms"][n] = {"attempts": N, "passed": k, "pass_rate": k / N, "wilson95": wilson(k, N),
                          "wall_median_s": statistics.median(w), "wall_p90_s": w[max(0, int(.9 * len(w)) - 1)]}
    lo, hi = bootstrap_diff(pl[na], pl[nb])
    out["pass_diff_B_minus_A_ci95"] = [lo, hi]
    # Guard: with a baseline that solves nothing, or too few attempts, the CI says nothing.
    N0 = out["arms"][na]["attempts"]
    if out["arms"][na]["passed"] == 0 or N0 < 30:
        out["non_inferior"] = "inconclusive (baseline passes 0 or fewer than 30 attempts per arm)"
    else:
        out["non_inferior"] = lo >= -a.margin
    out["latency_ratio_B_over_A"] = out["arms"][nb]["wall_median_s"] / max(out["arms"][na]["wall_median_s"], 1e-9)
    a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(json.dumps(out, indent=2))
    print(json.dumps({k: out[k] for k in ("arms", "pass_diff_B_minus_A_ci95", "non_inferior", "latency_ratio_B_over_A")}, indent=2))

if __name__ == "__main__": main()
