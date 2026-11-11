"""Quanto custa, em bits, o codigo novo -- e onde esta a informacao: estrutura ou conteudo?

O fluxo cronologico das linhas adicionadas (codigo; sem reformatacao/docs/config; sem commits em massa)
e dividido em 5 blocos. Para o bloco i, um n-gram de bytes (ordem 10) e treinado so nos blocos < i e
mede bits/byte no bloco i (causal). Cada byte do teste e atribuido a CONTEUDO (identificador que nao e
palavra-chave, string, numero) ou ESTRUTURA (palavras-chave, pontuacao, espacos). A fracao dos bits gasta
em ESTRUTURA e o teto do que uma linguagem de operacoes poderia economizar, mesmo que a estrutura
custasse zero bits. Depende de aurix.providers.ngram (PR #7).

Uso: python chrono_bits.py REPO [REPO ...]
"""

import sys
from collections import defaultdict

import numpy as np
from classify import CODE, KW, TOKEN, classify, hunks

try:
    from aurix.providers.ngram import NgramModel
except ImportError:  # pragma: no cover
    sys.exit("precisa de aurix.providers.ngram (PR #7 do AURIX)")

SKIP = {"formatacao", "docs", "config_dados", "outro"}
MAX_COMMIT_LINES = 1500


def per_byte_bits(model, data):
    """-log2 P(byte | contexto) para cada byte de data (mesma conta de NgramModel.bits_per_byte)."""
    x = np.frombuffer(data, dtype=np.uint8)
    xb = x.astype(np.uint64)
    p = np.full(len(x), 1.0 / 256.0)
    for k in range(model.order + 1):
        uniq, counts, uctx, totals, distinct = model._tables[k]
        ctx = model._contexts(x, k)
        i = np.searchsorted(uctx, ctx)
        i[i >= len(uctx)] = 0
        seen = uctx[i] == ctx
        key = ctx * np.uint64(256) + xb
        j = np.searchsorted(uniq, key)
        j[j >= len(uniq)] = 0
        cc = np.where(uniq[j] == key, counts[j], 0).astype(float)
        total = np.where(seen, totals[i], 1.0)
        n1 = np.where(seen, distinct[i], 0.0)
        d = model.discounts[k]
        pk = np.maximum(cc - d, 0.0) / total + (d * n1 / total) * p
        p = np.where(seen, pk, p)
    return -np.log2(p)


def content_mask(text):
    mask = np.zeros(len(text.encode()), dtype=bool)
    pos = 0
    for s, n, ident, ws, other in TOKEN.findall(text):
        tok = s or n or ident or ws or other
        n_bytes = len(tok.encode())
        if s or n or (ident and ident not in KW):
            mask[pos : pos + n_bytes] = True
        pos += n_bytes
    return mask


def run(repo, nblocks=5):
    size = defaultdict(int)
    for commit, _m, path, _d, add in hunks(repo):
        if path.endswith(CODE):
            size[commit] += len(add)
    chunks = []
    for commit, _m, path, dele, add in hunks(repo, reverse=True):
        if not path.endswith(CODE) or classify(path, dele, add) in SKIP:
            continue
        if size[commit] > MAX_COMMIT_LINES or not "".join(add).strip():
            continue
        chunks.append("\n".join(add) + "\n")
    raw = "".join(chunks).encode()
    cuts = [0] + [raw.find(b"\n", len(raw) * b // nblocks) + 1 for b in range(1, nblocks)]
    cuts.append(len(raw))
    out = [f"{repo.rstrip('/').split('/')[-1]} total={len(raw) // 1000}KB"]
    tot_bits = tot_struct = 0.0
    tot_bytes = 0
    for i in range(1, nblocks):
        train = raw[: cuts[i]][-2_000_000:]
        test = raw[cuts[i] : cuts[i + 1]][:200_000]
        if len(train) < 20_000 or len(test) < 5_000:
            continue
        bits = per_byte_bits(NgramModel(train, order=10), test)
        mask = content_mask(test.decode("utf-8", errors="ignore"))
        mask = np.resize(mask, len(bits)) if len(mask) != len(bits) else mask
        sb, tb = float(bits[~mask].sum()), float(bits.sum())
        tot_bits += tb
        tot_struct += sb
        tot_bytes += len(test)
        out.append(
            f"   bloco {i}: passado={len(train) // 1000:5d}KB  BPB={tb / len(test):.2f}"
            f"  bits em estrutura={100 * sb / tb:4.1f}%  bytes em estrutura={100 * (~mask).mean():4.1f}%"
        )
    if tot_bits:
        out.append(
            f"   TOTAL: BPB medio={tot_bits / tot_bytes:.2f}  bits em ESTRUTURA={100 * tot_struct / tot_bits:.1f}%"
        )
    print("\n".join(out), flush=True)


if __name__ == "__main__":
    for r in sys.argv[1:]:
        run(r)
