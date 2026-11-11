"""Sensibilidade do estudo de cobertura a commits em massa.

Compara a fracao de linhas de codigo "deterministicas" com e sem os commits que alteram mais de N
linhas de codigo (formatacao em massa, remocao de arquivos inteiros, importacoes iniciais).

Uso: python sensitivity.py [--max-commit-lines N] REPO [REPO ...]
"""

import argparse
from collections import Counter, defaultdict

from classify import DETERMINISTIC, classify, hunks

NON_CODE = {"docs", "config_dados", "outro"}


def run(repo, limit):
    per_commit = defaultdict(Counter)
    for commit, _msg, path, dele, add in hunks(repo):
        kind = classify(path, dele, add)
        if kind not in NON_CODE:
            per_commit[commit][kind] += len(add) + len(dele)
    out = {}
    for label, keep in (("todos", lambda t: True), ("sem_em_massa", lambda t: t <= limit)):
        lines = Counter()
        n_commits = 0
        for kinds in per_commit.values():
            if keep(sum(kinds.values())):
                lines.update(kinds)
                n_commits += 1
        total = sum(lines.values()) or 1
        det = sum(v for k, v in lines.items() if k in DETERMINISTIC)
        out[label] = (round(100 * det / total, 1), total, n_commits)
    name = repo.rstrip("/").split("/")[-1]
    a, b = out["todos"], out["sem_em_massa"]
    print(
        f"{name:18} todos: {a[0]:5.1f}% de {a[1]:6} linhas | sem commits > limite: {b[0]:5.1f}% de {b[1]:6} linhas"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-commit-lines", type=int, default=1500)
    ap.add_argument("repos", nargs="+")
    args = ap.parse_args()
    for r in args.repos:
        run(r, args.max_commit_lines)
