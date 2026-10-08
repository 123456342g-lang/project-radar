from __future__ import annotations

SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY,
    full_name TEXT UNIQUE NOT NULL,
    default_branch TEXT,
    stars INTEGER,
    updated_at REAL,
    last_scan_at REAL
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    stage TEXT,
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    started_at REAL,
    finished_at REAL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL,
    github_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    number INTEGER,
    title TEXT,
    body TEXT,
    author TEXT,
    state TEXT,
    created_at REAL,
    updated_at REAL,
    closed_at REAL,
    reactions INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    merged INTEGER DEFAULT 0,
    labels TEXT DEFAULT '[]',
    raw_url TEXT,
    closed_via_fix INTEGER DEFAULT 0,
    fix_refs TEXT DEFAULT '[]',
    changed_files INTEGER,
    UNIQUE(repo_id, kind, github_id)
);

CREATE TABLE IF NOT EXISTS problems (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL,
    scan_id INTEGER,
    canonical_title TEXT,
    description TEXT,
    evidence TEXT,
    problem_type TEXT,
    priority REAL,
    rank INTEGER,
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS problem_artifacts (
    problem_id INTEGER NOT NULL,
    artifact_id INTEGER NOT NULL,
    similarity REAL,
    PRIMARY KEY (problem_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS judgments (
    id INTEGER PRIMARY KEY,
    problem_id INTEGER NOT NULL,
    scan_id INTEGER,
    same_problem REAL,
    recurring REAL,
    unresolved REAL,
    worth_building REAL,
    problem_type TEXT,
    judge_mode TEXT,
    judged_at REAL,
    model TEXT,
    raw TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    problem_id INTEGER NOT NULL,
    scan_id INTEGER,
    kind TEXT NOT NULL,
    note TEXT,
    created_at REAL
);
"""
