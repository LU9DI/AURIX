"""Bounded CPU benchmark: byte n-gram, byte-GRU and probability interpolation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import time
from pathlib import Path

from aurix.providers.ngram import NgramModel

EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".rs", ".go", ".java", ".sql", ".sh"}
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    "target", "AURIX-backup-work", ".pytest_cache",
}


def files_under(root: Path, max_file_bytes: int) -> list[tuple[str, bytes]]:
    """Read deterministic, UTF-8 source files without following symlinks."""
    rows: list[tuple[str, bytes]] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        directory = Path(dirpath)
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in SKIP_DIRS and not (directory / name).is_symlink()
        )
        for name in sorted(filenames):
            path = directory / name
            if path.is_symlink() or path.suffix not in EXTENSIONS:
                continue
            try:
                if path.stat().st_size > max_file_bytes:
                    continue
                raw = path.read_bytes()
                raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if raw:
                rows.append((path.relative_to(root).as_posix(), raw))
    return rows


def split_files(rows: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[tuple[str, bytes]]]:
    """Stable path-hash split; files never cross the train/test boundary."""
    train, test = [], []
    for row in sorted(rows, key=lambda item: item[0]):
        bucket = int(hashlib.sha256(row[0].encode()).hexdigest()[:8], 16) % 10
        (test if bucket < 2 else train).append(row)
    if len(rows) >= 2 and (not train or not test):
        ordered = sorted(rows, key=lambda item: hashlib.sha256(item[0].encode()).hexdigest())
        test = [ordered[0]]
        train = ordered[1:]
    return train, test


def bpb(log_probs) -> float:
    """Convert natural-log probabilities into bits per byte."""
    if len(log_probs) == 0:
        raise ValueError("cannot score an empty sequence")
    return float(-log_probs.sum().item() / (math.log(2) * len(log_probs)))


def train_gru(train_bytes: bytes, steps: int, seq_len: int, batch_size: int,
              hidden_size: int, seed: int, device: str):
    import torch
    from torch import nn

    torch.manual_seed(seed)
    random.seed(seed)
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))

    class ByteGRU(nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = nn.Embedding(256, 64)
            self.gru = nn.GRU(64, hidden_size, batch_first=True)
            self.output = nn.Linear(hidden_size, 256)

        def forward(self, x):
            hidden, _ = self.gru(self.embedding(x))
            return self.output(hidden)

    model = ByteGRU().to(device)
    data = torch.tensor(list(train_bytes), dtype=torch.long, device=device)
    if data.numel() < seq_len + 2:
        raise ValueError("training corpus too small for requested sequence length")
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003)
    model.train()
    start = time.perf_counter()
    for _ in range(steps):
        starts = torch.randint(0, data.numel() - seq_len - 1, (batch_size,), device=device)
        x = torch.stack([data[s:s + seq_len] for s in starts])
        y = torch.stack([data[s + 1:s + seq_len + 1] for s in starts])
        optimizer.zero_grad(set_to_none=True)
        loss = nn.functional.cross_entropy(model(x).reshape(-1, 256), y.reshape(-1))
        loss.backward()
        optimizer.step()
    train_seconds = time.perf_counter() - start
    model.eval()
    return model, train_seconds, sum(p.numel() for p in model.parameters())


def neural_log_probs(model, raw: bytes, device: str):
    import torch
    if len(raw) < 2:
        return torch.empty((0, 256), device=device)
    # logits at position i predict raw[i+1]; the first byte is context only.
    x = torch.tensor(list(raw[:-1]), dtype=torch.long, device=device).unsqueeze(0)
    with torch.no_grad():
        return torch.log_softmax(model(x).squeeze(0), dim=-1)


def score_models(model, neural, test_rows, max_eval_bytes: int, device: str):
    import torch

    remaining = max_eval_bytes
    totals = {"ngram": 0.0, "neural": 0.0, **{f"hybrid_{a:.2f}": 0.0 for a in (0, .25, .5, .75, 1.)}}
    scored = 0
    inference_start = time.perf_counter()
    for _, raw in test_rows:
        if remaining <= 0:
            break
        # Each byte after the first is scored with preceding bytes as context.
        sample = raw[:min(len(raw), remaining + 1)]
        remaining -= max(0, len(sample) - 1)
        if len(sample) < 2:
            continue
        neural_lp = neural_log_probs(neural, sample, device)
        ngram_lp = []
        for i in range(len(sample) - 1):
            probs = model.next_distribution(sample[:i + 1])
            ngram_lp.append(max(float(probs[sample[i + 1]]), 1e-12))
        ngram_lp_t = torch.tensor(ngram_lp, dtype=torch.float64)
        neural_probs = neural_lp.exp().to(torch.float64)
        ngram_probs = torch.zeros_like(neural_probs)
        target = torch.tensor(list(sample[1:]), dtype=torch.long, device=device)
        # Recreate full n-gram distributions only for the bounded evaluation prefix.
        for i in range(len(sample) - 1):
            ngram_probs[i] = torch.tensor(
                model.next_distribution(sample[:i + 1]), dtype=torch.float64, device=device
            )
        totals["ngram"] += float(-torch.log2(ngram_t.gather(0, target.cpu()).clamp_min(1e-12)).sum())
        totals["neural"] += float(-neural_lp.gather(1, target.unsqueeze(1)).sum().item() / math.log(2))
        for alpha in (0., .25, .5, .75, 1.):
            mix = alpha * neural_probs + (1. - alpha) * ngram_probs
            totals[f"hybrid_{alpha:.2f}"] += float(
                -torch.log2(mix.gather(1, target.unsqueeze(1)).clamp_min(1e-12)).sum().item()
            )
        scored += len(sample) - 1
    elapsed = time.perf_counter() - inference_start
    if not scored:
        raise ValueError("no held-out bytes available; add source files or raise --max-file-bytes")
    return {key: value / scored for key, value in totals.items()}, elapsed, scored


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("artifacts/hybrid-benchmark.json"))
    parser.add_argument("--order", type=int, default=6)
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--seq-len", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-file-bytes", type=int, default=300_000)
    parser.add_argument("--max-eval-bytes", type=int, default=25_000)
    parser.add_argument("--max-train-bytes", type=int, default=1_000_000)
    args = parser.parse_args()
    if min(args.steps, args.seq_len, args.batch_size, args.hidden_size,
           args.max_eval_bytes, args.max_train_bytes) < 1:
        parser.error("steps, sequence length, batch size, hidden size and byte limits must be positive")

    rows = files_under(args.root, args.max_file_bytes)
    train_rows, test_rows = split_files(rows)
    if not train_rows or not test_rows:
        parser.error("need at least two eligible source files split between train and test")
    train_blob = b"\n\x00\n".join(data for _, data in train_rows)
    train_blob = train_blob[:args.max_train_bytes]
    if len(train_blob) < args.seq_len + 2:
        parser.error("training corpus is too small for --seq-len; lower it or raise --max-train-bytes")

    try:
        import torch
        import numpy
    except ImportError as exc:
        raise SystemExit("Install research dependencies with: pip install -e '.[cpu-lm]' && pip install torch") from exc
    device = "cpu"
    start = time.perf_counter()
    ngram = NgramModel(train_blob, order=args.order)
    ngram_train_seconds = time.perf_counter() - start
    neural, neural_train_seconds, parameter_count = train_gru(
        train_blob, args.steps, args.seq_len, args.batch_size, args.hidden_size, args.seed, device
    )
    metrics, inference_seconds, scored_bytes = score_models(
        ngram, neural, test_rows, args.max_eval_bytes, device
    )
    # Approximate GRU forward arithmetic per byte; this is a formula, not a hardware counter.
    h, e = args.hidden_size, 64
    gru_flops = 3 * 2 * (e * h + h * h + h) + 2 * h * 256
    result = {
        "experiment": "ngram_byte_gru_probability_interpolation",
        "seed": args.seed,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "numpy": numpy.__version__,
        "device": device,
        "config": vars(args) | {"root": str(args.root.resolve()), "device": device},
        "corpus": {
            "train_files": len(train_rows), "test_files": len(test_rows),
            "train_bytes_used": len(train_blob), "test_bytes_scored": scored_bytes,
            "files": [{"path": name, "bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()} for name, data in rows],
        },
        "metrics": {
            "bpb": metrics,
            "ngram_build_seconds": ngram_train_seconds,
            "neural_train_seconds": neural_train_seconds,
            "evaluation_seconds": inference_seconds,
            "neural_parameter_count": parameter_count,
            "estimated_gru_forward_flops_per_byte": gru_flops,
        },
        "notes": [
            "Path-hash file split is exploratory; similar files may leak patterns.",
            "Evaluation scores a bounded prefix of held-out files, not a full-corpus score.",
            "FLOPs are analytical estimates, not measured hardware counters.",
            "Compare seeds and repository/time-separated splits before drawing conclusions.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "metrics": result["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
