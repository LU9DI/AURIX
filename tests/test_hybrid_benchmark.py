from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
from pathlib import Path

_RUN_PATH = Path(__file__).resolve().parents[1] / "research" / "hybrid_benchmark" / "run.py"
_SPEC = importlib.util.spec_from_file_location("aurix_hybrid_benchmark_run", _RUN_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_RUN = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUN)
bpb, split_files, target_bpb = _RUN.bpb, _RUN.split_files, _RUN.target_bpb


def test_split_is_deterministic_and_keeps_files_whole() -> None:
    rows = [(f"src/file_{i}.py", f"print({i})".encode()) for i in range(12)]
    train_a, test_a = split_files(rows)
    train_b, test_b = split_files(list(reversed(rows)))
    assert train_a == train_b
    assert test_a == test_b
    assert not ({name for name, _ in train_a} & {name for name, _ in test_a})
    assert len(train_a) + len(test_a) == len(rows)


def test_bpb_uses_base_two_and_rejects_empty_input() -> None:
    import pytest

    class FakeLogProbabilities:
        def __len__(self):
            return 2

        def sum(self):
            class Total:
                def item(self):
                    return -2 * math.log(2)
            return Total()

    assert bpb(FakeLogProbabilities()) == 1.0
    with pytest.raises(ValueError, match="empty"):
        bpb([])



def test_target_bpb_uses_each_position_not_the_target_as_a_position() -> None:
    first = [0.5 / 255] * 256
    first[200] = 0.5
    second = [0.75 / 255] * 256
    second[7] = 0.25
    assert target_bpb([first, second], bytes([200, 7])) == 1.5


def test_cli_rejects_non_positive_ngram_order() -> None:
    result = subprocess.run(
        [sys.executable, str(_RUN_PATH), "--order", "0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--order must be between 1 and 16" in result.stderr


def test_cli_rejects_ngram_order_above_provider_limit() -> None:
    result = subprocess.run(
        [sys.executable, str(_RUN_PATH), "--order", "17"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--order must be between 1 and 16" in result.stderr
