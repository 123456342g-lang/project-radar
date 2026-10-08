from __future__ import annotations

import json
import re
import zlib
from typing import Any

from backend.app.github.issues import parse_iso, summarize_reactions

CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
URL_RE = re.compile(r"https?://\S+")
WHITESPACE_RE = re.compile(r"\s+")
ISSUE_REF_RE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?)\s+#(\d+)", re.IGNORECASE)


def clean_body(text: str | None, max_len: int = 4000) -> str:
    if not text:
        return ""
    text = CODE_FENCE_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)
    text = re.sub(r"[#*>`|_-]{1,}", " ", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text[:max_len]


def artifact_from_issue(item: dict[str, Any], repo_id: int) -> dict[str, Any]:
    return {
        "repo_id": repo_id,
        "github_id": item["id"],
        "kind": "issue",
        "number": item.get("number"),
        "title": (item.get("title") or "").strip(),
        "body": clean_body(item.get("body")),
        "author": ((item.get("user") or {}).get("login")) or "unknown",
        "state": item.get("state") or "open",
        "created_at": parse_iso(item.get("created_at")),
        "updated_at": parse_iso(item.get("updated_at")),
        "closed_at": parse_iso(item.get("closed_at")),
        "reactions": summarize_reactions(item),
        "comments": int(item.get("comments") or 0),
        "merged": 0,
        "labels": json.dumps(
            [lab.get("name", "") for lab in (item.get("labels") or [])], ensure_ascii=False
        ),
        "raw_url": item.get("html_url") or "",
        "closed_via_fix": 0,
        "fix_refs": "[]",
        "changed_files": None,
    }


def artifact_from_pull(item: dict[str, Any], repo_id: int) -> dict[str, Any]:
    merged = bool(item.get("merged_at"))
    return {
        "repo_id": repo_id,
        "github_id": item["id"],
        "kind": "pull_request",
        "number": item.get("number"),
        "title": (item.get("title") or "").strip(),
        "body": clean_body(item.get("body")),
        "author": ((item.get("user") or {}).get("login")) or "unknown",
        "state": "merged" if merged else (item.get("state") or "open"),
        "created_at": parse_iso(item.get("created_at")),
        "updated_at": parse_iso(item.get("updated_at")),
        "closed_at": parse_iso(item.get("closed_at")),
        "reactions": summarize_reactions(item),
        "comments": int(item.get("comments") or 0),
        "merged": 1 if merged else 0,
        "labels": json.dumps([], ensure_ascii=False),
        "raw_url": item.get("html_url") or "",
        "closed_via_fix": 0,
        "fix_refs": "[]",
        "changed_files": item.get("changed_files"),
    }


def artifact_from_discussion(node: dict[str, Any], repo_id: int) -> dict[str, Any]:
    author = (node.get("author") or {}).get("login") or "unknown"
    category = ((node.get("category") or {}).get("name")) or "discussion"
    return {
        "repo_id": repo_id,
        "github_id": zlib.crc32(f"d:{repo_id}:{node.get('number')}".encode()) + 4_000_000_000,
        "kind": "discussion",
        "number": node.get("number"),
        "title": (node.get("title") or "").strip(),
        "body": clean_body(node.get("body")),
        "author": author,
        "state": "answered" if node.get("answered") else "unanswered",
        "created_at": node.get("created_ts") or parse_iso(node.get("createdAt")),
        "updated_at": node.get("updated_ts") or parse_iso(node.get("updatedAt")),
        "closed_at": None,
        "reactions": ((node.get("reactions") or {}).get("totalCount")) or 0,
        "comments": ((node.get("comments") or {}).get("totalCount")) or 0,
        "merged": 0,
        "labels": json.dumps([category], ensure_ascii=False),
        "raw_url": "",
        "closed_via_fix": 0,
        "fix_refs": "[]",
        "changed_files": None,
    }


def comments_blob(comments: list[dict[str, Any]], max_comments: int = 20) -> str:
    parts: list[str] = []
    for comment in comments[:max_comments]:
        body = clean_body(comment.get("body"), max_len=800)
        if body:
            author = (comment.get("user") or {}).get("login") or "user"
            parts.append(f"{author}: {body}")
    return "\n".join(parts)


def find_fix_references(text: str) -> list[int]:
    return [int(m) for m in ISSUE_REF_RE.findall(text or "")]
