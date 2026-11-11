"""Degrau 2: LM de patches dinamicos sem vocabulario (estilo Byte Latent Transformer, minusculo).
Segmentacao: entropia de um modelo de contagem de bytes (n-grama), sem rede neural e sem vocabulario.
Arquitetura: embedding de bytes -> vetor por patch -> transformer GLOBAL so nos patches -> decoder local por byte.
Metrica: bits por byte (BPB), identica a dos outros bracos."""

import argparse
import os
import json
import math
import time
import random
import sys
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from corpus import split

ap = argparse.ArgumentParser()
ap.add_argument("--minutes", type=float, default=10)
ap.add_argument("--ctx_bytes", type=int, default=512)
ap.add_argument("--target_patch", type=float, default=4.0)
ap.add_argument("--min_len", type=int, default=2)
ap.add_argument("--max_len", type=int, default=16)
ap.add_argument("--ngram", type=int, default=3)
ap.add_argument("--gl", type=int, default=4)
ap.add_argument("--gd", type=int, default=128)
ap.add_argument("--gh", type=int, default=4)
ap.add_argument("--ll", type=int, default=2)
ap.add_argument("--ld", type=int, default=64)
ap.add_argument("--lh", type=int, default=4)
ap.add_argument("--bs", type=int, default=16)
ap.add_argument("--lr", type=float, default=2e-3)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out", default=None)
ap.add_argument("--threads", type=int, default=2)
ap.add_argument("--ternary", action="store_true")
ap.add_argument("--steps", type=int, default=0)
ap.add_argument("--ckpt", default=None)
ap.add_argument("--chunk_sec", type=float, default=1e9)
a = ap.parse_args()
torch.manual_seed(a.seed)
random.seed(a.seed)
np.random.seed(a.seed)
torch.set_num_threads(a.threads)
train, val = split(0)
tr = np.frombuffer(b"\n\x00\n".join(b for _, _, b in train), dtype=np.uint8)
va_files = [np.frombuffer(b, dtype=np.uint8) for _, _, b in val]
N = a.ngram


# ---------- patcher: entropia de n-grama (contagem) ----------
def ctx_ids(x):  # contexto dos N bytes anteriores (preenche com 0 no inicio)
    pad = np.concatenate([np.zeros(N, dtype=np.uint8), x]).astype(np.int64)
    c = np.zeros(len(x), dtype=np.int64)
    for k in range(N):
        c = c * 256 + pad[k : k + len(x)]
    return c


tr_ctx = ctx_ids(tr)
key = tr_ctx * 256 + tr.astype(np.int64)
uk, cnt = np.unique(key, return_counts=True)
uc, inv = np.unique(uk // 256, return_inverse=True)
tot = np.bincount(inv, weights=cnt)
ent_tab = np.zeros(len(uc))
p = cnt / tot[inv]
np.add.at(ent_tab, inv, -p * np.log2(p))


def entropies(x):
    c = ctx_ids(x)
    idx = np.searchsorted(uc, c)
    idx[idx >= len(uc)] = 0
    known = uc[idx] == c
    return np.where(known, ent_tab[idx], 8.0)  # contexto nunca visto = maxima incerteza


def flags(x, theta):
    h = entropies(x)
    f = np.zeros(len(x), dtype=np.int8)
    last = 0
    f[0] = 1
    for j in range(1, len(x)):
        d = j - last
        if d >= a.max_len or (d >= a.min_len and h[j] > theta):
            f[j] = 1
            last = j
    return f


def pick_theta(x, target):
    lo, hi = 0.0, 8.0
    for _ in range(14):
        mid = (lo + hi) / 2
        avg = len(x) / flags(x[:600_000], mid).sum() if False else None
        f = flags(x[:600_000], mid)
        avg = 600_000 / f.sum()
        if avg > target:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


theta = pick_theta(tr, a.target_patch)
tr_f = flags(tr, theta)
va_f = [flags(x, theta) for x in va_files]
print(
    f"patcher: theta={theta:.3f} bits, tamanho medio do patch treino={len(tr) / tr_f.sum():.2f} bytes, val={sum(len(x) for x in va_files) / sum(int(f.sum()) for f in va_f):.2f}",
    flush=True,
)


# ---------- modelo ----------
class BitLinear(nn.Linear):
    """Pesos ternarios {-1,0,+1}*escala (absmean) e ativacoes int8 (absmax por token), com STE (estilo BitNet b1.58).
    Simulado em float: serve para medir QUALIDADE (BPB); nao acelera nesta CPU. Em hardware dedicado, o produto
    por peso vira soma/subtracao."""

    def forward(self, x):
        w = self.weight
        sc = w.abs().mean().clamp(min=1e-5)
        w = w + ((w / sc).round().clamp(-1, 1) * sc - w).detach()
        xs = x.abs().amax(-1, keepdim=True).clamp(min=1e-5) / 127
        x = x + ((x / xs).round().clamp(-128, 127) * xs - x).detach()
        return F.linear(x, w, self.bias)


Lin = BitLinear if a.ternary else nn.Linear


class Block(nn.Module):
    def __init__(s, d, h):
        super().__init__()
        s.h = h
        s.ln1 = nn.LayerNorm(d)
        s.qkv = Lin(d, 3 * d)
        s.o = Lin(d, d)
        s.ln2 = nn.LayerNorm(d)
        s.ff = nn.Sequential(Lin(d, 4 * d), nn.GELU(), Lin(4 * d, d))

    def forward(s, x, mask=None):
        B, T, D = x.shape
        q, k, v = s.qkv(s.ln1(x)).view(B, T, 3, s.h, D // s.h).permute(2, 0, 3, 1, 4)
        o = F.scaled_dot_product_attention(q, k, v, attn_mask=mask, is_causal=(mask is None))
        x = x + s.o(o.transpose(1, 2).reshape(B, T, D))
        return x + s.ff(s.ln2(x))


PMAX = a.ctx_bytes // a.min_len


class PatchLM(nn.Module):
    def __init__(s):
        super().__init__()
        s.emb = nn.Embedding(256, a.ld)
        s.inpos = nn.Embedding(a.max_len, a.ld)
        s.enc_proj = nn.Sequential(nn.Linear(a.ld, a.gd), nn.GELU())
        s.ppos = nn.Embedding(PMAX, a.gd)
        s.gblocks = nn.ModuleList(Block(a.gd, a.gh) for _ in range(a.gl))
        s.gln = nn.LayerNorm(a.gd)
        s.start = nn.Parameter(torch.zeros(a.gd))
        s.g2l = nn.Linear(a.gd, a.ld)
        s.lblocks = nn.ModuleList(Block(a.ld, a.lh) for _ in range(a.ll))
        s.lln = nn.LayerNorm(a.ld)
        s.head = nn.Linear(a.ld, 256)

    def forward(s, x, f):  # x: (B,T) bytes de entrada; f: (B,T+1) flags de inicio de patch em w
        B, T = x.shape
        f = f.clone()
        f[:, 0] = 1
        pid = torch.cumsum(f, 1)[:, :T] - 1  # patch de cada byte de entrada
        P = int(pid.max()) + 1
        start_idx = torch.cummax(
            torch.where(
                f[:, :T] == 1, torch.arange(T).expand(B, T), torch.zeros(B, T, dtype=torch.long)
            ),
            1,
        ).values
        inpos = (torch.arange(T).expand(B, T) - start_idx).clamp(max=a.max_len - 1)
        e = s.emb(x) + s.inpos(inpos)
        # vetor por patch = media dos bytes do patch (so bytes ja vistos)
        pv = torch.zeros(B, P, a.ld).scatter_add_(1, pid.unsqueeze(-1).expand(B, T, a.ld), e)
        n = torch.zeros(B, P).scatter_add_(1, pid, torch.ones(B, T)).clamp(min=1)
        g = s.enc_proj(pv / n.unsqueeze(-1)) + s.ppos(torch.arange(P))
        for blk in s.gblocks:
            g = blk(g)  # transformer causal SO sobre patches
        g = s.gln(g)
        gs = torch.cat(
            [s.start.expand(B, 1, a.gd), g], 1
        )  # gs[:, k+1] = latente do patch k; gs[:,0] = inicio
        nxt = f[
            :, 1 : T + 1
        ].bool()  # o proximo byte inicia um novo patch? (decidido por bytes ja vistos)
        use = torch.where(
            nxt, pid + 1, pid
        )  # prox. inicia patch: usa patch atual completo; senao: so patches anteriores
        lat = torch.gather(gs, 1, use.unsqueeze(-1).expand(B, T, a.gd))
        h = e + s.g2l(lat)
        mask = (
            (pid.unsqueeze(2) == pid.unsqueeze(1)) & torch.tril(torch.ones(T, T, dtype=torch.bool))
        ).unsqueeze(1)
        for blk in s.lblocks:
            h = blk(h, mask)
        return s.head(s.lln(h))


m = PatchLM()
for n_, p_ in m.named_parameters():
    if p_.dim() > 1:
        nn.init.normal_(p_, 0, 0.02)
nparams = sum(p.numel() for p in m.parameters())
print(f"arm=patch params={nparams}", flush=True)
opt = torch.optim.AdamW(m.parameters(), lr=a.lr, weight_decay=0.01, betas=(0.9, 0.95))
ctx = a.ctx_bytes


def batch(ix):
    w = np.stack([tr[i : i + ctx + 1] for i in ix]).astype(np.int64)
    ff = np.stack([tr_f[i : i + ctx + 1] for i in ix]).astype(np.int64)
    w = torch.from_numpy(w)
    return w[:, :-1], w[:, 1:], torch.from_numpy(ff)


@torch.no_grad()
def eval_bpb(full=False):
    m.eval()
    nll = 0.0
    nb = 0
    for x_, f_ in list(zip(va_files, va_f))[: (len(va_files) if full else 8)]:
        for s_ in range(0, len(x_) - 1, ctx):
            w = torch.from_numpy(x_[s_ : s_ + ctx + 1].astype(np.int64))
            ff = torch.from_numpy(f_[s_ : s_ + ctx + 1].astype(np.int64)).unsqueeze(0)
            if len(w) < 2:
                continue
            lg = m(w[:-1].unsqueeze(0), ff)[0]
            nll += F.cross_entropy(lg, w[1:], reduction="sum").item()
            nb += len(w) - 1
    m.train()
    return nll / math.log(2) / nb


train_t = 0.0
budget = a.minutes * 60
step = 0
seen = 0
log = []
next_eval = 0.0


def progress():
    return step / a.steps if a.steps else train_t / budget


if a.ckpt and os.path.exists(a.ckpt):
    ck = torch.load(a.ckpt, weights_only=False)
    m.load_state_dict(ck["m"])
    opt.load_state_dict(ck["o"])
    train_t, step, seen, log, next_eval = (
        ck["train_t"],
        ck["step"],
        ck["seen"],
        ck["log"],
        ck["next_eval"],
    )
    np.random.seed(a.seed + step)
    torch.manual_seed(a.seed + step)
    print(f"retomado do checkpoint: step={step} train_t={train_t:.0f}s", flush=True)


def save_ck():
    if a.ckpt:
        torch.save(
            dict(
                m=m.state_dict(),
                o=opt.state_dict(),
                train_t=train_t,
                step=step,
                seen=seen,
                log=log,
                next_eval=next_eval,
            ),
            a.ckpt + ".tmp",
        )
        os.replace(a.ckpt + ".tmp", a.ckpt)


chunk_start = train_t
last_ck = train_t
while True:
    el = train_t
    prog = progress()
    if prog >= next_eval - 1e-9:
        b = eval_bpb(full=(prog >= 1))
        log.append(dict(step=step, sec=round(el), bytes_seen=int(seen), val_bpb=round(b, 4)))
        print(json.dumps(log[-1]), flush=True)
        next_eval += 1 / 6
    if prog >= 1:
        break
    if train_t - chunk_start >= a.chunk_sec:
        save_ck()
        print("CHUNK_DONE", flush=True)
        sys.exit(0)
    if train_t - last_ck >= 60:
        save_ck()
        last_ck = train_t
    tic = time.time()
    lr = a.lr * 0.5 * (1 + math.cos(math.pi * min(1, prog)))
    for g_ in opt.param_groups:
        g_["lr"] = lr
    x, y, ff = batch(np.random.randint(0, len(tr) - ctx - 2, a.bs))
    loss = F.cross_entropy(m(x, ff).reshape(-1, 256), y.reshape(-1))
    opt.zero_grad()
    loss.backward()
    nn.utils.clip_grad_norm_(m.parameters(), 1.0)
    opt.step()
    step += 1
    seen += a.bs * ctx
    train_t += time.time() - tic
ap_ = tr_f.sum() and len(tr) / tr_f.sum()


def blk(d):  # MACs de um bloco (qkv 3d^2, o d^2, ff 8d^2) por posicao
    return 12 * d * d


macs_blocks_per_byte = a.gl * blk(a.gd) / ap_ + a.ll * blk(a.ld)
macs_other_per_byte = a.ld * a.gd / ap_ + a.gd * a.ld + a.ld * 256
res = dict(
    arm="patch_ternary" if a.ternary else "patch_float",
    gd=a.gd,
    ld=a.ld,
    ternary=a.ternary,
    linear_macs_blocks_per_byte=round(macs_blocks_per_byte),
    linear_macs_other_per_byte=round(macs_other_per_byte),
    train_sec=round(train_t),
    params=nparams,
    steps=step,
    bytes_seen=int(seen),
    final_val_bpb=log[-1]["val_bpb"],
    log=log,
    seed=a.seed,
    minutes=a.minutes,
    theta=theta,
    avg_patch=len(tr) / tr_f.sum(),
)
print("FINAL", json.dumps({k: v for k, v in res.items() if k != "log"}))
if a.out:
    json.dump(res, open(a.out, "w"))
    torch.save(m.state_dict(), a.out.replace(".json", ".pt"))
