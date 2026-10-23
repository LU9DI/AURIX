"""Stage A (mechanism check): autoregressive vs masked-diffusion byte LM, same architecture.

Controlled: identical Transformer (same params; only the attention mask differs: causal vs bidirectional),
same frozen corpus + file-level split, same windows, same optimizer/steps/batch, learning rate tuned
per variant. NOT a coding-agent benchmark.

  python stage_a.py train --mode ar|diff --lr 2e-3 --seed 0 --out results/ar_lr2e-3_s0.json
"""
import argparse, json, math, os, pickle, random, sys, time
import torch, torch.nn as nn, torch.nn.functional as F

CORPUS = os.environ.get("STAGE_A_CORPUS", "corpus_frozen.pkl")
T, V, MASK = 128, 257, 256

def load_split(seed=0):
    fs = pickle.load(open(CORPUS, "rb")); rnd = random.Random(seed); rnd.shuffle(fs)
    nv = max(1, len(fs) // 10)
    return [b for _, _, b in fs[nv:]], [b for _, _, b in fs[:nv]]

def windows(files, n, seed):
    rnd = random.Random(seed); w = []
    ws = [len(f) - T for f in files]
    while len(w) < n:
        f = rnd.choices(files, weights=ws)[0]
        i = rnd.randrange(0, len(f) - T + 1)
        w.append(list(f[i:i + T]))
    return torch.tensor(w, dtype=torch.long)

class Block(nn.Module):
    def __init__(s, d, h):
        super().__init__(); s.h = h; s.n1 = nn.LayerNorm(d); s.qkv = nn.Linear(d, 3 * d); s.o = nn.Linear(d, d)
        s.n2 = nn.LayerNorm(d); s.f1 = nn.Linear(d, 4 * d); s.f2 = nn.Linear(4 * d, d)
    def forward(s, x, causal, cache=None):
        B, L, D = x.shape; q, k, v = s.qkv(s.n1(x)).view(B, L, 3, s.h, D // s.h).permute(2, 0, 3, 1, 4)
        if cache is not None:  # incremental decoding (AR only)
            if "k" in cache: k = torch.cat([cache["k"], k], 2); v = torch.cat([cache["v"], v], 2)
            cache["k"], cache["v"] = k, v
            a = F.scaled_dot_product_attention(q, k, v, is_causal=False)
        else:
            a = F.scaled_dot_product_attention(q, k, v, is_causal=causal)
        x = x + s.o(a.transpose(1, 2).reshape(B, L, D))
        return x + s.f2(F.gelu(s.f1(s.n2(x))))

class LM(nn.Module):
    def __init__(s, d=128, h=4, n=4):
        super().__init__(); s.emb = nn.Embedding(V, d); s.pos = nn.Embedding(T, d)
        s.blocks = nn.ModuleList(Block(d, h) for _ in range(n)); s.nf = nn.LayerNorm(d); s.out = nn.Linear(d, 256)
    def forward(s, x, causal, caches=None, start=0):
        L = x.shape[1]; h = s.emb(x) + s.pos(torch.arange(start, start + L))
        for i, b in enumerate(s.blocks): h = b(h, causal, None if caches is None else caches[i])
        return s.out(s.nf(h))

def ar_loss(m, x):  # nats per predicted byte (first byte has no context and is not scored)
    lg = m(x[:, :-1], True); return F.cross_entropy(lg.reshape(-1, 256), x[:, 1:].reshape(-1))

def diff_loss(m, x, t=None):  # MDLM absorbing-state ELBO, nats per byte (upper bound on NLL)
    B, L = x.shape
    if t is None: t = (torch.rand(1) + torch.arange(B) / B) % 1.0; t = t.clamp(min=1e-3)  # stratified
    msk = torch.rand(B, L) < t[:, None]
    xin = torch.where(msk, torch.full_like(x, MASK), x)
    ce = F.cross_entropy(m(xin, False).reshape(-1, 256), x.reshape(-1), reduction="none").view(B, L)
    return ((ce * msk) / t[:, None]).sum() / (B * L)

@torch.no_grad()
def eval_bpb(m, mode, val, reps=8):
    m.eval(); tot = 0.0; n = 0
    for i in range(0, len(val), 100):
        x = val[i:i + 100]
        if mode == "ar": l = ar_loss(m, x).item()
        else:
            g = torch.Generator().manual_seed(1234 + i)  # same masks for every model
            l = sum(diff_loss(m, x, t=torch.full((len(x),), (r + 0.5) / reps)).item() for r in range(reps)) / reps
        tot += l; n += 1
    m.train(); return tot / n / math.log(2)

def train(a):
    torch.set_num_threads(1); torch.manual_seed(a.seed); random.seed(a.seed)
    tr, va = load_split(); val = windows(va, 1000, 999)
    m = LM(); npar = sum(p.numel() for p in m.parameters())
    opt = torch.optim.AdamW(m.parameters(), lr=a.lr, betas=(0.9, 0.95), weight_decay=0.01)
    sched = lambda s: min(1, s / 100) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * s / a.steps)))
    rnd = random.Random(a.seed); t0 = time.time(); hist = []
    for s in range(a.steps):
        x = windows(tr, a.batch, rnd.randrange(1 << 30))
        for g in opt.param_groups: g["lr"] = a.lr * sched(s)
        loss = ar_loss(m, x) if a.mode == "ar" else diff_loss(m, x)
        opt.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(m.parameters(), 1.0); opt.step()
        if (s + 1) % 250 == 0 or s + 1 == a.steps:
            hist.append((s + 1, loss.item() / math.log(2))); print(a.mode, s + 1, round(hist[-1][1], 3), round(time.time() - t0), flush=True)
    bpb = eval_bpb(m, a.mode, val)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"mode": a.mode, "lr": a.lr, "seed": a.seed, "steps": a.steps, "batch": a.batch, "params": npar,
               "val_bpb": bpb, "bpb_kind": "exact" if a.mode == "ar" else "ELBO upper bound",
               "train_seconds": time.time() - t0, "hist": hist, "torch": torch.__version__}, open(a.out, "w"))
    torch.save(m.state_dict(), a.out.replace(".json", ".pt")); print("val_bpb", bpb, "params", npar)

if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("cmd"); p.add_argument("--mode"); p.add_argument("--lr", type=float)
    p.add_argument("--seed", type=int, default=0); p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--batch", type=int, default=32); p.add_argument("--out"); a = p.parse_args()
    train(a)
