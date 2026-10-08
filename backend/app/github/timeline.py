from __future__ import annotations

import json
import logging
from typing import Any

from backend.app.github.client import GitHubClient, GitHubError

logger = logging.getLogger(__name__)


def fetch_issue_timeline(
    client: GitHubClient, full_name: str, issue_number: int, max_items: int = 100
) -> list[dict[str, Any]]:
    try:
        items = list(
            client.paginate(
                f"/repos/{full_name}/issues/{issue_number}/timeline", max_items=max_items
            )
        )
    except GitHubError as exc:
        logger.warning("Timeline fetch failed for %s#%s: %s", full_name, issue_number, exc)
        return []
    return items


def extract_linked_prs(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    linked: list[dict[str, Any]] = []
    for event in timeline:
        event_type = event.get("event")
        if event_type in ("cross-referenced", "connected", "referenced"):
            source = (event.get("source") or {}).get("issue") or {}
            if not source.get("pull_request"):
                continue
            pull = source.get("pull_request") or {}
            merged = bool(pull.get("merged_at") or source.get("merged_at"))
            linked.append(
                {
                    "number": source.get("number"),
                    "state": source.get("state"),
                    "merged": merged,
                    "title": source.get("title"),
                    "url": source.get("html_url"),
                }
            )
        elif event_type == "closed" and event.get("commit_id"):
            linked.append({"commit": event.get("commit_id"), "merged": True})
    return linked


def load_fix_refs(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    raw = artifact.get("fix_refs") or "[]"
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []
