from __future__ import annotations

import dataclasses
import json
import time
from datetime import datetime, timedelta, timezone

from backend.app.db.database import db_session, fetch_all, fetch_one
from backend.app.memory.context import ProjectContext
from backend.app.pipeline import run_scan

NOW = datetime.now(timezone.utc)


def with_token(settings):
    return dataclasses.replace(settings, github_token="fake-token-for-tests")


def iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def make_issue(number, title, body, author, days_ago, state="open", comments=0, labels=None):
    created = iso(days_ago)
    item = {
        "id": 10000 + number,
        "number": number,
        "title": title,
        "body": body,
        "user": {"login": author},
        "state": state,
        "created_at": created,
        "updated_at": created,
        "closed_at": iso(days_ago - 5) if state == "closed" else None,
        "comments": comments,
        "labels": [{"name": lab} for lab in (labels or [])],
        "html_url": f"https://github.com/octo/demo/issues/{number}",
        "reactions": {"total_count": max(1, comments)},
    }
    return item


ISSUES = [
    make_issue(101, "Support async callbacks in hook API", "We need async callback support for coroutines", "alice", 400, comments=2),
    make_issue(102, "Callbacks block the event loop", "Blocking callbacks freeze the event loop entirely", "bob", 300, comments=1),
    make_issue(103, "Need non-blocking callback API", "Callbacks should run without blocking, add async support", "carol", 200),
    make_issue(104, "Async callback support?", "Is async callback supported? coroutine callbacks please", "dave", 100),
    make_issue(201, "Typo in install docs", "readme installation example is wrong", "erin", 50),
    make_issue(202, "Docs example broken", "documentation install example fails to run as documented", "frank", 30, state="closed"),
    make_issue(301, "Bump lodash from 4 to 5", "bumps lodash", "dependabot[bot]", 10),
    make_issue(302, "Same async callback thing", "duplicate of 101", "alice", 90, labels=["duplicate"]),
]

PULLS = [
    {
        "id": 20001,
        "number": 501,
        "title": "WIP async callback implementation",
        "body": "Attempt to add async callbacks, tries to fix #101",
        "user": {"login": "carol"},
        "state": "closed",
        "created_at": iso(150),
        "updated_at": iso(140),
        "closed_at": iso(140),
        "merged_at": None,
        "comments": 2,
        "html_url": "https://github.com/octo/demo/pull/501",
        "reactions": {"total_count": 2},
    },
    {
        "id": 20002,
        "number": 502,
        "title": "Fix docs example",
        "body": "Closes #202",
        "user": {"login": "frank"},
        "state": "closed",
        "created_at": iso(28),
        "updated_at": iso(27),
        "closed_at": iso(27),
        "merged_at": iso(27),
        "comments": 0,
        "html_url": "https://github.com/octo/demo/pull/502",
        "reactions": {"total_count": 0},
    },
]

DISCUSSIONS = {
    "repository": {
        "discussions": {
            "nodes": [
                {
                    "number": 12,
                    "title": "How to run callbacks without blocking",
                    "body": "Looking for an async callback workaround, does one exist?",
                    "createdAt": iso(60),
                    "updatedAt": iso(60),
                    "closed": False,
                    "answerChosenAt": None,
                    "category": {"name": "Q&A"},
                    "reactions": {"totalCount": 4},
                    "comments": {"totalCount": 3},
                    "author": {"login": "grace"},
                }
            ]
        }
    }
}

COMMENTS = {
    101: [
        {"user": {"login": "bob"}, "body": "+1, we need this daily"},
        {"user": {"login": "carol"}, "body": "same here, blocks our pipeline"},
    ],
    102: [{"user": {"login": "alice"}, "body": "we hit this too"}],
}

REPO = {
    "full_name": "octo/demo",
    "description": "Demo repo",
    "stargazers_count": 1234,
    "open_issues_count": 42,
    "default_branch": "main",
    "language": "Python",
    "html_url": "https://github.com/octo/demo",
    "pushed_at": iso(1),
}


class FakeGitHubClient:
    def __init__(self, settings=None):
        self.settings = settings
        self.calls = []
        self.requests_left = 5000

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def close(self):
        return None

    def get_json(self, path, params=None):
        self.calls.append(path)
        if path == "/repos/octo/demo":
            return REPO
        if path == "/repos/octo/demo/pulls/501":
            return {
                "number": 501,
                "merged_at": None,
                "changed_files": 4,
                "additions": 120,
                "deletions": 10,
                "reactions": {"total_count": 2},
            }
        if path == "/repos/octo/demo/pulls/502":
            return {
                "number": 502,
                "merged_at": iso(27),
                "changed_files": 1,
                "additions": 3,
                "deletions": 1,
                "reactions": {"total_count": 0},
            }
        raise AssertionError(f"unexpected GET {path}")

    def paginate(self, path, params=None, max_items=500):
        self.calls.append(path)
        params = params or {}
        if path.endswith("/issues") and "/pulls" not in path:
            wanted = params.get("state", "open")
            for item in ISSUES:
                if "pull_request" in item:
                    continue
                if wanted == "open" and item["state"] != "open":
                    continue
                if wanted == "closed" and item["state"] != "closed":
                    continue
                yield item
        elif path.endswith("/pulls"):
            yield from PULLS
        elif "/comments" in path:
            number = int(path.rstrip("/").split("/")[-2])
            yield from COMMENTS.get(number, [])
        elif "/timeline" in path:
            number = int(path.rstrip("/").split("/")[-2])
            if number == 202:
                yield {
                    "event": "cross-referenced",
                    "source": {
                        "issue": {
                            "number": 502,
                            "state": "closed",
                            "title": "Fix docs example",
                            "html_url": "https://github.com/octo/demo/pull/502",
                            "pull_request": {"merged_at": iso(27)},
                        }
                    },
                }
        else:
            raise AssertionError(f"unexpected paginate {path}")

    def graphql(self, query, variables):
        self.calls.append("graphql")
        return DISCUSSIONS


def test_run_scan_end_to_end(tmp_settings, monkeypatch):
    from backend.app import pipeline

    monkeypatch.setattr(pipeline, "GitHubClient", FakeGitHubClient)
    stages = []
    result = run_scan(
        "octo/demo",
        progress_callback=lambda stage, progress: stages.append((stage, round(progress, 3))),
        settings=with_token(tmp_settings),
    )

    assert result.repo["full_name"] == "octo/demo"
    assert result.judge_mode == "heuristic"
    assert len(result.artifacts) == 9, "bot + duplicate must be filtered"

    assert len(result.candidates) >= 2, "async cluster and docs cluster expected"
    assert len(result.top) >= 1

    top_titles = " ".join(c["title"].lower() for c in result.top)
    assert "callback" in top_titles or "async" in top_titles

    async_top = next(
        c for c in result.top if "callback" in c["title"].lower() or "async" in c["title"].lower()
    )
    evidence = async_top["evidence"]
    assert evidence["issues"] >= 4
    assert evidence["independent_authors"] >= 4
    assert evidence["span_days"] > 250
    assert evidence["failed_pr_attempts"] >= 1
    assert evidence["surfaces"] >= 2
    assert async_top["judgment"]["judge_mode"] == "heuristic"
    assert async_top["priority"] > 0.3
    assert async_top["evidence_chain"], "evidence chain must be rendered"
    assert async_top["why_exists"]
    assert async_top["why_unresolved"]
    assert async_top["minimal_fix"]

    stages_seen = {stage for stage, _ in stages}
    assert {"collect", "normalize", "cluster", "judge", "rank"} <= stages_seen
    assert stages[-1][1] == 1.0


def test_run_scan_persists_to_database(tmp_settings, monkeypatch):
    from backend.app import pipeline

    monkeypatch.setattr(pipeline, "GitHubClient", FakeGitHubClient)
    run_scan("octo/demo", settings=with_token(tmp_settings))

    with db_session() as conn:
        repo = fetch_one(conn, "SELECT * FROM repositories WHERE full_name=?", ("octo/demo",))
        assert repo is not None
        artifacts = fetch_all(conn, "SELECT * FROM artifacts WHERE repo_id=?", (repo["id"],))
        assert len(artifacts) == 9
        problems = fetch_all(conn, "SELECT * FROM problems WHERE repo_id=?", (repo["id"],))
        assert problems
        ranked = [p for p in problems if p["rank"] is not None]
        assert len(ranked) >= 1
        judgments = fetch_all(conn, "SELECT * FROM judgments")
        assert len(judgments) == len(problems)
        links = fetch_all(
            conn,
            "SELECT * FROM problem_artifacts WHERE problem_id=?",
            (problems[0]["id"],),
        )
        assert links


def test_run_scan_feedback_downranks_next_scan(tmp_settings, monkeypatch):
    from backend.app import pipeline

    monkeypatch.setattr(pipeline, "GitHubClient", FakeGitHubClient)
    first = run_scan("octo/demo", settings=with_token(tmp_settings))
    rejected_title = first.top[0]["title"]

    context = ProjectContext("octo/demo")
    context.add_feedback(1, "split", "not the same problem", rejected_title)

    second = run_scan("octo/demo", settings=with_token(tmp_settings))
    second_match = next(c for c in second.candidates if c["title"] == rejected_title)
    first_match = next(c for c in first.candidates if c["title"] == rejected_title)
    assert second_match["priority"] < first_match["priority"]


def test_run_scan_enriches_resolution_evidence(tmp_settings, monkeypatch):
    from backend.app import pipeline

    monkeypatch.setattr(pipeline, "GitHubClient", FakeGitHubClient)
    run_scan("octo/demo", settings=with_token(tmp_settings))

    with db_session() as conn:
        issue202 = fetch_one(
            conn,
            "SELECT * FROM artifacts WHERE kind='issue' AND number=202",
        )
        pr502 = fetch_one(
            conn,
            "SELECT * FROM artifacts WHERE kind='pull_request' AND number=502",
        )
    assert issue202["closed_via_fix"] == 1
    assert "502" in issue202["fix_refs"]
    assert pr502["changed_files"] == 1


def test_run_scan_writes_repo_profile(tmp_settings, monkeypatch):
    from backend.app import pipeline

    monkeypatch.setattr(pipeline, "GitHubClient", FakeGitHubClient)
    run_scan("octo/demo", settings=with_token(tmp_settings))
    context = ProjectContext("octo/demo")
    assert context.data["repo_profile"]["stars"] == 1234
    assert json.dumps(context.data)
