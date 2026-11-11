"""Corpus de codigo dos repos de Lucas, sem duplicatas exatas, split por arquivo."""

import hashlib
import subprocess
import random

REPOS = [
    "aurix",
    "aegis",
    "zion",
    "tax-platform-br",
    "shopping-agent",
    "business-automation",
    "ai-agent-marketplace",
]
EXT = (".py", ".js", ".ts")
SKIP = (
    "node_modules",
    "egg-info",
    "backup",
    "AURIX-backup-work",
    ".d.ts",
    "package-lock",
    "recovery/",
)


def files():
    seen_full, seen_head, out = set(), set(), []
    for r in REPOS:
        ls = subprocess.run(
            ["git", "-C", f"/home/claude/{r}", "ls-files"], capture_output=True, text=True
        ).stdout.split("\n")
        for p in ls:
            if not p.endswith(EXT) or any(s in p for s in SKIP):
                continue
            try:
                b = open(f"/home/claude/{r}/{p}", "rb").read()
            except Exception:
                continue
            if len(b) < 400 or len(b) > 300_000:
                continue
            try:
                b.decode("utf-8")
            except Exception:
                continue
            h, hh = hashlib.sha256(b).hexdigest(), hashlib.sha256(b[:1500]).hexdigest()
            if h in seen_full or hh in seen_head:
                continue  # tira copias e quase-copias (fundacao compartilhada)
            seen_full.add(h)
            seen_head.add(hh)
            out.append((r, p, b))
    return out


def split(seed=0):
    import os
    import pickle

    snap = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus_frozen.pkl")
    fs = pickle.load(open(snap, "rb")) if os.path.exists(snap) else files()
    rnd = random.Random(seed)
    rnd.shuffle(fs)
    n = len(fs)
    nv = max(1, n // 10)
    val, train = fs[:nv], fs[nv:]
    return train, val


if __name__ == "__main__":
    tr, va = split()
    print("arquivos treino", len(tr), "val", len(va))
    print("bytes treino", sum(len(b) for _, _, b in tr), "val", sum(len(b) for _, _, b in va))
