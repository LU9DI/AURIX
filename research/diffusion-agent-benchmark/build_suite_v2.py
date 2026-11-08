"""Generate suite v2 (20 new single-file bug-fix tasks + the 3 originals = 23) and self-test it.

Every spec carries a buggy body, a known-good body and a plausible-but-wrong body. `--check` verifies that
buggy FAILS, good PASSES and bad FAILS (gate 1). Synthetic, small tasks: they validate plumbing and
detect large differences, not broad coding ability.
"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent; FX = ROOT / "suite" / "fixtures"

S = []  # (id, fn, buggy, good, bad, tests, task)
def add(i, fn, sig, buggy, good, bad, tests, task):
    S.append((i, fn, sig, buggy, good, bad, tests, task))
add("clamp", "clamp", "def clamp(x, lo, hi):", "    return min(x, lo)", "    return max(lo, min(x, hi))", "    return min(x, hi)",
    "assert clamp(5,0,10)==5\nassert clamp(-3,0,10)==0\nassert clamp(99,0,10)==10", "clamp(x, lo, hi) must restrict x to the closed interval [lo, hi].")
add("reverse-words", "reverse_words", "def reverse_words(s):", "    return ' '.join(s.split())", "    return ' '.join(reversed(s.split()))", "    return s[::-1]",
    "assert reverse_words('a b c')=='c b a'\nassert reverse_words('hello')=='hello'\nassert reverse_words('one  two')=='two one'", "reverse_words(s) must reverse the order of the words, joined by single spaces.")
add("count-vowels", "count_vowels", "def count_vowels(s):", "    return sum(1 for c in s.lower() if c in 'aeio')", "    return sum(1 for c in s.lower() if c in 'aeiou')", "    return sum(1 for c in s.lower() if c.isalpha() and c not in 'aeiou')",
    "assert count_vowels('Education')==5\nassert count_vowels('xyz')==0\nassert count_vowels('AEIOU')==5", "count_vowels(s) must count a, e, i, o, u in either case.")
add("factorial", "factorial", "def factorial(n):", "    r = 1\n    for i in range(1, n):\n        r *= i\n    return r", "    r = 1\n    for i in range(1, n + 1):\n        r *= i\n    return r", "    return n",
    "assert factorial(0)==1\nassert factorial(1)==1\nassert factorial(5)==120", "factorial(n) must return n! for n >= 0.")
add("palindrome", "is_palindrome", "def is_palindrome(s):", "    return s == s[::-1]", "    t = [c.lower() for c in s if c.isalnum()]\n    return t == t[::-1]", "    return s.lower() == s.lower()[::-1]",
    "assert is_palindrome('A man, a plan, a canal: Panama')\nassert not is_palindrome('hello')\nassert is_palindrome('')", "is_palindrome(s) must ignore case and non-alphanumeric characters.")
add("fizzbuzz", "fizzbuzz", "def fizzbuzz(n):", "    if n % 3 == 0:\n        return 'Fizz'\n    if n % 5 == 0:\n        return 'Buzz'\n    if n % 15 == 0:\n        return 'FizzBuzz'\n    return str(n)",
    "    if n % 15 == 0:\n        return 'FizzBuzz'\n    if n % 3 == 0:\n        return 'Fizz'\n    if n % 5 == 0:\n        return 'Buzz'\n    return str(n)", "    if n % 3 == 0:\n        return 'Fizz'\n    if n % 5 == 0:\n        return 'Buzz'\n    return str(n)",
    "assert fizzbuzz(15)=='FizzBuzz'\nassert fizzbuzz(9)=='Fizz'\nassert fizzbuzz(10)=='Buzz'\nassert fizzbuzz(7)=='7'", "fizzbuzz(n) must return 'FizzBuzz' for multiples of 15, 'Fizz' for 3, 'Buzz' for 5, else str(n).")
add("max-of", "max_of", "def max_of(xs):", "    best = 0\n    for x in xs:\n        if x > best:\n            best = x\n    return best", "    best = xs[0]\n    for x in xs:\n        if x > best:\n            best = x\n    return best", "    return min(xs)",
    "assert max_of([1,5,3])==5\nassert max_of([-4,-2,-9])==-2", "max_of(xs) must return the largest element of a non-empty list, including all-negative lists.")
add("average", "average", "def average(xs):", "    return sum(xs) // len(xs)", "    return sum(xs) / len(xs) if xs else 0.0", "    return sum(xs) / (len(xs) + 1)",
    "assert average([1,2])==1.5\nassert average([])==0.0\nassert average([4])==4", "average(xs) must return the arithmetic mean as a float, and 0.0 for an empty list.")
add("flatten", "flatten", "def flatten(xss):", "    return xss", "    return [x for xs in xss for x in xs]", "    return [x for xs in xss for x in xs[:-1]]",
    "assert flatten([[1,2],[3]])==[1,2,3]\nassert flatten([])==[]\nassert flatten([[],[4]])==[4]", "flatten(xss) must flatten one level of nested lists, preserving order.")
add("unique-sorted", "unique_sorted", "def unique_sorted(xs):", "    return sorted(xs)", "    return sorted(set(xs))", "    return sorted(set(xs))[:-1]",
    "assert unique_sorted([3,1,3,2])==[1,2,3]\nassert unique_sorted([])==[]", "unique_sorted(xs) must return the distinct elements in ascending order.")
add("title-case", "title_case", "def title_case(s):", "    return s.upper()", "    return ' '.join(w.capitalize() for w in s.split(' '))", "    return s.capitalize()",
    "assert title_case('hello big world')=='Hello Big World'\nassert title_case('')==''", "title_case(s) must capitalize the first letter of every space-separated word and lowercase the rest.")
add("gcd", "gcd", "def gcd(a, b):", "    return a % b", "    while b:\n        a, b = b, a % b\n    return a", "    return min(a, b)",
    "assert gcd(12,18)==6\nassert gcd(7,13)==1\nassert gcd(9,0)==9", "gcd(a, b) must return the greatest common divisor of two non-negative integers.")
add("leap-year", "is_leap", "def is_leap(y):", "    return y % 4 == 0", "    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)", "    return y % 100 != 0",
    "assert is_leap(2024)\nassert not is_leap(1900)\nassert is_leap(2000)\nassert not is_leap(2023)", "is_leap(y) must follow the Gregorian leap-year rules.")
add("binary-search", "binary_search", "def binary_search(xs, t):", "    lo, hi = 0, len(xs) - 1\n    while lo < hi:\n        mid = (lo + hi) // 2\n        if xs[mid] == t:\n            return mid\n        if xs[mid] < t:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1",
    "    lo, hi = 0, len(xs) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if xs[mid] == t:\n            return mid\n        if xs[mid] < t:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1", "    return 0 if xs and xs[0] == t else -1",
    "xs=[1,3,5,7,9]\nassert [binary_search(xs,v) for v in xs]==[0,1,2,3,4]\nassert binary_search(xs,4)==-1\nassert binary_search([],1)==-1", "binary_search(xs, t) must return the index of t in a sorted list, or -1; every element, including the last, must be found.")
add("sum-digits", "sum_digits", "def sum_digits(n):", "    return sum(int(c) for c in str(n))", "    n = abs(n)\n    s = 0\n    while n:\n        s += n % 10\n        n //= 10\n    return s", "    return len(str(n))",
    "assert sum_digits(123)==6\nassert sum_digits(0)==0\nassert sum_digits(-45)==9", "sum_digits(n) must return the sum of the decimal digits of abs(n).")
add("chunk", "chunk", "def chunk(xs, n):", "    return [xs[i:i+n] for i in range(0, len(xs) - len(xs) % n, n)]", "    return [xs[i:i+n] for i in range(0, len(xs), n)]", "    return [xs]",
    "assert chunk([1,2,3,4,5],2)==[[1,2],[3,4],[5]]\nassert chunk([],3)==[]\nassert chunk([1,2],5)==[[1,2]]", "chunk(xs, n) must split xs into consecutive pieces of size n, keeping the shorter last piece.")
add("merge-dicts", "merge_dicts", "def merge_dicts(a, b):", "    a.update(b)", "    return {**a, **b}", "    return {**b}",
    "a={'x':1}\nr=merge_dicts(a,{'y':2})\nassert r=={'x':1,'y':2}\nassert a=={'x':1}\nassert merge_dicts({'x':1},{'x':3})=={'x':3}", "merge_dicts(a, b) must return a new dict with b's values overriding a's, without mutating a.")
add("c-to-f", "c_to_f", "def c_to_f(c):", "    return c * 9 / 5", "    return c * 9 / 5 + 32", "    return c * 5 / 9 + 32",
    "assert c_to_f(0)==32\nassert c_to_f(100)==212\nassert c_to_f(-40)==-40", "c_to_f(c) must convert Celsius to Fahrenheit.")
add("second-largest", "second_largest", "def second_largest(xs):", "    return sorted(xs)[-2]", "    return sorted(set(xs))[-2]", "    return max(xs)",
    "assert second_largest([1,5,3])==3\nassert second_largest([5,5,4])==4", "second_largest(xs) must return the second largest distinct value.")
add("strip-prefix", "strip_prefix", "def strip_prefix(s, p):", "    return s.lstrip(p)", "    return s[len(p):] if s.startswith(p) else s", "    return s.replace(p, '')",
    "assert strip_prefix('foobar','foo')=='bar'\nassert strip_prefix('aab','a')=='ab'\nassert strip_prefix('xyz','q')=='xyz'", "strip_prefix(s, p) must remove p from the start of s exactly once, only if s starts with p.")

def code(sig, body): return f"{sig}\n{body}\n"

def build():
    suite = json.loads((ROOT / "suite" / "suite.json").read_text())
    suite = [c for c in suite if c["id"].startswith("fix-") and c["fixture"].count("/") == 1 and "v2/" not in c["fixture"]]
    for i, fn, sig, buggy, good, bad, tests, task in S:
        d = FX / "v2" / i; d.mkdir(parents=True, exist_ok=True)
        (d / "calculator.py").write_text(code(sig, buggy))
        (d / "test_calculator.py").write_text(f"from calculator import {fn}\n\n\ndef test_{fn}():\n" + "".join(f"    {l}\n" for l in tests.split("\n")))
        suite.append({"id": f"fix-{i}", "fixture": f"fixtures/v2/{i}", "task": f"Fix the bug in calculator.py: {task} Inspect the tests, propose the smallest unified diff using propose_patch, and do not claim success unless verification passes.",
                      "expect_baseline_passed": False, "expect_candidate_passed": True})
    (ROOT / "suite" / "suite_v2.json").write_text(json.dumps(suite, indent=2) + "\n")
    return len(suite)

def run(fixture, text):
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "w"; shutil.copytree(fixture, w)
        if text is not None: (w / "calculator.py").write_text(text)
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=w, capture_output=True, timeout=60).returncode == 0

def check():
    ok = True
    for i, fn, sig, buggy, good, bad, tests, task in S:
        fx = FX / "v2" / i; r = (run(fx, None), run(fx, code(sig, good)), run(fx, code(sig, bad)))
        good_ = r == (False, True, False); ok &= good_
        print(f"{i:16s} original={r[0]!s:5} good={r[1]!s:5} bad={r[2]!s:5} {'OK' if good_ else 'FAIL'}")
    print("GATE 1 (v2):", "PASS" if ok else "FAIL"); return ok

if __name__ == "__main__":
    n = build(); print("suite_v2.json cases:", n)
    sys.exit(0 if check() else 1)
