from __future__ import annotations

import pytest

from backend.app.memory.context import (
    ProjectContext,
    detect_maintainer_signal,
    normalize_title,
)


def test_normalize_title_strips_punctuation():
    assert normalize_title("Async: Callback Support!") == normalize_title(
        "async callback support"
    )


def test_feedback_confirm_marks_title_confirmed(tmp_settings):
    context = ProjectContext("octo/demo")
    context.add_feedback(11, "confirm", "really real", "Async callback support")
    reloaded = ProjectContext("octo/demo")
    assert normalize_title("Async callback support") in reloaded.confirmed_titles()


def test_feedback_split_and_solved_mark_title_rejected(tmp_settings):
    context = ProjectContext("octo/demo")
    context.add_feedback(12, "split", "", "Docs typo")
    context.add_feedback(13, "solved", "", "Old crash bug")
    reloaded = ProjectContext("octo/demo")
    rejected = reloaded.rejected_titles()
    assert normalize_title("Docs typo") in rejected
    assert normalize_title("Old crash bug") in rejected
    assert reloaded.rejected_ids() == {12, 13}


def test_invalid_feedback_kind_rejected(tmp_settings):
    context = ProjectContext("octo/demo")
    with pytest.raises(ValueError):
        context.add_feedback(1, "banana", "")


def test_non_goals_accumulate(tmp_settings):
    context = ProjectContext("octo/demo")
    context.add_non_goal("No Windows support")
    context.add_non_goal("No GUI")
    context.add_non_goal("No Windows support")
    assert context.data["known_non_goals"] == ["No Windows support", "No GUI"]


def test_context_survives_reload(tmp_settings):
    context = ProjectContext("octo/demo")
    context.add_feedback(5, "confirm", "yes", "Feature X")
    context.set_repo_profile({"full_name": "octo/demo", "stars": 10})
    reloaded = ProjectContext("octo/demo")
    assert reloaded.data["repo_profile"]["stars"] == 10
    assert len(reloaded.data["user_feedback"]) == 1
    summary = reloaded.summary()
    assert summary["confirmed_count"] == 1
    assert summary["feedback_count"] == 1


def test_detect_maintainer_signal_reject():
    artifacts = [
        {"kind": "issue", "labels": '["wontfix"]', "body": "", "state": "closed"},
        {"kind": "issue", "labels": "[]", "body": "we won't fix this, out of scope", "state": "closed"},
    ]
    assert detect_maintainer_signal(artifacts) == "reject"


def test_detect_maintainer_signal_support():
    artifacts = [
        {"kind": "pull_request", "labels": "[]", "body": "", "state": "merged", "merged": 1},
    ]
    assert detect_maintainer_signal(artifacts) == "support"


def test_detect_maintainer_signal_neutral():
    artifacts = [{"kind": "issue", "labels": "[]", "body": "feature request", "state": "open"}]
    assert detect_maintainer_signal(artifacts) == "neutral"
