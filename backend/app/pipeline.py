from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.app.clustering.cluster import Cluster, cluster_artifacts, cluster_summary_text
from backend.app.config import Settings, get_settings
from backend.app.db.database import db_session, insert, upsert
from backend.app.github.client import GitHubClient, GitHubError, RateLimitExceeded
from backend.app.github.discussions import iter_discussions
from backend.app.github.issues import fetch_issue_comments, fetch_repo, iter_issues
from backend.app.github.pulls import apply_pull_detail, fetch_pull_detail, iter_pulls
from backend.app.github.timeline import extract_linked_prs, fetch_issue_timeline
from backend.app.ingest.dedupe import dedupe
from backend.app.ingest.normalize import (
    artifact_from_discussion,
    artifact_from_issue,
    artifact_from_pull,
    comments_blob,
)
from backend.app.judge.jev import get_judge
from backend.app.judge.schemas import Judgment
from backend.app.memory.context import (
    ProjectContext,
    detect_maintainer_signal,
    normalize_title,
)
from backend.app.ranking.evidence import build_evidence, resolution_hints
from backend.app.ranking.score import rank_candidates, score_candidate

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float], None]

STAGES = [
    ("collect", 0.0, 0.35),
    ("normalize", 0.35, 0.45),
    ("cluster", 0.45, 0.58),
    ("judge", 0.58, 0.88),
    ("rank", 0.88, 1.0),
]


@dataclass
class ScanResult:
    repo: dict[str, Any]
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    top: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    judge_mode: str = "heuristic"


class StageProgress:
    def __init__(self, callback: ProgressCallback | None = None, scan_id: int | None = None):
        self.callback = callback
        self.scan_id = scan_id
        self.current_stage = ""

    def update(self, stage: str, fraction: float, label: str = "") -> None:
        self.current_stage = stage
        for name, start, end in STAGES:
            if name == stage:
                progress = start + (end - start) * max(0.0, min(1.0, fraction))
                break
        else:
            progress = fraction
        logger.info("scan stage=%s progress=%.2f %s", stage, progress, label)
        if self.callback:
            self.callback(stage, progress)
        if self.scan_id is not None:
            try:
                with db_session() as conn:
                    conn.execute(
                        "UPDATE scans SET stage=?, progress=? WHERE id=?",
                        (label or stage, round(progress, 4), self.scan_id),
                    )
            except Exception as exc:  # pragma: no cover - progress is best effort
                logger.debug("progress update failed: %s", exc)


def collect_artifacts(
    client: GitHubClient, full_name: str, settings: Settings, progress: StageProgress,
    warnings: list[str],
) -> list[dict[str, Any]]:
    raw_issues = list(iter_issues(client, full_name, settings))
    progress.update("collect", 0.3, f"issues: {len(raw_issues)}")

    raw_pulls = list(iter_pulls(client, full_name, settings))
    progress.update("collect", 0.6, f"pulls: {len(raw_pulls)}")

    discussions = iter_discussions(client, full_name, settings)
    progress.update("collect", 0.7, f"discussions: {len(discussions)}")

    artifacts: list[dict[str, Any]] = []
    comment_budget = settings.max_comment_fetches
    commented_issues = sorted(
        (i for i in raw_issues if int(i.get("comments") or 0) > 0),
        key=lambda i: -int(i.get("comments") or 0),
    )
    for position, item in enumerate(commented_issues):
        if comment_budget <= 0:
            warnings.append("comment fetch budget exhausted; some context is incomplete")
            break
        limit = min(20, comment_budget)
        try:
            comments = fetch_issue_comments(client, full_name, item["number"], limit=limit)
        except RateLimitExceeded:
            warnings.append("GitHub rate limit hit while fetching comments")
            break
        except GitHubError as exc:
            warnings.append(f"comments for #{item['number']} failed: {exc}")
            continue
        comment_budget -= limit
        item["_comments_blob"] = comments_blob(comments)
        if position % 10 == 0:
            progress.update("collect", 0.7 + 0.15 * (position / max(1, len(commented_issues))))

    for item in raw_issues:
        artifacts.append(artifact_from_issue(item, repo_id=0))
    for item in raw_pulls:
        artifacts.append(artifact_from_pull(item, repo_id=0))
    for node in discussions:
        artifacts.append(artifact_from_discussion(node, repo_id=0))

    for artifact in artifacts:
        match = next(
            (i for i in commented_issues if i.get("id") == artifact["github_id"]), None
        )
        if match and match.get("_comments_blob"):
            artifact["body"] = f"{artifact['body']} {match['_comments_blob']}".strip()[:6000]
    return artifacts


def _enrich_evidence(
    client: GitHubClient,
    full_name: str,
    artifacts: list[dict[str, Any]],
    clusters: list[Cluster],
    settings: Settings,
    warnings: list[str],
) -> None:
    """Budget-aware second pass: timelines for closed issues, details for candidate PRs."""
    remaining_budget = getattr(client, "requests_left", None)
    if remaining_budget is not None and remaining_budget < settings.github_min_budget:
        warnings.append("GitHub API budget too low; skipping timeline/PR enrichment")
        return
    timeline_left = settings.max_timeline_fetches
    pulls_left = settings.max_pull_details
    try:
        for cluster in clusters:
            for index in cluster.artifact_indices:
                artifact = artifacts[index]
                kind = artifact.get("kind")
                if kind == "issue" and artifact.get("state") == "closed" and timeline_left > 0:
                    timeline_left -= 1
                    events = fetch_issue_timeline(
                        client, full_name, int(artifact.get("number") or 0)
                    )
                    refs = extract_linked_prs(events)
                    artifact["fix_refs"] = json.dumps(refs, ensure_ascii=False)
                    if any(ref.get("merged") for ref in refs):
                        artifact["closed_via_fix"] = 1
                elif kind == "pull_request" and pulls_left > 0:
                    pulls_left -= 1
                    detail = fetch_pull_detail(
                        client, full_name, int(artifact.get("number") or 0)
                    )
                    apply_pull_detail(artifact, detail)
                if timeline_left <= 0 and pulls_left <= 0:
                    return
    except RateLimitExceeded as exc:
        warnings.append(f"rate limit during enrichment: {exc}")
    except GitHubError as exc:
        warnings.append(f"enrichment failed: {exc}")


def _candidate_context(
    cluster: Cluster,
    artifacts: list[dict[str, Any]],
    evidence_dict: dict[str, Any],
    resolution: dict[str, Any],
    cohesion: float,
    context_summary: dict[str, Any],
) -> dict[str, Any]:
    member_artifacts = [artifacts[i] for i in cluster.artifact_indices]
    return {
        "problem_title": cluster.representative.get("title", ""),
        "keywords": cluster.keywords,
        "cohesion": cohesion,
        "evidence": evidence_dict,
        "resolution_signals": resolution,
        "project_context": context_summary,
        "artifacts": [
            {
                "kind": a.get("kind"),
                "number": a.get("number"),
                "title": a.get("title"),
                "body": (a.get("body") or "")[:600],
                "state": a.get("state"),
                "author": a.get("author"),
                "created_at": a.get("created_at"),
            }
            for a in member_artifacts
        ],
    }


def _why_exists(evidence: dict[str, Any], judgment: Judgment) -> str:
    authors = evidence.get("independent_authors", 0)
    issues = evidence.get("issues", 0)
    discussions = evidence.get("discussions", 0)
    months = max(1, int(evidence.get("span_days", 0) / 30))
    surfaces = []
    if issues:
        surfaces.append(f"{issues} issues")
    if discussions:
        surfaces.append(f"{discussions} discussions")
    if evidence.get("pull_requests"):
        surfaces.append(f"{evidence['pull_requests']} pull requests")
    surface_text = ", ".join(surfaces)
    return (
        f"{authors} independent authors across {surface_text} over ~{months} months, "
        f"coherence {judgment.same_problem:.2f}."
    )


def _why_unresolved(evidence: dict[str, Any], resolution: dict[str, Any], judgment: Judgment) -> str:
    parts: list[str] = []
    merged_numbers = [p["number"] for p in resolution.get("merged_pull_requests", [])]
    fixed_numbers = [p["number"] for p in resolution.get("issue_fixes", [])]
    fix_numbers = merged_numbers + fixed_numbers
    if fix_numbers:
        parts.append(
            "fix evidence exists ("
            + ", ".join(f"#{n}" for n in fix_numbers)
            + ") but evidence suggests the underlying problem persists"
        )
    elif resolution.get("has_failed_attempt"):
        parts.append(
            "attempts were made but closed unmerged (" +
            ", ".join(f"#{p['number']}" for p in resolution.get("failed_pull_requests", [])) +
            ")"
        )
    else:
        parts.append("no merged fix found")
    open_numbers = resolution.get("open_issue_numbers") or []
    if open_numbers:
        parts.append(f"still-open issues: {', '.join('#' + str(n) for n in open_numbers[:6])}")
    parts.append(f"unresolved probability {judgment.unresolved:.2f}")
    return "; ".join(parts) + "."


def _why_worth(evidence: dict[str, Any], judgment: Judgment, context: dict[str, Any]) -> str:
    signal = context.get("maintainer_signal", "unclear")
    parts = [
        f"worth building {judgment.worth_building:.2f}/3",
        f"{evidence.get('independent_authors', 0)} independent authors",
        f"{evidence.get('surfaces', 1)} evidence surfaces",
    ]
    if evidence.get("cross_surface"):
        parts.append("appears in issues AND discussions/PRs (demand escalated past complaining)")
    if signal == "reject":
        parts.append("maintainers have signalled rejection — external fork/opportunity")
    elif signal == "support":
        parts.append("maintainers appear receptive")
    return "; ".join(parts) + "."


MINIMAL_FIX_HINTS = {
    "bug_fix": "Reproduce from the linked issues, patch the failing path, add a regression test.",
    "missing_feature": "Ship the smallest API surface that satisfies the most repeated use case.",
    "developer_experience": "Improve the error/config path first — it is the cheapest observable win.",
    "performance": "Profile with the reported workloads, optimize the hot path, add a benchmark.",
    "integration": "Build against the most requested target first, keep the adapter thin.",
    "documentation": "Rewrite the entry-point docs around the reported confusion, add a runnable example.",
    "workflow": "Automate the repeated manual step end-to-end before generalizing.",
    "architecture": "Isolate the limitation behind an interface, migrate incrementally.",
    "other": "Start with a minimal reproduction from the evidence chain.",
}


def run_scan(
    full_name: str,
    progress_callback: ProgressCallback | None = None,
    scan_id: int | None = None,
    settings: Settings | None = None,
) -> ScanResult:
    settings = settings or get_settings()
    progress = StageProgress(progress_callback, scan_id)
    warnings: list[str] = []
    context = ProjectContext(full_name)

    with GitHubClient(settings) as client:
        repo = fetch_repo(client, full_name)
        context.set_repo_profile(
            {
                "full_name": repo.get("full_name", full_name),
                "description": repo.get("description"),
                "stars": repo.get("stargazers_count"),
                "open_issues": repo.get("open_issues_count"),
                "default_branch": repo.get("default_branch"),
                "language": repo.get("language"),
                "updated_at": repo.get("pushed_at"),
            }
        )
        raw_artifacts = collect_artifacts(client, full_name, settings, progress, warnings)

        progress.update("normalize", 0.5, f"raw artifacts: {len(raw_artifacts)}")
        artifacts = dedupe(raw_artifacts)
        now = time.time()
        progress.update("normalize", 1.0, f"after dedupe: {len(artifacts)}")

        if len(artifacts) < 2:
            warnings.append("not enough artifacts to cluster")

        progress.update("cluster", 0.2, "embedding")
        clusters = cluster_artifacts(artifacts)
        progress.update("cluster", 0.6, f"clusters: {len(clusters)}")
        _enrich_evidence(client, full_name, artifacts, clusters, settings, warnings)
        progress.update("cluster", 1.0, "evidence enriched")

    judge = get_judge(settings)
    rejected_titles = context.rejected_titles()
    confirmed_titles = context.confirmed_titles()
    context_summary = context.summary()

    candidates: list[dict[str, Any]] = []
    total_clusters = max(1, len(clusters))
    for position, cluster in enumerate(clusters):
        member_artifacts = [artifacts[i] for i in cluster.artifact_indices]
        evidence = build_evidence(member_artifacts, now)
        evidence_dict = evidence.as_dict()
        resolution = resolution_hints(member_artifacts)
        cluster_context = _candidate_context(
            cluster, artifacts, evidence_dict, resolution, cluster.cohesion, context_summary
        )
        try:
            judgment = judge.judge(cluster_context)
        except Exception as exc:
            warnings.append(f"judgment failed for cluster {cluster.index}: {exc}")
            judgment = Judgment(judge_mode="error", model="none")

        scored = score_candidate(
            evidence_dict, judgment.unresolved, judgment.worth_building, judgment.recurring
        )
        if judgment.same_problem < 0.55:
            scored.priority *= 0.5

        candidate_id = cluster.index + 1
        candidate_title = (
            cluster.representative.get("title") or " ".join(cluster.keywords[:6])
        )
        title_key = normalize_title(candidate_title)
        if title_key in rejected_titles:
            scored.priority *= 0.3
        if title_key in confirmed_titles:
            scored.priority = min(1.0, scored.priority * 1.15)

        member_states = [
            {
                "kind": a.get("kind"),
                "number": a.get("number"),
                "title": a.get("title"),
                "state": a.get("state"),
                "author": a.get("author"),
                "created_at": a.get("created_at"),
                "url": a.get("raw_url"),
                "reactions": a.get("reactions"),
                "comments": a.get("comments"),
            }
            for a in sorted(member_artifacts, key=lambda a: a.get("created_at") or 0)
        ]
        candidate = {
            "id": candidate_id,
            "title": candidate_title,
            "keywords": cluster.keywords,
            "problem_type": judgment.problem_type,
            "priority": round(scored.priority, 4),
            "worth": judgment.worth_building,
            "components": scored.components,
            "judgment": {
                "same_problem": judgment.same_problem,
                "recurring": judgment.recurring,
                "unresolved": judgment.unresolved,
                "worth_building": judgment.worth_building,
                "problem_type": judgment.problem_type,
                "judge_mode": judgment.judge_mode,
                "model": judgment.model,
                "confidence": judgment.confidence,
            },
            "evidence": evidence_dict,
            "resolution": resolution,
            "cohesion": round(cluster.cohesion, 4),
            "maintainer_signal": detect_maintainer_signal(member_artifacts),
            "why_exists": _why_exists(evidence_dict, judgment),
            "why_unresolved": _why_unresolved(evidence_dict, resolution, judgment),
            "why_worth": _why_worth(evidence_dict, judgment, {
                **context_summary,
                "maintainer_signal": detect_maintainer_signal(member_artifacts),
            }),
            "minimal_fix": MINIMAL_FIX_HINTS.get(judgment.problem_type, MINIMAL_FIX_HINTS["other"]),
            "confidence": round(
                judgment.confidence
                if judgment.judge_mode == "jev"
                else min(0.95, 0.4 + 0.2 * cluster.cohesion + 0.05 * evidence.independent_authors),
                4,
            ),
            "artifacts": member_states,
            "evidence_chain": _evidence_chain(member_states),
        }
        candidates.append(candidate)
        progress.update(
            "judge", (position + 1) / total_clusters, f"judged {position + 1}/{total_clusters}"
        )

    top = rank_candidates(candidates, settings.top_n)
    progress.update("rank", 1.0, f"top {len(top)} selected")

    _persist(full_name, repo, artifacts, clusters, candidates, top, scan_id)

    return ScanResult(
        repo={
            "full_name": repo.get("full_name", full_name),
            "description": repo.get("description"),
            "stars": repo.get("stargazers_count"),
            "language": repo.get("language"),
            "url": repo.get("html_url"),
            "open_issues": repo.get("open_issues_count"),
        },
        artifacts=artifacts,
        candidates=candidates,
        top=top,
        warnings=warnings,
        judge_mode=getattr(judge, "mode", None) or settings.judge_mode,
    )


def _evidence_chain(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "date": _format_date(s.get("created_at")),
            "label": f"{'PR' if s.get('kind') == 'pull_request' else s.get('kind', 'issue').title()} #{s.get('number')}",
            "title": s.get("title"),
            "state": s.get("state"),
            "url": s.get("url"),
            "author": s.get("author"),
        }
        for s in states
    ]


def _format_date(timestamp: float | None) -> str:
    if not timestamp:
        return ""
    return time.strftime("%Y-%m", time.gmtime(timestamp))


def _persist(
    full_name: str,
    repo: dict[str, Any],
    artifacts: list[dict[str, Any]],
    clusters: list[Cluster],
    candidates: list[dict[str, Any]],
    top: list[dict[str, Any]],
    scan_id: int | None,
) -> None:
    with db_session() as conn:
        repo_id = upsert(
            conn,
            "repositories",
            {
                "full_name": repo.get("full_name", full_name),
                "default_branch": repo.get("default_branch"),
                "stars": repo.get("stargazers_count", 0),
                "updated_at": time.time(),
                "last_scan_at": time.time(),
            },
            ["full_name"],
        )
        artifact_ids: list[int] = []
        for artifact in artifacts:
            values = dict(artifact)
            values["repo_id"] = repo_id
            artifact_id = upsert(
                conn,
                "artifacts",
                values,
                ["repo_id", "kind", "github_id"],
            )
            artifact_ids.append(artifact_id)

        rank_map = {c["id"]: c["rank"] for c in top}
        for candidate in candidates:
            problem_id = insert(
                conn,
                "problems",
                {
                    "repo_id": repo_id,
                    "scan_id": scan_id,
                    "canonical_title": candidate["title"],
                    "description": candidate["why_exists"],
                    "evidence": json.dumps(candidate["evidence"], ensure_ascii=False),
                    "problem_type": candidate["problem_type"],
                    "priority": candidate["priority"],
                    "rank": rank_map.get(candidate["id"]),
                    "created_at": time.time(),
                    "updated_at": time.time(),
                },
            )
            cluster_index = candidate["id"] - 1
            if 0 <= cluster_index < len(clusters):
                for member in clusters[cluster_index].artifact_indices:
                    if member < len(artifact_ids):
                        conn.execute(
                            "INSERT OR IGNORE INTO problem_artifacts "
                            "(problem_id, artifact_id, similarity) VALUES (?, ?, ?)",
                            (problem_id, artifact_ids[member], candidate["cohesion"]),
                        )
            judgment = candidate["judgment"]
            insert(
                conn,
                "judgments",
                {
                    "problem_id": problem_id,
                    "scan_id": scan_id,
                    "same_problem": judgment["same_problem"],
                    "recurring": judgment["recurring"],
                    "unresolved": judgment["unresolved"],
                    "worth_building": judgment["worth_building"],
                    "problem_type": judgment["problem_type"],
                    "judge_mode": judgment["judge_mode"],
                    "judged_at": time.time(),
                    "model": judgment["model"],
                    "raw": json.dumps(judgment, ensure_ascii=False),
                },
            )
        if scan_id is not None:
            conn.execute(
                "UPDATE scans SET status='done', progress=1.0, finished_at=? WHERE id=?",
                (time.time(), scan_id),
            )
