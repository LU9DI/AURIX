import pytest

from aurix.planning import BoundedStudyPlanner


def test_planner_creates_three_bounded_branches():
    planner = BoundedStudyPlanner("Rust async cancellation")
    branches = planner.ordered_branches()
    assert len(branches) == 3
    assert {branch.name for branch in branches} == {"direct", "documentation", "implementation"}
    assert all(len(branch.query) <= 500 for branch in branches)


def test_planner_penalizes_failed_branch_and_records_bounded_reward():
    planner = BoundedStudyPlanner("SQLite WAL")
    first = planner.ordered_branches()[0]
    planner.record(first.name, reward=4.0, failed=True, note="timeout")
    record = next(item for item in planner.snapshot() if item["name"] == first.name)
    assert record["visits"] == 1
    assert record["mean_reward"] == 1.0
    assert record["failures"] == 1
    with pytest.raises(ValueError):
        planner.record("unknown", reward=0.5)
