from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import httpx

from backend.app.config import Settings, get_settings

logger = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"
RATE_LIMIT_REMAINING_KEY = "x-ratelimit-remaining"
RATE_LIMIT_RESET_KEY = "x-ratelimit-reset"
MIN_REQUESTS_LEFT = 5


class GitHubError(RuntimeError):
    pass


class RateLimitExceeded(GitHubError):
    def __init__(self, reset_at: float):
        self.reset_at = reset_at
        wait = max(0, int(reset_at - time.time()))
        super().__init__(f"GitHub rate limit reached, resets in {wait}s")


class GitHubClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "project-radar",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        self._client = httpx.Client(
            headers=headers, timeout=self.settings.http_timeout, follow_redirects=True
        )
        self.requests_left: int | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _check_budget(self) -> None:
        if self.requests_left is not None and self.requests_left < MIN_REQUESTS_LEFT:
            raise RateLimitExceeded(time.time() + 60)

    def _track(self, response: httpx.Response) -> None:
        remaining = response.headers.get(RATE_LIMIT_REMAINING_KEY)
        if remaining is not None and remaining.isdigit():
            self.requests_left = int(remaining)

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code in (403, 429) and RATE_LIMIT_REMAINING_KEY in response.headers:
            reset_raw = response.headers.get(RATE_LIMIT_RESET_KEY, "0")
            reset_at = float(reset_raw) if reset_raw.isdigit() else time.time() + 60
            if response.headers.get(RATE_LIMIT_REMAINING_KEY, "1") == "0":
                raise RateLimitExceeded(reset_at)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GitHubError(
                f"GitHub API {response.status_code} for {response.request.url}: "
                f"{response.text[:300]}"
            ) from exc

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._check_budget()
        response = self._client.get(f"{API_ROOT}{path}", params=params)
        self._track(response)
        self._raise_for_status(response)
        return response.json()

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, max_items: int = 500
    ) -> Iterator[dict[str, Any]]:
        query = dict(params or {})
        query.setdefault("per_page", 100)
        page = 1
        yielded = 0
        while yielded < max_items:
            self._check_budget()
            response = self._client.get(f"{API_ROOT}{path}", params={**query, "page": page})
            self._track(response)
            self._raise_for_status(response)
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                return
            for item in batch:
                yield item
                yielded += 1
                if yielded >= max_items:
                    return
            if len(batch) < query["per_page"]:
                return
            page += 1

    def graphql(self, query: str, variables: dict[str, Any]) -> Any:
        self._check_budget()
        response = self._client.post(
            GRAPHQL_URL, json={"query": query, "variables": variables}
        )
        self._track(response)
        self._raise_for_status(response)
        payload = response.json()
        if payload.get("errors"):
            raise GitHubError(f"GraphQL errors: {payload['errors']}")
        return payload.get("data")
