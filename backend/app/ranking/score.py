from __future__ import annotations

from dataclasses import dataclass
from typing import Any

WEIGHTS = {
    "recurrence": 0.25,
    "unresolved": 0.25,
    "user_demand": 0.20,
    "buildability": 0.15,
    "cross_surface": 0.15,
}

MAX_AUTHORS_FOR_SATURATION = 12
MAX_ISSUES_FOR_SATURATION = 15
MAX_SPAN_DAYS_FOR_SATURATION = 400
SMALL_PR_CHANGED_FILES = 30


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def recurrence_score(evidence: dict[str, Any]) -> float:
    authors = int(evidence.get("independent_authors") or 0)
    issues = int(evidence.get("issues") or 0)
    discussions = int(evidence.get("discussions") or 0)
    span = int(evidence.get("span_days") or 0)
    author_part = _clamp(authors / MAX_AUTHORS_FOR_SATURATION)
    issue_part = _clamp(issues / MAX_ISSUES_FOR_SATURATION)
    span_part = _clamp(span / MAX_SPAN_DAYS_FOR_SATURATION)
    discussion_part = _clamp(discussions / 5)
    return _clamp(
        0.40 * author_part + 0.30 * issue_part + 0.20 * span_part + 0.10 * discussion_part
    )


def user_demand_score(evidence: dict[str, Any], worth_building: float) -> float:
    reactions = int(evidence.get("reactions") or 0)
    comments = int(evidence.get("comments") or 0)
    signal = _clamp(reactions / 40) * 0.5 + _clamp(comments / 60) * 0.5
    worth_norm = _clamp(worth_building / 3.0)
    return _clamp(0.6 * worth_norm + 0.4 * signal)


def buildability_score(evidence: dict[str, Any]) -> float:
    failed = int(evidence.get("failed_pr_attempts") or 0)
    merged = int(evidence.get("merged_fixes") or 0)
    score = 0.45
    if failed:
        score += 0.25
    if merged:
        score += 0.15
    open_ratio = float(evidence.get("open_ratio") or 0)
    if open_ratio > 0.5:
        score += 0.1
    changed_files = evidence.get("changed_files")
    if isinstance(changed_files, int) and 0 < changed_files <= SMALL_PR_CHANGED_FILES:
        score += 0.1
    return _clamp(score)


def cross_surface_score(evidence: dict[str, Any]) -> float:
    surfaces = int(evidence.get("surfaces") or 0)
    score = {1: 0.30, 2: 0.65, 3: 1.0}.get(surfaces, 0.30)
    if evidence.get("failed_pr_attempts") and surfaces >= 2:
        score = min(1.0, score + 0.1)
    return score


@dataclass
class ScoredCandidate:
    priority: float
    components: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {"priority": round(self.priority, 4), **{k: round(v, 4) for k, v in self.components.items()}}


def score_candidate(
    evidence: dict[str, Any],
    unresolved: float,
    worth_building: float,
    recurring: float,
) -> ScoredCandidate:
    recurrence = _clamp(recurrence_score(evidence) * (0.6 + 0.4 * _clamp(recurring)))
    unresolved_component = _clamp(unresolved)
    demand = user_demand_score(evidence, worth_building)
    buildability = buildability_score(evidence)
    cross = cross_surface_score(evidence)

    components = {
        "recurrence": recurrence,
        "unresolved": unresolved_component,
        "user_demand": demand,
        "buildability": buildability,
        "cross_surface": cross,
    }
    priority = sum(WEIGHTS[key] * components[key] for key in WEIGHTS)
    return ScoredCandidate(priority=_clamp(priority), components=components)


def rank_candidates(candidates: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates, key=lambda c: (-float(c.get("priority", 0)), -float(c.get("worth", 0)))
    )
    ranked = []
    for position, candidate in enumerate(ordered[:top_n], start=1):
        enriched = dict(candidate)
        enriched["rank"] = position
        ranked.append(enriched)
    return ranked
