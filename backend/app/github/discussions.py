from __future__ import annotations

import logging
from typing import Any

from backend.app.config import Settings
from backend.app.github.client import GitHubClient, GitHubError
from backend.app.github.issues import parse_iso

logger = logging.getLogger(__name__)

DISCUSSIONS_QUERY = """
query($owner: String!, $name: String!, $first: Int!) {
  repository(owner: $owner, name: $name) {
    discussions(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        number
        title
        body
        createdAt
        updatedAt
        closed
        answerChosenAt
        category { name }
        reactions { totalCount }
        comments { totalCount }
        author { login }
      }
    }
  }
}
"""


def iter_discussions(
    client: GitHubClient, full_name: str, settings: Settings
) -> list[dict[str, Any]]:
    if not settings.github_token:
        logger.warning("Discussions require GITHUB_TOKEN; skipping discussions collection")
        return []
    owner, _, name = full_name.partition("/")
    try:
        data = client.graphql(
            DISCUSSIONS_QUERY,
            {"owner": owner, "name": name, "first": min(settings.max_discussions, 100)},
        )
    except GitHubError as exc:
        logger.warning("Discussions collection failed: %s", exc)
        return []
    nodes = (((data or {}).get("repository") or {}).get("discussions") or {}).get("nodes") or []
    results = []
    for node in nodes:
        if not node:
            continue
        node["created_ts"] = parse_iso(node.get("createdAt"))
        node["updated_ts"] = parse_iso(node.get("updatedAt"))
        node["answered"] = bool(node.get("answerChosenAt"))
        results.append(node)
    return results[: settings.max_discussions]
