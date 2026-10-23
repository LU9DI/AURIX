"""Stage B-lite: completion quality and batch-1 latency vs decoding budget.

Prompt = first P bytes of a held-out window, target = next G bytes. Greedy decoding for both.
AR uses a KV cache; diffusion runs a full bidirectional forward per step (no cache), K steps,
unmasking the n/K most confident positions per step. Wall-clock is CPU float32, 1 thread.
"""
import json, statistics, sys, time, torch
import stage_a as S

P, G = 96, 32

@torch.no_grad()
def gen_ar(m, prompt):
    caches = [dict() for _ in m.blocks]
    lg = m(prompt[None], True, caches, 0)[0, -1]; out = []
    for i in range(G):
        nx = lg.argmax().item(); out.append(nx)
        if i == G - 1: break
        lg = m(torch.tensor([[nx]]), True, caches, P + i)[0, -1]
    return out, G  # NFE counted in forward passes

@torch.no_grad()
def gen_diff(m, prompt, K):
    x = torch.cat([prompt, torch.full((G,), S.MASK)])[None]; left = G; per = [G // K + (1 if i < G % K else 0) for i in range(K)]
    for k in range(K):
        lg = m(x, False)[0, P:]; pr = lg.softmax(-1); conf, tok = pr.max(-1)
        free = (x[0, P:] == S.MASK); conf = torch.where(free, conf, torch.full_like(conf, -1))
        for j in conf.topk(per[k]).indices.tolist(): x[0, P + j] = tok[j]
    return x[0, P:].tolist(), K

def main(ar_ckpt, diff_ckpt, n_acc=200, n_time=20, reps=5, Ks=(2, 4, 8, 16, 32), out="results/gen_eval.json"):
    torch.set_num_threads(1); _, va = S.load_split(); win = S.windows(va, n_acc, 4242)
    res = {}
    models = {}
    for name, ck in (("ar", ar_ckpt), ("diff", diff_ckpt)):
        m = S.LM(); m.load_state_dict(torch.load(ck)); m.eval(); models[name] = m
    configs = [("ar", None)] + [("diff", K) for K in Ks]
    for name, K in configs:
        m = models[name]; fn = (lambda p: gen_ar(m, p)) if name == "ar" else (lambda p: gen_diff(m, p, K))
        acc, exact, first8, lat = [], [], [], []
        for i, w in enumerate(win):
            p, tgt = w[:P], w[P:P + G].tolist()
            if i < n_time:
                fn(p)  # warm-up
                ts = []
                for _ in range(reps): t0 = time.perf_counter(); o, nfe = fn(p); ts.append(time.perf_counter() - t0)
                lat += ts
            else: o, nfe = fn(p)
            acc.append(sum(a == b for a, b in zip(o, tgt)) / G); exact.append(o == tgt)
            first8.append(sum(a == b for a, b in zip(o[:8], tgt[:8])) / 8)
        lat.sort()
        res[f"{name}{'' if K is None else '_K' + str(K)}"] = {
            "forward_passes": nfe, "byte_acc": statistics.mean(acc), "first8_acc": statistics.mean(first8),
            "exact32": statistics.mean(exact), "n_prompts": n_acc,
            "lat_median_ms": 1000 * statistics.median(lat), "lat_p90_ms": 1000 * lat[int(0.9 * len(lat)) - 1]}
        print(name, K, res[f"{name}{'' if K is None else '_K' + str(K)}"], flush=True)
    json.dump(res, open(out, "w"), indent=1)

if __name__ == "__main__": main(sys.argv[1], sys.argv[2])
