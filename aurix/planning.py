"""Bounded multi-branch planning for autonomous research.

This is a lightweight UCT-inspired planner, not a claim of full general-purpose
MCTS. It keeps a tiny in-memory search tree, uses deterministic priors and bounded
exploration, and always has a finite number of branches/attempts.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[\w.-]{2,}", text, flags=re.UNICODE)}


@dataclass
class Branch:
    name: str
    query: str
    prior: float
    visits: int = 0
    reward_sum: float = 0.0
    failures: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def mean_reward(self) -> float:
        return self.reward_sum / self.visits if self.visits else 0.0

    def score(self, total_visits: int, exploration: float = 0.7) -> float:
        if self.visits == 0:
            return self.prior + exploration * math.sqrt(math.log(total_visits + 2))
        return (
            self.mean_reward
            + self.prior * 0.2
            + exploration * math.sqrt(math.log(total_visits + 1) / self.visits)
            - min(0.8, self.failures * 0.25)
        )


class BoundedStudyPlanner:
    """Create three alternative study paths and rank them with a bounded UCT score."""

    def __init__(self, topic: str, *, known_context: str = "") -> None:
        normalized = " ".join(str(topic).split())[:500]
        if not normalized:
            raise ValueError("topic must not be empty")
        self.topic = normalized
        overlap = len(_tokens(normalized) & _tokens(known_context)) / max(
            1, len(_tokens(normalized))
        )
        # More prior knowledge raises the value of seeking verification and gaps.
        self.branches = [
            Branch("direct", normalized, 0.78 - 0.15 * overlap),
            Branch("documentation", f"{normalized} official documentation standards", 0.92),
            Branch(
                "implementation",
                f"{normalized} implementation examples limitations failure modes",
                0.86 + 0.1 * overlap,
            ),
        ]
        self._total_visits = 0

    def ordered_branches(self) -> list[Branch]:
        """Return a stable ranking; the caller tries at most one pass over branches."""
        return sorted(
            self.branches, key=lambda branch: (-branch.score(self._total_visits), branch.name)
        )

    def record(
        self, branch_name: str, *, reward: float, failed: bool = False, note: str = ""
    ) -> None:
        branch = next((item for item in self.branches if item.name == branch_name), None)
        if branch is None:
            raise ValueError("unknown planning branch")
        bounded_reward = max(0.0, min(1.0, float(reward)))
        branch.visits += 1
        branch.reward_sum += bounded_reward
        branch.failures += int(failed)
        if note:
            branch.notes.append(" ".join(note.split())[:160])
        self._total_visits += 1

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "name": branch.name,
                "query": branch.query,
                "prior": round(branch.prior, 4),
                "visits": branch.visits,
                "mean_reward": round(branch.mean_reward, 4),
                "failures": branch.failures,
                "score": round(branch.score(self._total_visits), 4),
            }
            for branch in self.branches
        ]
