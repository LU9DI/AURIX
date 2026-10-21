"""Para hunks de 'logica_nova' (sem vazamento: vocabulario so de commits anteriores):
- taxa de identificadores ja existentes no projeto
- taxa de linhas cujo 'molde' (identificadores abstraidos) ja apareceu antes.

Uso: python copy_cov.py REPO
"""

import json
import statistics
import sys

from classify import IDENT, KW, STR, classify, hunks, shape


def idents(line):
    s = STR.sub(" ", line)
    return [t for t in IDENT.findall(s) if t not in KW]


def main(repo):
    vocab, shapes = set(), set()
    pending = []  # hunks do commit atual: entram no vocabulario so depois de avaliados
    cur = None
    tot_id = known_id = n_hunks = full_known = lines = shape_seen = 0
    novel_per_hunk = []

    def commit_end():
        for _p, a in pending:
            for ln in a:
                vocab.update(idents(ln))
                shapes.add(shape(ln))
        pending.clear()

    for c, _m, p, d, a in hunks(repo, reverse=True):
        if c != cur:
            commit_end()
            cur = c
        if classify(p, d, a) == "logica_nova":
            ids = [i for ln in a for i in idents(ln)]
            nl = [ln for ln in a if len(shape(ln)) >= 12]
            if ids and vocab:
                kn = sum(1 for i in ids if i in vocab)
                tot_id += len(ids)
                known_id += kn
                n_hunks += 1
                novel_per_hunk.append(len(ids) - kn)
                full_known += kn == len(ids)
            for ln in nl:
                lines += 1
                shape_seen += shape(ln) in shapes
        pending.append((p, a))
    commit_end()
    print(
        json.dumps(
            {
                "repo": repo.rstrip("/").split("/")[-1],
                "hunks_logica_nova": n_hunks,
                "pct_identificadores_ja_conhecidos": round(100 * known_id / max(tot_id, 1), 1),
                "pct_hunks_100pct_identificadores_conhecidos": round(
                    100 * full_known / max(n_hunks, 1), 1
                ),
                "mediana_identificadores_novos_por_hunk": (
                    statistics.median(novel_per_hunk) if novel_per_hunk else None
                ),
                "pct_linhas_com_molde_ja_visto": round(100 * shape_seen / max(lines, 1), 1),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main(sys.argv[1])
