from __future__ import annotations

import numpy as np

from backend.app.clustering.cluster import (
    _prune_members,
    _sub_split,
    cluster_artifacts,
    cluster_summary_text,
)
from backend.app.clustering.embeddings import TfidfEmbedder, tokenize


def _issue(github_id, number, title, body, author="user", kind="issue"):
    return {
        "repo_id": 1,
        "github_id": github_id,
        "kind": kind,
        "number": number,
        "title": title,
        "body": body,
        "author": author,
        "state": "open",
        "created_at": 1_700_000_000 + github_id * 86400,
        "updated_at": 1_700_000_000 + github_id * 86400,
        "closed_at": None,
        "reactions": 1,
        "comments": 1,
        "merged": 0,
        "labels": "[]",
        "raw_url": "",
    }


ASYNC_TEXTS = [
    ("Support async callbacks", "the hook API needs async callback support for coroutines"),
    ("Callbacks block the event loop", "blocking callbacks freeze the event loop, need async"),
    ("Non blocking callback API", "callbacks should not block, add asynchronous callback support"),
    ("Async callback support?", "is async callback supported? coroutine callbacks please"),
]
DOCS_TEXTS = [
    ("Typo in install docs", "the docs install example is wrong in the readme"),
    ("Docs install example broken", "documentation install example fails to run as documented"),
]


def build_fixture():
    artifacts = []
    gid = 1
    for title, body in ASYNC_TEXTS:
        artifacts.append(_issue(gid, gid, title, body, author=f"async-{gid}"))
        gid += 1
    for title, body in DOCS_TEXTS:
        artifacts.append(_issue(gid, gid, title, body, author=f"docs-{gid}"))
        gid += 1
    return artifacts


def test_tokenize_lowercases_and_drops_stopwords():
    tokens = tokenize("The async callback support for the API")
    assert "the" not in tokens
    assert "async" in tokens


def test_tfidf_embedder_normalizes():
    embedder = TfidfEmbedder()
    vectors = embedder.embed(["async callback support", "documentation typo"])
    assert vectors.shape[0] == 2
    assert vectors.shape[1] > 0


def test_async_texts_cluster_together():
    artifacts = build_fixture()
    clusters = cluster_artifacts(artifacts, embedder=TfidfEmbedder())
    assert clusters, "expected at least one cluster"
    async_cluster = next(
        (c for c in clusters if any("async" in artifacts[i]["title"].lower() for i in c.artifact_indices)),
        None,
    )
    assert async_cluster is not None
    assert len(async_cluster.artifact_indices) >= 3
    assert async_cluster.cohesion > 0.2


def test_cluster_summary_text_contains_titles():
    artifacts = build_fixture()
    clusters = cluster_artifacts(artifacts, embedder=TfidfEmbedder())
    text = cluster_summary_text(clusters[0], artifacts)
    assert "[" in text and "#" in text


def test_empty_input_returns_no_clusters():
    assert cluster_artifacts([]) == []


def test_prune_members_drops_weakly_attached_noise():
    sim = np.eye(4, dtype=np.float32)
    for a, b in ((0, 1), (0, 2), (1, 2)):
        sim[a, b] = sim[b, a] = 0.6
    sim[0, 3] = sim[3, 0] = 0.16

    kept = _prune_members(sim, [0, 1, 2, 3])

    assert kept == [0, 1, 2]


def test_prune_members_keeps_directly_linked_pairs():
    sim = np.zeros((3, 3), dtype=np.float32)
    sim[0, 1] = sim[1, 0] = 0.3
    sim[2, 2] = 1.0

    kept = _prune_members(sim, [0, 1, 2])

    assert set(kept) == {0, 1}


def test_sub_split_breaks_oversized_blobs_into_blocks():
    size = 16
    sim = np.full((size, size), 0.02, dtype=np.float32)
    np.fill_diagonal(sim, 1.0)
    sim[:8, :8] = np.maximum(sim[:8, :8], 0.5)
    sim[8:, 8:] = np.maximum(sim[8:, 8:], 0.5)
    np.fill_diagonal(sim, 1.0)

    groups = _sub_split(sim, list(range(size)))

    assert sorted(len(g) for g in groups) == [8, 8]


def test_blob_of_unrelated_issues_does_not_merge():
    artifacts = build_fixture()
    fixture_titles = {a["title"] for a in artifacts}
    noise = [
        _issue(gid, gid, f"Disk quota {gid}", "quota exceeded during upload")
        for gid in range(10, 17)
    ]
    all_items = artifacts + noise
    clusters = cluster_artifacts(all_items, embedder=TfidfEmbedder())
    for cluster in clusters:
        titles = [all_items[i]["title"] for i in cluster.artifact_indices]
        signal = [t for t in titles if t in fixture_titles]
        noise_titles = [t for t in titles if t.startswith("Disk quota")]
        assert not (signal and noise_titles), f"noise merged into signal cluster: {titles}"
