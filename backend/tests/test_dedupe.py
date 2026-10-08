from __future__ import annotations

from backend.app.ingest.dedupe import dedupe, is_noise


def _issue(**overrides):
    base = {
        "github_id": 1,
        "kind": "issue",
        "number": 1,
        "title": "Support async callbacks",
        "body": "need async",
        "author": "alice",
        "state": "open",
        "labels": "[]",
    }
    base.update(overrides)
    return base


def test_bot_issues_are_noise():
    assert is_noise(_issue(author="dependabot[bot]", title="Bump lodash from 1 to 2"))


def test_duplicate_labeled_issues_are_noise():
    assert is_noise(_issue(labels='["duplicate"]'))


def test_normal_issue_is_not_noise():
    assert not is_noise(_issue())


def test_dedupe_drops_same_author_same_content():
    first = _issue(github_id=1)
    duplicate = _issue(github_id=2, number=2)
    kept = dedupe([first, duplicate])
    assert len(kept) == 1


def test_dedupe_keeps_different_authors():
    first = _issue(github_id=1, author="alice")
    second = _issue(github_id=2, number=2, author="bob")
    kept = dedupe([first, second])
    assert len(kept) == 2
