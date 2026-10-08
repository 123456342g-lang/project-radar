from __future__ import annotations

import json

import httpx
import pytest

from backend.app.judge.jev import (
    JevJudge,
    HeuristicJudge,
    build_state,
)
from backend.app.judge.schemas import PROBLEM_TYPES


def _context():
    return {
        "problem_title": "Missing async callback support",
        "keywords": ["async", "callback", "event", "loop"],
        "cohesion": 0.62,
        "evidence": {
            "independent_authors": 8,
            "issues": 9,
            "discussions": 3,
            "span_days": 330,
            "reactions": 20,
            "comments": 40,
            "open_ratio": 0.8,
            "merged_fixes": 0,
            "failed_pr_attempts": 1,
            "surfaces": 3,
        },
        "resolution_signals": {"has_merged_fix": False, "has_failed_attempt": True},
        "artifacts": [
            {"kind": "issue", "number": 31, "title": "Need async callbacks", "body": "support async"},
            {"kind": "issue", "number": 87, "title": "Event loop blocked", "body": "blocking"},
        ],
    }


def test_heuristic_judge_returns_in_range_values():
    judgment = HeuristicJudge().judge(_context())
    assert judgment.judge_mode == "heuristic"
    assert 0.0 <= judgment.same_problem <= 1.0
    assert 0.0 <= judgment.unresolved <= 1.0
    assert 0.0 <= judgment.worth_building <= 3.0
    assert judgment.problem_type in PROBLEM_TYPES


def test_heuristic_judge_is_deterministic():
    first = HeuristicJudge().judge(_context())
    second = HeuristicJudge().judge(_context())
    assert first == second


def test_heuristic_unresolved_drops_when_merged_fix_exists():
    context = _context()
    context["evidence"] = {**context["evidence"], "merged_fixes": 2, "open_ratio": 0.1}
    judgment = HeuristicJudge().judge(context)
    baseline = HeuristicJudge().judge(_context())
    assert judgment.unresolved < baseline.unresolved


def test_build_state_includes_artifacts_and_truncates():
    context = _context()
    state = build_state(context)
    assert "issue #31" in state
    assert "Missing async callback support" in state
    assert len(state) <= 24000


def test_build_state_truncates_huge_context():
    context = _context()
    context["artifacts"] = [
        {"kind": "issue", "number": i, "title": "x" * 300, "body": "y" * 500}
        for i in range(100)
    ]
    assert len(build_state(context)) <= 24000


def test_jev_judge_parses_api_response(tmp_settings, monkeypatch):
    payload = {
        "answers": {
            "same_problem": {"noul": 0.94},
            "recurring_independent": {"noul": 0.88},
            "still_unresolved": {"noul": 0.97},
            "worth_building": {"score": 2.73, "confidence": 0.8},
            "problem_type": {"choice": "missing_feature"},
        }
    }

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == tmp_settings.jev_api_url
        assert headers["Authorization"].startswith("Bearer ")
        body = json
        assert body["model"] == "jev-latest"
        assert "same_problem" in body["questions"]
        assert body["questions"]["same_problem"]["type"] == "noul"
        assert body["questions"]["worth_building"]["type"] == "score"
        assert body["questions"]["problem_type"]["type"] == "choice"
        request = httpx.Request("POST", url)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr("backend.app.judge.jev.httpx.post", fake_post)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    from backend.app import config

    config.reset_settings()
    settings = config.get_settings()

    judgment = JevJudge(settings).judge(_context())
    assert judgment.judge_mode == "jev"
    assert judgment.same_problem == pytest.approx(0.94)
    assert judgment.unresolved == pytest.approx(0.97)
    assert judgment.worth_building == pytest.approx(2.73)
    assert judgment.problem_type == "missing_feature"
    assert judgment.confidence > 0
    config.reset_settings()


def test_jev_judge_raises_on_http_error(tmp_settings, monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        request = httpx.Request("POST", url)
        return httpx.Response(500, text="boom", request=request)

    monkeypatch.setattr("backend.app.judge.jev.httpx.post", fake_post)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    from backend.app import config

    config.reset_settings()
    settings = config.get_settings()
    with pytest.raises(Exception):
        JevJudge(settings).judge(_context())
    config.reset_settings()


def test_jev_answers_support_flat_payload():
    from backend.app.judge.jev import _choice, _noul, _score

    flat = {"same_problem": 0.5, "worth_building": {"value": 1.0}, "problem_type": "bug_fix"}
    assert _noul(flat, "same_problem", 0.0) == 0.5
    assert _score(flat, "worth_building", 0.0) == 1.0
    assert _choice(flat, "problem_type") == "bug_fix"
    assert json.dumps(flat)
