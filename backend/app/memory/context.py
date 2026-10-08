from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from backend.app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = {
    "repo_profile": {},
    "confirmed_problem_clusters": [],
    "rejected_clusters": [],
    "solved_patterns": [],
    "maintainer_preferences": [],
    "known_non_goals": [],
    "maintainer_signal": "unclear",
    "user_feedback": [],
}

FEEDBACK_KINDS = {"confirm", "split", "solved", "minor"}


def _safe_name(full_name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", full_name)


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())[:120]


class ProjectContext:
    def __init__(self, full_name: str):
        self.full_name = full_name
        settings = get_settings()
        self.path: Path = settings.context_dir / f"{_safe_name(full_name)}.json"
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                merged = dict(DEFAULT_TEMPLATE)
                merged.update(payload)
                return merged
            except (ValueError, OSError) as exc:
                logger.warning("Could not load context for %s: %s", self.full_name, exc)
        return dict(DEFAULT_TEMPLATE)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def add_feedback(
        self, problem_id: int, kind: str, note: str = "", title: str = ""
    ) -> dict[str, Any]:
        if kind not in FEEDBACK_KINDS:
            raise ValueError(f"feedback kind must be one of {sorted(FEEDBACK_KINDS)}")
        entry = {
            "problem_id": problem_id,
            "title": title,
            "title_key": normalize_title(title),
            "kind": kind,
            "note": note,
            "timestamp": time.time(),
        }
        history = list(self.data.get("user_feedback") or [])
        history.append(entry)
        self.data["user_feedback"] = history[-200:]

        if kind == "confirm":
            confirmed = list(self.data.get("confirmed_problem_clusters") or [])
            if problem_id not in confirmed:
                confirmed.append(problem_id)
            self.data["confirmed_problem_clusters"] = confirmed[-100:]
        elif kind in ("split", "solved"):
            rejected = list(self.data.get("rejected_clusters") or [])
            if problem_id not in rejected:
                rejected.append(problem_id)
            self.data["rejected_clusters"] = rejected[-100:]
        self.save()
        return entry

    def set_repo_profile(self, profile: dict[str, Any]) -> None:
        self.data["repo_profile"] = profile
        self.save()

    def add_non_goal(self, text: str) -> None:
        goals = list(self.data.get("known_non_goals") or [])
        if text not in goals:
            goals.append(text)
        self.data["known_non_goals"] = goals
        self.save()

    def rejected_ids(self) -> set[int]:
        return {int(x) for x in (self.data.get("rejected_clusters") or [])}

    def confirmed_ids(self) -> set[int]:
        return {int(x) for x in (self.data.get("confirmed_problem_clusters") or [])}

    def _feedback_titles(self, kinds: tuple[str, ...]) -> set[str]:
        return {
            entry["title_key"]
            for entry in (self.data.get("user_feedback") or [])
            if entry.get("kind") in kinds and entry.get("title_key")
        }

    def rejected_titles(self) -> set[str]:
        return self._feedback_titles(("split", "solved"))

    def confirmed_titles(self) -> set[str]:
        return self._feedback_titles(("confirm",))

    def summary(self) -> dict[str, Any]:
        return {
            "known_non_goals": self.data.get("known_non_goals") or [],
            "maintainer_signal": self.data.get("maintainer_signal", "unclear"),
            "maintainer_preferences": self.data.get("maintainer_preferences") or [],
            "confirmed_count": len(self.data.get("confirmed_problem_clusters") or []),
            "rejected_count": len(self.data.get("rejected_clusters") or []),
            "feedback_count": len(self.data.get("user_feedback") or []),
        }


REJECTION_MARKERS = (
    "wontfix",
    "won't fix",
    "will not fix",
    "not planned",
    "out of scope",
    "by design",
    "not going to",
    "we won't",
    "not a bug",
)


def detect_maintainer_signal(artifacts: list[dict[str, Any]]) -> str:
    rejection_hits = 0
    support_hits = 0
    for artifact in artifacts:
        labels = str(artifact.get("labels") or "").lower()
        if "wontfix" in labels or "declined" in labels or "invalid" in labels:
            rejection_hits += 2
        body = str(artifact.get("body") or "").lower()
        for marker in REJECTION_MARKERS:
            if marker in body:
                rejection_hits += 1
        if artifact.get("kind") == "pull_request" and artifact.get("merged"):
            support_hits += 2
    if rejection_hits >= 2:
        return "reject"
    if support_hits >= 1 and rejection_hits == 0:
        return "support"
    if rejection_hits == 1:
        return "unclear"
    return "neutral"
