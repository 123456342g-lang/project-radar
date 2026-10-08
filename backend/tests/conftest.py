from __future__ import annotations

import pytest

from backend.app import config
from backend.app.db.database import init_db


@pytest.fixture()
def tmp_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("EMBEDDING_BACKEND", "tfidf")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    config.reset_settings()
    settings = config.get_settings()
    init_db()
    yield settings
    config.reset_settings()


@pytest.fixture()
def sample_artifacts():
    base = 1_700_000_000
    return [
        {
            "repo_id": 1,
            "github_id": 101,
            "kind": "issue",
            "number": 1,
            "title": "Support async callbacks",
            "body": "Please support async callbacks in the hook API",
            "author": "alice",
            "state": "open",
            "created_at": base,
            "updated_at": base + 100,
            "closed_at": None,
            "reactions": 5,
            "comments": 3,
            "merged": 0,
            "labels": "[]",
            "raw_url": "https://github.com/x/y/issues/1",
        },
        {
            "repo_id": 1,
            "github_id": 102,
            "kind": "issue",
            "number": 2,
            "title": "Callbacks block the event loop",
            "body": "Sync callbacks block the event loop, need non blocking callback API",
            "author": "bob",
            "state": "open",
            "created_at": base + 86400 * 120,
            "updated_at": base + 86400 * 121,
            "closed_at": None,
            "reactions": 2,
            "comments": 1,
            "merged": 0,
            "labels": "[]",
            "raw_url": "https://github.com/x/y/issues/2",
        },
        {
            "repo_id": 1,
            "github_id": 103,
            "kind": "pull_request",
            "number": 3,
            "title": "WIP async callback support",
            "body": "Attempt to add async callback support, fixes #1",
            "author": "carol",
            "state": "closed",
            "created_at": base + 86400 * 200,
            "updated_at": base + 86400 * 210,
            "closed_at": base + 86400 * 210,
            "reactions": 1,
            "comments": 2,
            "merged": 0,
            "labels": "[]",
            "raw_url": "https://github.com/x/y/pull/3",
        },
        {
            "repo_id": 1,
            "github_id": 104,
            "kind": "discussion",
            "number": 12,
            "title": "How to make callbacks non blocking?",
            "body": "Is there a way to run callbacks without blocking? workaround?",
            "author": "dave",
            "state": "unanswered",
            "created_at": base + 86400 * 300,
            "updated_at": base + 86400 * 300,
            "closed_at": None,
            "reactions": 4,
            "comments": 3,
            "merged": 0,
            "labels": '["Q&A"]',
            "raw_url": "",
        },
        {
            "repo_id": 1,
            "github_id": 105,
            "kind": "issue",
            "number": 4,
            "title": "Typo in readme installation section",
            "body": "Docs typo: pip install exmaple is wrong",
            "author": "erin",
            "state": "closed",
            "created_at": base + 86400 * 40,
            "updated_at": base + 86400 * 41,
            "closed_at": base + 86400 * 41,
            "reactions": 0,
            "comments": 0,
            "merged": 0,
            "labels": '["documentation"]',
            "raw_url": "https://github.com/x/y/issues/4",
        },
    ]
