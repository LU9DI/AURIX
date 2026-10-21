from __future__ import annotations

import math

from research.hybrid_benchmark.run import bpb, split_files


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
