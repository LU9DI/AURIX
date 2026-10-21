"""Quanto de uma linha nova ja existia no projeto? (reuso causal, sem modelo, sem GPU)

Para cada linha adicionada em hunk de "logica nova" (linhas nao triviais, arquivos de codigo):
  exata          a mesma linha (sem espacos nas pontas) ja existia
  molde          alguma linha com a mesma forma (identificadores/literais abstraidos) ja existia
  molde+campos   um dos 3 moldes mais recentes, com cada campo (identificador/literal) igual ao do molde
                 ou entre os k tokens mais recentes do mesmo arquivo
  teto-arquivo / teto-repo   idem, mas aceitando qualquer token ja visto no arquivo / no repo

Por padrao o "ja existia" so conta commits ANTERIORES (o passado do projeto). Com --within-commit
tambem conta linhas anteriores do proprio commit (auto-copia), o que infla o reuso.

Commits em massa (mais de --max-commit-lines linhas de codigo adicionadas, p.ex. importacao inicial
de um clone raso) continuam alimentando o passado, mas nao entram na avaliacao: nao ha "passado" para eles.

Uso: python reuse.py [--within-commit] [--max-commit-lines N] REPO [REPO ...]
"""

import argparse
from collections import OrderedDict, defaultdict
from itertools import islice

from classify import CODE, KW, TOKEN, classify, hunks, shape

KS = (1, 5, 20)


def slots_of(line):
    out = []
    for s, n, ident, _ws, _other in TOKEN.findall(line):
        if s or n or (ident and ident not in KW):
            out.append(s or n or ident)
    return out


def run(repo, within_commit, max_commit_lines):
    size = defaultdict(int)
    for commit, _msg, path, _dele, add in hunks(repo):
        if path.endswith(CODE):
            size[commit] += len(add)
    seen_exact = set()
    shape_idx = defaultdict(list)
    hist = defaultdict(OrderedDict)
    gset = set()
    pending = []

    def learn(path, s, sh, sl):
        seen_exact.add(s)
        shape_idx[sh] = (shape_idx[sh] + [sl])[-3:]
        h = hist[path]
        for v in sl:
            h[v] = None
            h.move_to_end(v)
            gset.add(v)

    def flush():
        for item in pending:
            learn(*item)
        pending.clear()

    c = {"linhas": 0, "exata": 0, "molde": 0, "tem_molde_compativel": 0, "teto_arquivo": 0}
    c.update({"teto_repo": 0, **{f"k{k}": 0 for k in KS}})
    cur = None
    for commit, _msg, path, dele, add in hunks(repo, reverse=True):
        if commit != cur:
            flush()
            cur = commit
        if not path.endswith(CODE):
            continue
        kind = classify(path, dele, add)
        h = hist[path]
        for ln in add:
            s = ln.strip()
            if len(s) < 12:
                continue
            sh, sl = shape(ln), slots_of(ln)
            if kind == "logica_nova" and size[commit] <= max_commit_lines:
                c["linhas"] += 1
                c["exata"] += s in seen_exact
                c["molde"] += sh in shape_idx
                ts = [t for t in shape_idx.get(sh, []) if len(t) == len(sl)]
                if ts:
                    c["tem_molde_compativel"] += 1
                    for k in KS:
                        cand = set(islice(reversed(h), k))
                        c[f"k{k}"] += any(
                            all(t[j] == v or v in cand for j, v in enumerate(sl)) for t in ts
                        )
                    c["teto_arquivo"] += any(
                        all(t[j] == v or v in h for j, v in enumerate(sl)) for t in ts
                    )
                    c["teto_repo"] += any(
                        all(t[j] == v or v in gset for j, v in enumerate(sl)) for t in ts
                    )
            if within_commit:
                learn(path, s, sh, sl)
            else:
                pending.append((path, s, sh, sl))
    n = c["linhas"] or 1
    pct = {k: round(100 * v / n, 1) for k, v in c.items() if k != "linhas"}
    print(f"{repo.rstrip('/').split('/')[-1]:18} linhas={c['linhas']:6} {pct}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--within-commit", action="store_true")
    ap.add_argument("--max-commit-lines", type=int, default=1500)
    ap.add_argument("repos", nargs="+")
    args = ap.parse_args()
    for r in args.repos:
        run(r, args.within_commit, args.max_commit_lines)
