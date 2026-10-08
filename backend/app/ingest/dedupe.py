from __future__ import annotations

import re
from typing import Any

NON_PROBLEM_LABELS = {"duplicate", "invalid", "spam", "wontfix", "can't reproduce"}
BOT_AUTHORS = {"dependabot[bot]", "renovate[bot]", "github-actions[bot]", "codecov[bot]"}
LOW_SIGNAL_TITLE_RE = re.compile(
    r"^(bump|update dependencies|release v?\d|\[bot\])", re.IGNORECASE
)


def _labels(artifact: dict[str, Any]) -> list[str]:
    raw = artifact.get("labels") or "[]"
    if isinstance(raw, list):
        return [str(x).lower() for x in raw]
    return [x.lower() for x in re.findall(r'"([^"]*)"', raw)]


def is_noise(artifact: dict[str, Any]) -> bool:
    author = (artifact.get("author") or "").lower()
    if author in BOT_AUTHORS:
        return True
    title = (artifact.get("title") or "").strip()
    if not title or LOW_SIGNAL_TITLE_RE.search(title):
        return True
    labels = set(_labels(artifact))
    if labels & {l.lower() for l in NON_PROBLEM_LABELS}:
        return True
    if artifact.get("kind") == "pull_request" and artifact.get("merged"):
        return False
    return False


def content_key(artifact: dict[str, Any]) -> str:
    title = re.sub(r"\W+", "", (artifact.get("title") or "").lower())
    body = re.sub(r"\W+", "", (artifact.get("body") or "").lower())[:200]
    return f"{title}:{body}"


def dedupe(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    for artifact in artifacts:
        if is_noise(artifact):
            continue
        key = (str(artifact.get("author")), content_key(artifact))
        if key in seen and not (artifact.get("kind") == "pull_request"):
            continue
        seen[key] = artifact
        result.append(artifact)
    return result
