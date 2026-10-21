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
import os
import platform
import random
import time
from pathlib import Path

from aurix.providers.ngram import NgramModel

EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".rs", ".go", ".java", ".sql", ".sh"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "target", "AURIX-backup-work"}


def files_under(root: Path, max_file_bytes: int) -> list[tuple[str, bytes]]:
    rows: list[tuple[str, bytes]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in SKIP_DIRS and not (Path(dirpath) / name).is_symlink()
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink() or path.suffix not in EXTENSIONS:
                continue
            rel = path.relative_to(root)
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
