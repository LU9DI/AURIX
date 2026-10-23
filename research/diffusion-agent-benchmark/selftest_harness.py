"""Gate 1: harness self-test with known-good and known-bad patches.

For each fixture: original must FAIL tests; a known-good fix must PASS; a known-bad
(plausible but wrong) fix must FAIL. Runs in disposable copies, no model involved.
"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUITE = json.loads((ROOT / "suite" / "suite.json").read_text())

PATCHES = {  # (good, bad) replacement of calculator.py body
    "fix-add-subtraction": ("def add(a: int, b: int) -> int:\n    return a + b\n",
                            "def add(a: int, b: int) -> int:\n    return a * b\n"),
    "fix-negative-absolute": ("def absolute_value(n: int) -> int:\n    return -n if n < 0 else n\n",
                              "def absolute_value(n: int) -> int:\n    return -n\n"),
    "fix-even-check": ("def is_even(n: int) -> bool:\n    return n % 2 == 0\n",
                       "def is_even(n: int) -> bool:\n    return n > 0 and n % 2 == 0\n"),
}

def run(fixture: Path, code: str | None) -> bool:
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "w"; shutil.copytree(fixture, w)
        if code is not None: (w / "calculator.py").write_text(code)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                           cwd=w, capture_output=True, text=True, timeout=60)
        return r.returncode == 0

ok = True
for case in SUITE:
    fx = ROOT / "suite" / case["fixture"]
    good, bad = PATCHES[case["id"]]
    res = {"original": run(fx, None), "good": run(fx, good), "bad": run(fx, bad)}
    expect = {"original": False, "good": True, "bad": False}
    passed = res == expect
    ok &= passed
    print(f"{case['id']:24s} {res} {'OK' if passed else 'FAIL'}")
print("GATE 1:", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
