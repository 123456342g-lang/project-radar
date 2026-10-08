from __future__ import annotations

from backend.app.ranking.evidence import build_evidence, resolution_hints
from backend.app.ranking.score import (
    WEIGHTS,
    buildability_score,
    cross_surface_score,
    rank_candidates,
    recurrence_score,
    score_candidate,
)


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_build_evidence_counts_surfaces_and_authors(sample_artifacts):
    now = sample_artifacts[-1]["created_at"] + 86400 * 400
    evidence = build_evidence(sample_artifacts, now)
    assert evidence.issues == 3
    assert evidence.pull_requests == 1
    assert evidence.discussions == 1
    assert evidence.surfaces == 3
    assert evidence.cross_surface is True
    assert evidence.independent_authors == 5
    assert evidence.span_days >= 300
    assert evidence.failed_pr_attempts == 1


def test_resolution_hints_flags_failed_pr(sample_artifacts):
    hints = resolution_hints(sample_artifacts)
    assert hints["has_failed_attempt"] is True
    assert hints["has_merged_fix"] is False
    assert hints["failed_pull_requests"][0]["number"] == 3


def test_recurrence_increases_with_authors():
    few = {"independent_authors": 1, "issues": 1, "discussions": 0, "span_days": 5}
    many = {"independent_authors": 12, "issues": 15, "discussions": 5, "span_days": 400}
    assert recurrence_score(many) > recurrence_score(few)


def test_recurrence_is_clamped():
    huge = {"independent_authors": 500, "issues": 500, "discussions": 99, "span_days": 9999}
    assert recurrence_score(huge) <= 1.0


def test_cross_surface_score_monotonic():
    one = cross_surface_score({"surfaces": 1})
    two = cross_surface_score({"surfaces": 2})
    three = cross_surface_score({"surfaces": 3})
    assert one < two < three


def test_buildability_bonus_for_failed_attempt():
    plain = buildability_score({"failed_pr_attempts": 0, "merged_fixes": 0, "open_ratio": 0.2})
    attempted = buildability_score({"failed_pr_attempts": 1, "merged_fixes": 0, "open_ratio": 0.6})
    assert attempted > plain


def test_score_candidate_prefers_unresolved_recurring_problem():
    strong_evidence = {
        "independent_authors": 12,
        "issues": 14,
        "discussions": 4,
        "span_days": 380,
        "reactions": 30,
        "comments": 50,
        "surfaces": 3,
        "failed_pr_attempts": 1,
        "merged_fixes": 0,
        "open_ratio": 0.8,
    }
    weak_evidence = {
        "independent_authors": 1,
        "issues": 2,
        "discussions": 0,
        "span_days": 10,
        "reactions": 0,
        "comments": 1,
        "surfaces": 1,
        "failed_pr_attempts": 0,
        "merged_fixes": 0,
        "open_ratio": 1.0,
    }
    strong = score_candidate(strong_evidence, unresolved=0.95, worth_building=2.8, recurring=0.9)
    weak = score_candidate(weak_evidence, unresolved=0.9, worth_building=0.5, recurring=0.4)
    assert strong.priority > weak.priority
    assert 0.0 <= weak.priority <= 1.0


def test_rank_candidates_orders_and_ranks():
    candidates = [
        {"priority": 0.2, "worth": 1.0},
        {"priority": 0.9, "worth": 2.0},
        {"priority": 0.5, "worth": 3.0},
    ]
    ranked = rank_candidates(candidates, top_n=2)
    assert len(ranked) == 2
    assert ranked[0]["priority"] == 0.9
    assert ranked[0]["rank"] == 1
    assert ranked[1]["rank"] == 2
