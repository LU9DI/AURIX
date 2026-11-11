"""O conhecimento previo (corpus generico de terceiros) reduz os bits do codigo novo do projeto?

A: so o passado do repo | B: so corpus generico | C: generico + passado do repo. Teste: ultimo bloco
cronologico do fluxo de codigo novo (ver chrono_bits.py). n-gram de bytes, ordem 10.
Corpus generico: "ts" = JS/TS de node_modules locais (de terceiros); "py" = stdlib e dist-packages.
Depende de aurix.providers.ngram (PR #7).

Uso: python prior_corpus.py REPO ts|py [BYTES_DO_CORPUS_GENERICO]
"""

import os
import sys
import time
from collections import defaultdict

from aurix.providers.ngram import NgramModel
from chrono_bits import MAX_COMMIT_LINES, SKIP, per_byte_bits
from classify import CODE, classify, hunks


def stream(repo, nblocks=5):
    size = defaultdict(int)
    for c, _m, p, _d, a in hunks(repo):
        if p.endswith(CODE):
            size[c] += len(a)
    chunks = []
    for c, _m, p, d, a in hunks(repo, reverse=True):
        if not p.endswith(CODE) or classify(p, d, a) in SKIP:
            continue
        if size[c] > MAX_COMMIT_LINES or not "".join(a).strip():
            continue
        chunks.append("\n".join(a) + "\n")
    raw = "".join(chunks).encode()
    cuts = (
        [0] + [raw.find(b"\n", len(raw) * b // nblocks) + 1 for b in range(1, nblocks)] + [len(raw)]
    )
    return raw[: cuts[nblocks - 1]], raw[cuts[nblocks - 1] : cuts[nblocks]][:200_000]


def generic(roots, exts, cap):
    per_root = cap // len(roots)
    seen = set()
    out = []
    for root in roots:
        total = 0
        for dp, dn, fn in os.walk(root):
            dn[:] = sorted(
                d
                for d in dn
                if d not in {".git", "__pycache__", "test", "tests", "node_modules"} or dp == root
            )
            for n in sorted(fn):
                if not n.endswith(exts) or n.endswith((".min.js", ".d.ts", ".map")):
                    continue
                p = os.path.join(dp, n)
                try:
                    if os.path.getsize(p) > 200_000:
                        continue
                    b = open(p, "rb").read()
                    b.decode("utf-8")
                except Exception:
                    continue
                if not b or b in seen or len(b) / (b.count(b"\n") + 1) > 200:
                    continue
                if total + len(b) > per_root:
                    break
                seen.add(b)
                out.append(b)
                total += len(b)
            if total >= per_root:
                break
    return b"\n\x00\n".join(out)


def bpb(model, test):
    return float(per_byte_bits(model, test).sum() / len(test))


repo, kind = sys.argv[1], sys.argv[2]
cap = int(sys.argv[3]) if len(sys.argv) > 3 else 12_000_000
past, test = stream(f"/home/claude/{repo}")
if kind == "ts":
    roots = [
        r
        for r in (
            "/home/claude/backend/node_modules",
            "/home/claude/saas-reputacao-ia/frontend/node_modules",
            "/home/claude/tax-platform-br/node_modules",
        )
        if not r.startswith(f"/home/claude/{repo}/")
    ]
    gen = generic(roots, (".js", ".ts", ".mjs", ".cjs"), cap)
else:
    gen = generic(["/usr/lib/python3.13", "/usr/local/lib/python3.13/dist-packages"], (".py",), cap)
print(
    f"{repo}: passado={len(past) // 1000}KB teste={len(test) // 1000}KB generico={len(gen) // 1000}KB",
    flush=True,
)
for label, data in (
    ("A repo-passado", past),
    ("B generico", gen),
    ("C generico+passado", gen + b"\n\x00\n" + past),
):
    t = time.time()
    m = NgramModel(data, order=10)
    print(f"  {label:20} BPB={bpb(m, test):.2f}  (construcao {time.time() - t:.0f}s)", flush=True)
