from __future__ import annotations

import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.app.config import REPO_ROOT, get_settings
from backend.app.db.database import db_session, fetch_all, fetch_one, init_db, insert
from backend.app.github.client import GitHubError, RateLimitExceeded
from backend.app.memory.context import FEEDBACK_KINDS, ProjectContext
from backend.app.pipeline import run_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
FRONTEND_DIR = REPO_ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Project Radar", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_scan_threads: dict[int, threading.Thread] = {}
_scan_lock = threading.Lock()


class ScanRequest(BaseModel):
    repo: str = Field(..., min_length=3, max_length=200)


class FeedbackRequest(BaseModel):
    kind: str = Field(..., min_length=3, max_length=20)
    note: str = Field(default="", max_length=2000)


def parse_repo(value: str) -> str:
    text = value.strip().rstrip("/")
    text = re.sub(r"^https?://(www\.)?github\.com/", "", text)
    text = text.split("?")[0].split("#")[0].strip("/")
    if text.endswith(".git"):
        text = text[:-4]
    if not REPO_NAME_RE.match(text):
        raise HTTPException(status_code=422, detail="Expected a GitHub repo like owner/name")
    return text


def _start_scan(full_name: str) -> int:
    with db_session() as conn:
        repo_id_row = conn.execute(
            "SELECT id FROM repositories WHERE full_name=?", (full_name,)
        ).fetchone()
        if repo_id_row is None:
            repo_id = insert(
                conn, "repositories", {"full_name": full_name, "updated_at": time.time()}
            )
        else:
            repo_id = int(repo_id_row["id"])
        scan_id = insert(
            conn,
            "scans",
            {
                "repo_id": repo_id,
                "status": "running",
                "stage": "starting",
                "progress": 0.0,
                "started_at": time.time(),
            },
        )

    def worker() -> None:
        try:
            run_scan(full_name, scan_id=scan_id)
        except RateLimitExceeded as exc:
            _fail_scan(scan_id, f"GitHub rate limit hit: {exc}")
        except GitHubError as exc:
            _fail_scan(scan_id, str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("scan failed")
            _fail_scan(scan_id, f"unexpected error: {exc}")

    thread = threading.Thread(target=worker, daemon=True, name=f"scan-{scan_id}")
    with _scan_lock:
        _scan_threads[scan_id] = thread
    thread.start()
    return scan_id


def _fail_scan(scan_id: int, message: str) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE scans SET status='failed', error=?, finished_at=? WHERE id=?",
            (message[:1000], time.time(), scan_id),
        )


@app.get("/api/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "judge_mode": settings.judge_mode,
        "github_token": bool(settings.github_token),
    }


@app.post("/api/scans")
def create_scan(payload: ScanRequest) -> dict[str, Any]:
    full_name = parse_repo(payload.repo)
    scan_id = _start_scan(full_name)
    return {"scan_id": scan_id, "repo": full_name}


@app.get("/api/scans/{scan_id}")
def scan_status(scan_id: int) -> dict[str, Any]:
    with db_session() as conn:
        row = fetch_one(
            conn,
            "SELECT s.*, r.full_name FROM scans s JOIN repositories r ON r.id=s.repo_id "
            "WHERE s.id=?",
            (scan_id,),
        )
    if not row:
        raise HTTPException(status_code=404, detail="scan not found")
    return row


@app.get("/api/scans/{scan_id}/report")
def scan_report(scan_id: int) -> dict[str, Any]:
    with db_session() as conn:
        scan = fetch_one(conn, "SELECT * FROM scans WHERE id=?", (scan_id,))
        if not scan:
            raise HTTPException(status_code=404, detail="scan not found")
        if scan["status"] != "done":
            raise HTTPException(status_code=409, detail=f"scan is {scan['status']}")
        repo_id = scan["repo_id"]
        repo = fetch_one(conn, "SELECT * FROM repositories WHERE id=?", (repo_id,))
        top_rows = fetch_all(
            conn,
            "SELECT * FROM problems WHERE scan_id=? AND rank IS NOT NULL ORDER BY rank",
            (scan_id,),
        )
        candidate_rows = fetch_all(
            conn,
            "SELECT id, canonical_title, problem_type, priority, rank, evidence "
            "FROM problems WHERE scan_id=? ORDER BY priority DESC LIMIT 20",
            (scan_id,),
        )
        judgment_rows = fetch_all(
            conn, "SELECT * FROM judgments WHERE scan_id=?", (scan_id,)
        )

    judgment_by_problem = {j["problem_id"]: j for j in judgment_rows}
    context = ProjectContext(repo["full_name"])

    def decorate(row: dict[str, Any]) -> dict[str, Any]:
        problem_id = row["id"]
        evidence = json.loads(row["evidence"] or "{}")
        judgment = judgment_by_problem.get(problem_id) or {}
        artifacts = _load_artifacts(problem_id)
        return {
            "problem_id": problem_id,
            "rank": row.get("rank"),
            "title": row.get("canonical_title"),
            "problem_type": row.get("problem_type"),
            "priority": row.get("priority"),
            "why": row.get("description"),
            "evidence": evidence,
            "judgment": {
                "same_problem": judgment.get("same_problem"),
                "recurring": judgment.get("recurring"),
                "unresolved": judgment.get("unresolved"),
                "worth_building": judgment.get("worth_building"),
                "judge_mode": judgment.get("judge_mode"),
                "model": judgment.get("model"),
            },
            "artifacts": artifacts,
            "feedback": _feedback_for(problem_id),
        }

    return {
        "scan": scan,
        "repo": {
            "full_name": repo["full_name"],
            "stars": repo.get("stars"),
            "last_scan_at": repo.get("last_scan_at"),
        },
        "top": [decorate(row) for row in top_rows],
        "candidates": [
            {
                "problem_id": row["id"],
                "title": row["canonical_title"],
                "problem_type": row["problem_type"],
                "priority": row["priority"],
                "rank": row["rank"],
            }
            for row in candidate_rows
        ],
        "context": context.summary(),
        "judge_mode": (top_rows and top_rows[0]) and judgment_rows and
        judgment_rows[0].get("judge_mode") or "unknown",
    }


def _load_artifacts(problem_id: int) -> list[dict[str, Any]]:
    with db_session() as conn:
        rows = fetch_all(
            conn,
            "SELECT a.* FROM problem_artifacts pa JOIN artifacts a ON a.id=pa.artifact_id "
            "WHERE pa.problem_id=? ORDER BY a.created_at",
            (problem_id,),
        )
    chain = []
    for row in rows:
        created = row.get("created_at")
        chain.append(
            {
                "kind": row.get("kind"),
                "number": row.get("number"),
                "title": row.get("title"),
                "state": row.get("state"),
                "author": row.get("author"),
                "date": time.strftime("%Y-%m", time.gmtime(created)) if created else "",
                "url": row.get("raw_url"),
                "reactions": row.get("reactions"),
                "comments": row.get("comments"),
            }
        )
    return chain


def _feedback_for(problem_id: int) -> list[dict[str, Any]]:
    with db_session() as conn:
        return fetch_all(
            conn, "SELECT kind, note, created_at FROM feedback WHERE problem_id=? ORDER BY id",
            (problem_id,),
        )


@app.post("/api/problems/{problem_id}/feedback")
def add_feedback(problem_id: int, payload: FeedbackRequest) -> dict[str, Any]:
    if payload.kind not in FEEDBACK_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {sorted(FEEDBACK_KINDS)}"
        )
    with db_session() as conn:
        problem = fetch_one(conn, "SELECT * FROM problems WHERE id=?", (problem_id,))
        if not problem:
            raise HTTPException(status_code=404, detail="problem not found")
        repo = fetch_one(conn, "SELECT * FROM repositories WHERE id=?", (problem["repo_id"],))
        feedback_id = insert(
            conn,
            "feedback",
            {
                "problem_id": problem_id,
                "scan_id": problem.get("scan_id"),
                "kind": payload.kind,
                "note": payload.note,
                "created_at": time.time(),
            },
        )
    context = ProjectContext(repo["full_name"])
    entry = context.add_feedback(
        problem_id, payload.kind, payload.note, problem["canonical_title"] or ""
    )
    return {"feedback_id": feedback_id, "stored": entry}


@app.get("/api/repos")
def list_repos() -> dict[str, Any]:
    with db_session() as conn:
        rows = fetch_all(
            conn,
            "SELECT r.full_name, r.stars, r.last_scan_at, "
            "(SELECT COUNT(*) FROM scans s WHERE s.repo_id=r.id AND s.status='done') AS scans "
            "FROM repositories r ORDER BY r.last_scan_at DESC LIMIT 50",
        )
    return {"repos": rows}


@app.get("/api/repos/{owner}/{name}/context")
def repo_context(owner: str, name: str) -> dict[str, Any]:
    full_name = f"{owner}/{name}"
    context = ProjectContext(full_name)
    return {"full_name": full_name, "context": context.data}


@app.post("/api/repos/{owner}/{name}/context/non_goals")
def add_non_goal(owner: str, name: str, payload: FeedbackRequest) -> dict[str, Any]:
    if not payload.note.strip():
        raise HTTPException(status_code=422, detail="note is required for a non-goal")
    context = ProjectContext(f"{owner}/{name}")
    context.add_non_goal(payload.note.strip())
    return {"known_non_goals": context.data["known_non_goals"]}


@app.get("/api/candidates/{scan_id}")
def candidates(scan_id: int) -> dict[str, Any]:
    with db_session() as conn:
        scan = fetch_one(conn, "SELECT * FROM scans WHERE id=?", (scan_id,))
        if not scan:
            raise HTTPException(status_code=404, detail="scan not found")
        rows = fetch_all(
            conn,
            "SELECT p.id, p.canonical_title, p.problem_type, p.priority, p.rank, p.evidence, "
            "j.same_problem, j.unresolved, j.worth_building, j.judge_mode "
            "FROM problems p LEFT JOIN judgments j ON j.problem_id=p.id "
            "WHERE p.scan_id=? ORDER BY p.priority DESC LIMIT 20",
            (scan_id,),
        )
    return {"candidates": rows}


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))
