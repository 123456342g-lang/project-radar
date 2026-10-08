from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

MERGED_STATE = "merged"
FIX_MARKERS = ("fix", "close", "resolve")


@dataclass
class Evidence:
    issues: int = 0
    discussions: int = 0
    pull_requests: int = 0
    merged_fixes: int = 0
    failed_pr_attempts: int = 0
    independent_authors: int = 0
    span_days: int = 0
    reactions: int = 0
    comments: int = 0
    open_ratio: float = 0.0
    closed_without_fix: int = 0
    surfaces: int = 0
    cross_surface: bool = False
    recent_activity_days: int | None = None
    labels: list[str] = field(default_factory=list)
    changed_files: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "issues": self.issues,
            "discussions": self.discussions,
            "pull_requests": self.pull_requests,
            "merged_fixes": self.merged_fixes,
            "failed_pr_attempts": self.failed_pr_attempts,
            "independent_authors": self.independent_authors,
            "span_days": self.span_days,
            "reactions": self.reactions,
            "comments": self.comments,
            "open_ratio": round(self.open_ratio, 4),
            "closed_without_fix": self.closed_without_fix,
            "surfaces": self.surfaces,
            "cross_surface": self.cross_surface,
            "recent_activity_days": self.recent_activity_days,
            "labels": self.labels[:10],
            "changed_files": self.changed_files,
        }


def _labels_of(artifact: dict[str, Any]) -> list[str]:
    raw = artifact.get("labels") or "[]"
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        parsed = json.loads(raw)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def build_evidence(artifacts: list[dict[str, Any]], now: float) -> Evidence:
    kinds = {a.get("kind") for a in artifacts}
    issues = [a for a in artifacts if a.get("kind") == "issue"]
    pulls = [a for a in artifacts if a.get("kind") == "pull_request"]
    discussions = [a for a in artifacts if a.get("kind") == "discussion"]

    timestamps = [a.get("created_at") for a in artifacts if a.get("created_at")]
    span_days = 0
    recent_days: int | None = None
    if timestamps:
        span_days = int((max(timestamps) - min(timestamps)) / 86400)
        recent_days = int((now - max(timestamps)) / 86400)

    open_states = {"open", "unanswered"}
    open_count = sum(1 for a in artifacts if a.get("state") in open_states)
    merged_fixes = sum(1 for a in pulls if a.get("merged"))
    merged_fixes += sum(1 for a in issues if a.get("closed_via_fix"))
    failed_prs = sum(1 for a in pulls if not a.get("merged") and a.get("state") == "closed")
    closed_without_fix = sum(
        1 for a in issues if a.get("state") == "closed" and not a.get("closed_via_fix")
    )
    changed_files = [a.get("changed_files") for a in pulls if a.get("changed_files")]

    authors = {(a.get("author") or "unknown") for a in artifacts}
    label_names: list[str] = []
    for artifact in artifacts:
        label_names.extend(_labels_of(artifact))

    surfaces = sum(1 for k in kinds if k)
    return Evidence(
        issues=len(issues),
        discussions=len(discussions),
        pull_requests=len(pulls),
        merged_fixes=merged_fixes,
        failed_pr_attempts=failed_prs,
        independent_authors=len(authors),
        span_days=span_days,
        reactions=sum(int(a.get("reactions") or 0) for a in artifacts),
        comments=sum(int(a.get("comments") or 0) for a in artifacts),
        open_ratio=(open_count / len(artifacts)) if artifacts else 0.0,
        closed_without_fix=closed_without_fix,
        surfaces=surfaces,
        cross_surface=surfaces >= 2,
        recent_activity_days=recent_days,
        labels=sorted(set(label_names)),
        changed_files=sum(changed_files) if changed_files else None,
    )


def resolution_hints(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    merged = [a for a in artifacts if a.get("kind") == "pull_request" and a.get("merged")]
    failed = [
        a
        for a in artifacts
        if a.get("kind") == "pull_request" and not a.get("merged") and a.get("state") == "closed"
    ]
    open_issues = [a for a in artifacts if a.get("kind") == "issue" and a.get("state") == "open"]
    issue_fixes = [a for a in artifacts if a.get("closed_via_fix")]
    return {
        "merged_pull_requests": [
            {"number": a.get("number"), "title": a.get("title")} for a in merged[:5]
        ],
        "failed_pull_requests": [
            {"number": a.get("number"), "title": a.get("title")} for a in failed[:5]
        ],
        "issue_fixes": [{"number": a.get("number"), "title": a.get("title")} for a in issue_fixes[:5]],
        "open_issue_numbers": [a.get("number") for a in open_issues[:20]],
        "has_merged_fix": bool(merged or issue_fixes),
        "has_failed_attempt": bool(failed),
    }
