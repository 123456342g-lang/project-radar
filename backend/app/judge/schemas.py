from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROBLEM_TYPES = [
    "bug_fix",
    "missing_feature",
    "developer_experience",
    "performance",
    "integration",
    "documentation",
    "workflow",
    "architecture",
    "other",
]

SAME_PROBLEM = "same_problem"
RECURRING = "recurring_independent"
UNRESOLVED = "still_unresolved"
WORTH_BUILDING = "worth_building"
PROBLEM_TYPE = "problem_type"


@dataclass
class Judgment:
    same_problem: float = 0.0
    recurring: float = 0.0
    unresolved: float = 0.0
    worth_building: float = 0.0
    problem_type: str = "other"
    judge_mode: str = "heuristic"
    model: str = "none"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def confidence(self) -> float:
        if self.judge_mode == "heuristic":
            return 0.0
        raw = self.raw or {}
        scores = [
            float(raw.get(key, {}).get("confidence", 0.5))
            for key in (SAME_PROBLEM, UNRESOLVED, WORTH_BUILDING)
            if isinstance(raw.get(key), dict)
        ]
        return round(sum(scores) / len(scores), 4) if scores else 0.5
