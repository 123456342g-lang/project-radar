from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.db.database import db_session, insert


@pytest.fixture()
def client(tmp_settings):
    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_judge_mode(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["judge_mode"] == "heuristic"


def test_settings_roundtrip_persists_and_switches_judge(client, tmp_settings):
    import os

    from backend.app import config as app_config
    from backend.app.config import load_saved_settings

    try:
        before = client.get("/api/settings").json()
        assert before["typesafe_api_key"]["set"] is False
        assert before["judge_mode"] == "heuristic"

        saved = client.post(
            "/api/settings", json={"typesafe_api_key": "apikey_test_1234abcd"}
        ).json()
        assert saved["ok"] is True
        assert saved["judge_mode"] == "jev"
        assert saved["typesafe_api_key"]["hint"].endswith("abcd")
        assert "apikey_test" not in saved["typesafe_api_key"]["hint"]

        after = client.get("/api/settings").json()
        assert after["typesafe_api_key"]["set"] is True
        assert after["judge_mode"] == "jev"

        assert load_saved_settings(tmp_settings.data_dir)["typesafe_api_key"] == (
            "apikey_test_1234abcd"
        )

        health = client.get("/api/health").json()
        assert health["judge_mode"] == "jev"
    finally:
        os.environ.pop("TYPESAFE_API_KEY", None)
        app_config.reset_settings()


def test_settings_blank_payload_rejected(client):
    response = client.post("/api/settings", json={"typesafe_api_key": "   "})
    assert response.status_code == 422


def test_index_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Project Radar" in response.text


@pytest.mark.parametrize(
    "bad_repo", ["not a repo", "https://github.com/", "justoneword", "a/b/c/d"]
)
def test_scan_rejects_invalid_repo(client, bad_repo):
    response = client.post("/api/scans", json={"repo": bad_repo})
    assert response.status_code == 422


def test_scan_accepts_url_and_starts(client, monkeypatch):
    done = {}

    def fake_run_scan(full_name, scan_id=None, **kwargs):
        done["full_name"] = full_name
        with db_session() as conn:
            conn.execute(
                "UPDATE scans SET status='done', progress=1.0, finished_at=? WHERE id=?",
                (time.time(), scan_id),
            )

    monkeypatch.setattr(main, "run_scan", fake_run_scan)
    response = client.post(
        "/api/scans", json={"repo": "https://github.com/octo/demo.git"}
    )
    assert response.status_code == 200
    scan_id = response.json()["scan_id"]
    assert response.json()["repo"] == "octo/demo"

    thread = main._scan_threads.get(scan_id)
    if thread:
        thread.join(timeout=5)

    status = client.get(f"/api/scans/{scan_id}").json()
    assert status["status"] == "done"
    assert done["full_name"] == "octo/demo"

    report = client.get(f"/api/scans/{scan_id}/report")
    assert report.status_code == 200
    assert report.json()["top"] == []


def test_report_409_when_scan_not_done(client, monkeypatch):
    response = client.post("/api/scans", json={"repo": "octo/pending"})
    scan_id = response.json()["scan_id"]
    thread = main._scan_threads.get(scan_id)
    with db_session() as conn:
        conn.execute("UPDATE scans SET status='failed', error='rate limit' WHERE id=?", (scan_id,))
    if thread:
        thread.join(timeout=5)
    assert client.get(f"/api/scans/{scan_id}/report").status_code == 409


def test_feedback_requires_known_problem(client):
    response = client.post("/api/problems/9999/feedback", json={"kind": "confirm", "note": ""})
    assert response.status_code == 404


def test_feedback_rejects_unknown_kind(client):
    with db_session() as conn:
        repo_id = insert(
            conn, "repositories", {"full_name": "octo/fb", "updated_at": time.time()}
        )
        problem_id = insert(
            conn,
            "problems",
            {
                "repo_id": repo_id,
                "canonical_title": "Async callbacks",
                "evidence": "{}",
                "problem_type": "missing_feature",
                "priority": 0.5,
                "created_at": time.time(),
                "updated_at": time.time(),
            },
        )
    response = client.post(
        f"/api/problems/{problem_id}/feedback", json={"kind": "banana", "note": ""}
    )
    assert response.status_code == 422


def test_feedback_stores_and_updates_context(client):
    with db_session() as conn:
        repo_id = insert(
            conn, "repositories", {"full_name": "octo/fb2", "updated_at": time.time()}
        )
        problem_id = insert(
            conn,
            "problems",
            {
                "repo_id": repo_id,
                "canonical_title": "Async callbacks",
                "evidence": "{}",
                "problem_type": "missing_feature",
                "priority": 0.5,
                "created_at": time.time(),
                "updated_at": time.time(),
            },
        )
    response = client.post(
        f"/api/problems/{problem_id}/feedback",
        json={"kind": "split", "note": "these are two different bugs"},
    )
    assert response.status_code == 200

    context = client.get("/api/repos/octo/fb2/context").json()
    assert context["context"]["rejected_clusters"] == [problem_id]
    assert context["context"]["user_feedback"][0]["note"] == "these are two different bugs"

    listing = client.get("/api/repos")
    assert any(r["full_name"] == "octo/fb2" for r in listing.json()["repos"])


def test_non_goal_requires_note(client):
    response = client.post("/api/repos/octo/x/context/non_goals", json={"kind": "confirm", "note": "  "})
    assert response.status_code == 422


def test_non_goal_stores(client):
    response = client.post(
        "/api/repos/octo/x/context/non_goals",
        json={"kind": "confirm", "note": "Maintainers will not support Windows"},
    )
    assert response.status_code == 200
    assert "Maintainers will not support Windows" in response.json()["known_non_goals"]
