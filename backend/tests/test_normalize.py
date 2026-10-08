from __future__ import annotations

from backend.app.ingest.normalize import (
    artifact_from_discussion,
    artifact_from_issue,
    artifact_from_pull,
    clean_body,
    comments_blob,
    find_fix_references,
)


def test_clean_body_strips_code_and_urls():
    text = "Crash when parsing ```code block``` see https://example.com/x for details"
    cleaned = clean_body(text)
    assert "code block" not in cleaned
    assert "https" not in cleaned
    assert "Crash when parsing" in cleaned


def test_clean_body_truncates():
    cleaned = clean_body("word " * 2000, max_len=100)
    assert len(cleaned) <= 100


def test_artifact_from_issue_maps_fields():
    raw = {
        "id": 42,
        "number": 7,
        "title": "  Crash on save  ",
        "body": "It crashes",
        "user": {"login": "alice"},
        "state": "open",
        "created_at": "2025-01-02T03:04:05Z",
        "updated_at": "2025-01-03T03:04:05Z",
        "closed_at": None,
        "comments": 2,
        "labels": [{"name": "bug"}],
        "html_url": "https://github.com/x/y/issues/7",
        "reactions": {"total_count": 3},
    }
    artifact = artifact_from_issue(raw, repo_id=1)
    assert artifact["kind"] == "issue"
    assert artifact["title"] == "Crash on save"
    assert artifact["author"] == "alice"
    assert artifact["reactions"] == 3
    assert artifact["created_at"] > 0
    assert artifact["labels"] == '["bug"]'


def test_artifact_from_pull_marks_merged():
    raw = {
        "id": 99,
        "number": 11,
        "title": "Fix crash",
        "body": "Fixes #7",
        "user": {"login": "bob"},
        "state": "closed",
        "created_at": "2025-02-01T00:00:00Z",
        "updated_at": "2025-02-02T00:00:00Z",
        "closed_at": "2025-02-02T00:00:00Z",
        "merged_at": "2025-02-02T00:00:00Z",
        "comments": 0,
        "html_url": "https://github.com/x/y/pull/11",
    }
    artifact = artifact_from_pull(raw, repo_id=1)
    assert artifact["merged"] == 1
    assert artifact["state"] == "merged"


def test_artifact_from_discussion_uses_answer_state():
    node = {
        "number": 5,
        "title": "How do I configure X",
        "body": "question body",
        "author": {"login": "carol"},
        "category": {"name": "Q&A"},
        "reactions": {"totalCount": 2},
        "comments": {"totalCount": 4},
        "createdAt": "2025-03-01T00:00:00Z",
        "answered": True,
    }
    artifact = artifact_from_discussion(node, repo_id=1)
    assert artifact["kind"] == "discussion"
    assert artifact["state"] == "answered"
    assert artifact["reactions"] == 2
    assert artifact["comments"] == 4


def test_comments_blob_joins_authors():
    blob = comments_blob(
        [
            {"user": {"login": "a"}, "body": "same here"},
            {"user": {"login": "b"}, "body": "me too, blocks us daily"},
        ]
    )
    assert "a: same here" in blob
    assert "b: me too" in blob


def test_find_fix_references():
    refs = find_fix_references("This PR fixes #12 and closes #34")
    assert refs == [12, 34]
