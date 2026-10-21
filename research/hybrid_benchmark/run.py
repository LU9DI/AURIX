"""Reproducible CPU benchmark: n-gram vs byte-GRU vs probability interpolation.

Optional research dependency: torch. Run from the AURIX repository root:
    python research/hybrid_benchmark/run.py --root . --output results.json

This is an experiment harness, not production provider code. It never downloads data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import time
from pathlib import Path

from aurix.providers.ngram import NgramModel

EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".rs", ".go", ".java", ".sql", ".sh"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "target"}


def files_under(root: Path, max_file_bytes: int) -> list[tuple[str, bytes]]:
    rows: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.suffix not in EXTENSIONS:
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
            raw = path.read_bytes()
            raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if raw:
            rows.append((rel.as_posix(), raw))
    return rows


def split_files(rows: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[tuple[str, bytes]]]:
    """Stable path-hash split; all files with the same normalized path stay in one split."""
    train, test = [], []
    for path, data in rows:
        bucket = int(hashlib.sha256(path.encode("utf-8")).hexdigest()[:8], 16) % 5
        (test if bucket == 0 else train).append((path, data))
    if not train or not test:
        raise ValueError("Need at least one train file and one held-out file; add more source files.")
    return train, test


def join_files(rows: list[tuple[str, bytes]]) -> bytes:
    # A sentinel avoids inventing adjacency between the end and start of files.
    return b"\n\x00\n".join(data for _, data in rows)


def score_ngram_files(model: NgramModel, rows: list[tuple[str, bytes]]) -> float:
    weighted = 0.0
    total = 0
    for _, data in rows:
        weighted += model.bits_per_byte(data) * len(data)
        total += len(data)
    if not total:
        raise ValueError("empty test split")
    return weighted / total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261020)
    parser.add_argument("--order", type=int, default=6)
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--max-eval-bytes", type=int, default=25000)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--sequence-length", type=int, default=128)
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=0.003)
    args = parser.parse_args()

    try:
        import numpy  # noqa: F401
        import torch
        from torch import nn
        import torch.nn.functional as F
    except ImportError as exc:
        raise SystemExit("Install research dependencies: pip install '.[cpu-lm]' torch") from exc

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    torch.use_deterministic_algorithms(True, warn_only=True)
    root = args.root.resolve()
    rows = files_under(root, max_file_bytes=300_000)
    train_rows, test_rows_full = split_files(rows)
    if args.max_eval_bytes < 2:
        raise SystemExit("--max-eval-bytes must be at least 2")
    # Bound the expensive per-byte hybrid loop; allocate a deterministic prefix budget per file.
    budget_per_file = max(2, args.max_eval_bytes // len(test_rows_full))
    test_rows = [(path, data[:budget_per_file]) for path, data in test_rows_full if len(data) >= 2]
    test_rows = test_rows[: max(1, args.max_eval_bytes // 2)]
    train_bytes = join_files(train_rows)
    test_bytes = join_files(test_rows)
    if len(train_bytes) < args.sequence_length + 2 or not test_bytes:
        raise SystemExit("Corpus too small for requested sequence length or held-out split.")

    start = time.perf_counter()
    ngram = NgramModel(train_bytes, order=args.order)
    ngram_train_seconds = time.perf_counter() - start
    ngram_bpb = score_ngram_files(ngram, test_rows)

    # Byte-level GRU language model. One prediction per byte; no pretrained weights.
    class ByteGRU(nn.Module):
        def __init__(self, hidden: int) -> None:
            super().__init__()
            self.embedding = nn.Embedding(256, 64)
            self.gru = nn.GRU(64, hidden, batch_first=True)
            self.output = nn.Linear(hidden, 256)

        def forward(self, x):
            h, _ = self.gru(self.embedding(x))
            return self.output(h)

    model = ByteGRU(args.hidden_size).cpu()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    train_tensor = torch.tensor(list(train_bytes), dtype=torch.long)
    test_tensors = [torch.tensor(list(data), dtype=torch.long) for _, data in test_rows]
    max_start = len(train_tensor) - args.sequence_length - 1
    if max_start <= 0:
        raise SystemExit("Training corpus too small.")
    start = time.perf_counter()
    model.train()
    for _ in range(args.steps):
        starts = torch.randint(0, max_start, (args.batch_size,))
        x = torch.stack([train_tensor[i : i + args.sequence_length] for i in starts])
        y = torch.stack([train_tensor[i + 1 : i + args.sequence_length + 1] for i in starts])
        optimizer.zero_grad(set_to_none=True)
        logits = model(x)
        loss = F.cross_entropy(logits.reshape(-1, 256), y.reshape(-1))
        loss.backward()
        optimizer.step()
    neural_train_seconds = time.perf_counter() - start

    def neural_log_probs(data: bytes):
        model.eval()
        with torch.no_grad():
            x = torch.tensor(list(data[:-1]), dtype=torch.long).unsqueeze(0)
            logits = model(x).squeeze(0)
            return F.log_softmax(logits, dim=-1)

    def evaluate_neural_and_hybrid():
        # Sequential scoring per file; the model sees preceding bytes in the same file only.
        nll_neural = 0.0
        count = 0
        lambdas = [0.0, 0.25, 0.5, 0.75, 1.0]  # weight on neural probabilities
        hybrid_nll = {str(v): 0.0 for v in lambdas}
        for _, raw in test_rows:
            if len(raw) < 2:
                continue
            logp = neural_log_probs(raw)
            neural_p = logp.exp().numpy()
            for i in range(len(raw) - 1):
                target = raw[i + 1]
                np_hist = raw[: i + 1]
                dist = ngram.next_distribution(np_hist)
                pn = float(neural_p[i, target])
                pg = float(dist[target])
                nll_neural += -math.log2(max(pn, 1e-30))
                for weight in lambdas:
                    prob = weight * pn + (1.0 - weight) * pg
                    hybrid_nll[str(weight)] += -math.log2(max(prob, 1e-30))
                count += 1
        if not count:
            raise ValueError("No scorable held-out bytes.")
        return {
            "neural_bpb": nll_neural / count,
            "hybrid_bpb_by_neural_weight": {k: v / count for k, v in hybrid_nll.items()},
            "scored_bytes": count,
        }

    start = time.perf_counter()
    neural_results = evaluate_neural_and_hybrid()
    inference_seconds = time.perf_counter() - start
    params = sum(p.numel() for p in model.parameters())
    # Approximate forward FLOPs per predicted byte for GRU gates + projection.
    hidden = args.hidden_size
    input_size = 64
    estimated_flops_per_byte = 3 * 2 * (hidden * input_size + hidden * hidden + hidden) + 2 * hidden * 256
    result = {
        "schema_version": 1,
        "experiment": "byte_ngram_vs_gru_vs_probability_interpolation",
        "seed": args.seed,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "numpy": __import__("numpy").__version__,
        "root_label": root.name,
        "source_file_count": len(rows),
        "train_files": [{"path": p, "sha256": hashlib.sha256(d).hexdigest(), "bytes": len(d)} for p, d in train_rows],
        "test_files": [{"path": p, "sha256": hashlib.sha256(next(raw for original_path, raw in test_rows_full if original_path == p)).hexdigest(), "file_bytes": len(next(raw for original_path, raw in test_rows_full if original_path == p)), "scored_prefix_bytes": len(d)} for p, d in test_rows],
        "train_bytes_with_separators": len(train_bytes),
        "test_bytes_raw": sum(len(d) for _, d in test_rows),
        "config": vars(args) | {"root": str(root), "output": str(args.output)},
        "metrics": {
            "ngram": {"order": args.order, "bpb": ngram_bpb, "train_seconds": ngram_train_seconds,
                      "flops_per_byte": "not meaningful: table-based counting/inference; report CPU time and memory instead"},
            "gru": {"parameters": params, "bpb": neural_results["neural_bpb"],
                    "train_seconds": neural_train_seconds, "inference_seconds_all_test_files": inference_seconds,
                    "estimated_forward_flops_per_byte": estimated_flops_per_byte},
            "hybrid": neural_results["hybrid_bpb_by_neural_weight"],
        },
        "method_notes": [
            "File-level deterministic split prevents same file from appearing in both train and test.",
            "The split is by normalized path hash, not commit time; disclose that limitation.",
            "The n-gram model is trained on joined training files but scored per test-file prefix.",
            "Evaluation is capped by --max-eval-bytes to bound CPU; only deterministic file prefixes are scored.",
            "Hybrid combines normalized next-byte probabilities, not logits.",
            "FLOPs are an analytic estimate for GRU forward operations, not a hardware counter.",
            "One seed and one split are exploratory; repeat seeds before making a claim.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "ngram_bpb": ngram_bpb,
        "gru_bpb": neural_results["neural_bpb"],
        "hybrid_bpb_by_neural_weight": neural_results["hybrid_bpb_by_neural_weight"],
        "gru_estimated_flops_per_byte": estimated_flops_per_byte,
        "train_seconds": {"ngram": ngram_train_seconds, "gru": neural_train_seconds},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
