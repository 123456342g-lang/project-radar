from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from backend.app.config import Settings
from backend.app.github.client import GitHubClient
from backend.app.github.issues import summarize_reactions


def iter_pulls(client: GitHubClient, full_name: str, settings: Settings) -> Iterator[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.scan_lookback_days)).timestamp()
    params = {"state": "all", "sort": "created", "direction": "desc"}
    count = 0
    for item in client.paginate(
        f"/repos/{full_name}/pulls", params=params, max_items=settings.max_prs * 2
    ):
        created_raw = item.get("created_at") or ""
        try:
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            created = 0
        if created < cutoff:
            continue
        count += 1
        if count > settings.max_prs:
            return
        yield item


def fetch_pull_detail(client: GitHubClient, full_name: str, number: int) -> dict[str, Any]:
    return client.get_json(f"/repos/{full_name}/pulls/{number}")


def apply_pull_detail(artifact: dict[str, Any], detail: dict[str, Any]) -> None:
    artifact["changed_files"] = detail.get("changed_files")
    if detail.get("merged_at"):
        artifact["merged"] = 1
        artifact["state"] = "merged"
    artifact["reactions"] = summarize_reactions(detail)
