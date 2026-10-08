from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from backend.app.config import Settings, get_settings
from backend.app.judge.prompts import QUESTIONS
from backend.app.judge.schemas import (
    PROBLEM_TYPE,
    RECURRING,
    SAME_PROBLEM,
    UNRESOLVED,
    WORTH_BUILDING,
    Judgment,
)

logger = logging.getLogger(__name__)

MAX_STATE_CHARS = 24000


class JevError(RuntimeError):
    pass


def build_state(context: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("problem_title", "keywords", "evidence", "recent_activity", "resolution_signals"):
        if key in context and context[key]:
            parts.append(f"{key}: {context[key]}")
    artifacts = context.get("artifacts") or []
    for artifact in artifacts[:14]:
        kind = artifact.get("kind", "issue")
        number = artifact.get("number")
        title = (artifact.get("title") or "").strip()
        body = (artifact.get("body") or "").strip()[:500]
        parts.append(f"{kind} #{number}: {title}\n{body}")
    state = "\n\n".join(parts)
    return state[:MAX_STATE_CHARS]


class JevJudge:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.model = self.settings.jev_model

    def judge(self, context: dict[str, Any]) -> Judgment:
        payload = {
            "model": self.model,
            "state": build_state(context),
            "questions": QUESTIONS,
        }
        try:
            response = httpx.post(
                self.settings.jev_api_url,
                headers={
                    "Authorization": f"Bearer {self.settings.typesafe_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.settings.http_timeout,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise JevError(f"Jev API request failed: {exc}") from exc
        except ValueError as exc:
            raise JevError(f"Jev API returned invalid JSON: {exc}") from exc

        answers = _extract_answers(data)
        judgment = Judgment(
            same_problem=_noul(answers, SAME_PROBLEM, default=0.5),
            recurring=_noul(answers, RECURRING, default=0.5),
            unresolved=_noul(answers, UNRESOLVED, default=0.5),
            worth_building=_score(answers, WORTH_BUILDING, default=1.5),
            problem_type=_choice(answers, PROBLEM_TYPE),
            judge_mode="jev",
            model=self.model,
            raw=answers,
        )
        return judgment


def _extract_answers(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        for key in ("answers", "result", "results", "questions", "output"):
            inner = data.get(key)
            if isinstance(inner, dict):
                return inner
        return data
    return {}


def _entry(answers: dict[str, Any], name: str) -> dict[str, Any]:
    value = answers.get(name)
    if isinstance(value, dict):
        return value
    if value is not None:
        return {"value": value}
    return {}


def _noul(answers: dict[str, Any], name: str, default: float) -> float:
    entry = _entry(answers, name)
    for key in ("noul", "probability", "value", "score", "p"):
        if key in entry:
            try:
                return min(1.0, max(0.0, float(entry[key])))
            except (TypeError, ValueError):
                continue
    return default


def _score(answers: dict[str, Any], name: str, default: float) -> float:
    entry = _entry(answers, name)
    for key in ("score", "expected_score", "value", "mean", "noul"):
        if key in entry:
            try:
                return float(entry[key])
            except (TypeError, ValueError):
                continue
    return default


def _choice(answers: dict[str, Any], name: str) -> str:
    entry = _entry(answers, name)
    for key in ("choice", "value", "label", "selected", "answer"):
        if key in entry:
            text = str(entry[key]).strip().lower().replace(" ", "_")
            if text in QUESTIONS[PROBLEM_TYPE]["criteria"]:
                return text
    return "other"


class HeuristicJudge:
    """Offline fallback: rule-based judgments from evidence statistics."""

    mode = "heuristic"

    def judge(self, context: dict[str, Any]) -> Judgment:
        evidence = context.get("evidence") or {}
        artifacts = context.get("artifacts") or []
        coherence = float(context.get("cohesion") or 0.0)

        same_problem = min(0.98, 0.40 + coherence * 0.8)
        independent_authors = int(evidence.get("independent_authors") or 0)
        issue_count = int(evidence.get("issues") or 0)
        span_days = int(evidence.get("span_days") or 0)
        recurring = 0.35 + min(0.4, independent_authors * 0.06) + min(0.2, issue_count * 0.04)
        if span_days > 90:
            recurring += 0.1
        recurring = min(0.97, recurring)

        unresolved = self._unresolved_score(evidence, artifacts)
        worth = self._worth_score(evidence, artifacts)
        problem_type = self._classify(artifacts)
        return Judgment(
            same_problem=round(same_problem, 4),
            recurring=round(recurring, 4),
            unresolved=round(unresolved, 4),
            worth_building=round(worth, 4),
            problem_type=problem_type,
            judge_mode="heuristic",
            model="heuristic-rules-v1",
            raw={},
        )

    @staticmethod
    def _unresolved_score(evidence: dict[str, Any], artifacts: list[dict]) -> float:
        open_ratio = float(evidence.get("open_ratio") or 0.0)
        merged_fixes = int(evidence.get("merged_fixes") or 0)
        closed_without_fix = int(evidence.get("closed_without_fix") or 0)
        score = 0.45 + open_ratio * 0.4
        if merged_fixes > 0:
            score -= 0.45 * min(merged_fixes, 3)
        if closed_without_fix > 0:
            score += 0.1
        if evidence.get("failed_pr_attempts"):
            score += 0.08
        return min(0.98, max(0.05, score))

    @staticmethod
    def _worth_score(evidence: dict[str, Any], artifacts: list[dict]) -> float:
        authors = int(evidence.get("independent_authors") or 0)
        surfaces = int(evidence.get("surfaces") or 1)
        reactions = int(evidence.get("reactions") or 0)
        score = 0.6 + min(1.2, authors * 0.18) + min(0.7, surfaces * 0.25)
        score += min(0.5, reactions * 0.03)
        if evidence.get("failed_pr_attempts"):
            score += 0.25
        return round(min(3.0, score), 4)

    @staticmethod
    def _classify(artifacts: list[dict]) -> str:
        text = " ".join(
            f"{a.get('title', '')} {a.get('body', '')}".lower() for a in artifacts[:15]
        )
        rules: list[tuple[str, list[str]]] = [
            ("performance", ["slow", "performance", "latency", "memory leak", "oom", "timeout"]),
            ("documentation", ["docs", "documentation", "readme", "typo", "example missing"]),
            ("bug_fix", ["crash", "exception", "traceback", "incorrect", "wrong result", "data loss"]),
            ("integration", ["webhook", "oauth", "slack", "database", "postgres", "redis", "sdk"]),
            ("developer_experience", ["cli", "error message", "onboarding", "dx", "config file"]),
            ("workflow", ["manual", "workaround", "every time", "step by step"]),
            ("architecture", ["refactor", "rewrite", "redesign", "monolith", "breaking change"]),
            ("missing_feature", ["support", "add support", "feature request", "missing", "please add"]),
        ]
        best_type, best_hits = "other", 0
        for problem_type, keywords in rules:
            hits = sum(1 for kw in keywords if kw in text)
            if hits > best_hits:
                best_type, best_hits = problem_type, hits
        return best_type


def get_judge(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.typesafe_api_key:
        return JevJudge(settings)
    logger.info("TYPESAFE_API_KEY not set; using offline heuristic judge")
    return HeuristicJudge()
