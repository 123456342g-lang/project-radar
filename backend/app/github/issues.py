from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from backend.app.config import Settings, get_settings
from backend.app.github.client import GitHubClient


def parse_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fetch_repo(client: GitHubClient, full_name: str) -> dict[str, Any]:
    return client.get_json(f"/repos/{full_name}")


def _lookback_cutoff(settings: Settings) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=settings.scan_lookback_days)


def iter_issues(client: GitHubClient, full_name: str, settings: Settings) -> Iterator[dict]:
    cutoff = _lookback_cutoff(settings).timestamp()
    seen: set[int] = set()
    for state in ("open", "closed"):
        params: dict[str, Any] = {"state": state, "sort": "updated", "direction": "desc"}
        if state == "closed":
            since = _lookback_cutoff(settings).isoformat()
            params["since"] = since
        count = 0
        for item in client.paginate(
            f"/repos/{full_name}/issues", params=params, max_items=settings.max_issues
        ):
            if "pull_request" in item:
                continue
            created = parse_iso(item.get("created_at")) or 0
            if state == "closed" and created < cutoff:
                continue
            if item["number"] in seen:
                continue
            seen.add(item["number"])
            count += 1
            if count > settings.max_issues:
                return
            yield item


def fetch_issue_comments(
    client: GitHubClient, full_name: str, issue_number: int, limit: int = 50
) -> list[dict]:
    return list(
        client.paginate(
            f"/repos/{full_name}/issues/{issue_number}/comments", max_items=limit
        )
    )


def summarize_reactions(item: dict) -> int:
    reactions = item.get("reactions") or {}
    if isinstance(reactions, dict):
        total = reactions.get("total_count")
        if isinstance(total, int):
            return total
    return int(item.get("reactions", 0) or 0)
