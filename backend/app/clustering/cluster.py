from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.app.clustering.embeddings import Embedder, get_embedder, tokenize
from backend.app.ingest.normalize import clean_body

logger = logging.getLogger(__name__)

MIN_CLUSTER_SIZE = 2
MAX_CLUSTER_SIZE = 40
SIMILARITY_THRESHOLD = 0.15
MEMBER_FLOOR = 0.12
MEMBER_FLOOR_NEIGHBORS = 3
BLOB_SPLIT_SIZE = 12
BLOB_SPLIT_THRESHOLD = 0.25
MAX_ITEMS = 1200


@dataclass
class Cluster:
    index: int
    artifact_indices: list[int]
    cohesion: float
    representative: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)


def _artifact_text(artifact: dict[str, Any]) -> str:
    title = artifact.get("title", "")
    return f"{title}. {title}. {clean_body(artifact.get('body'), max_len=1200)}"


def _cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    if vectors.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = vectors / norms
    return (normalized @ normalized.T).astype(np.float32)


def _overlap_matrix(texts: list[str]) -> np.ndarray:
    """Overlap coefficient over shared keywords; catches reworded reports.

    Requires at least three shared tokens so generic two-word matches never merge.
    """
    token_sets = [set(tokenize(text)) for text in texts]
    size = len(token_sets)
    matrix = np.eye(size, dtype=np.float32)
    for i in range(size):
        set_i = token_sets[i]
        if len(set_i) == 0:
            continue
        for j in range(i + 1, size):
            shared = len(set_i & token_sets[j])
            if shared < 3:
                continue
            denominator = max(1, min(len(set_i), len(token_sets[j])))
            value = shared / denominator
            matrix[i, j] = matrix[j, i] = value
    return matrix


def _linkage_labels(similarity: np.ndarray, threshold: float, linkage: str) -> np.ndarray:
    n = similarity.shape[0]
    if n == 0:
        return np.zeros(0, dtype=int)
    if n == 1:
        return np.zeros(1, dtype=int)
    from sklearn.cluster import AgglomerativeClustering

    distance = 1.0 - similarity
    np.fill_diagonal(distance, 0.0)
    distance = np.clip(distance, 0.0, 2.0)
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=1.0 - threshold,
        metric="precomputed",
        linkage=linkage,
    )
    return model.fit_predict(distance)


def _prune_members(
    similarity: np.ndarray,
    members: list[int],
    floor: float = MEMBER_FLOOR,
    neighbors: int = MEMBER_FLOOR_NEIGHBORS,
    max_passes: int = 5,
) -> list[int]:
    """Drop members weakly attached to their component (top-N mean similarity).

    Single-link chains glue unrelated issues into blobs; members whose best
    neighbor ties are near zero are noise even if a path exists. Pairs that
    are directly linked pass the floor and always stay.
    """
    members = list(members)
    for _ in range(max_passes):
        if len(members) <= 2:
            break
        keep: list[int] = []
        for member in members:
            ties = sorted(
                (float(similarity[member, other]) for other in members if other != member),
                reverse=True,
            )
            top = ties[: max(1, neighbors)]
            if sum(top) / len(top) >= floor:
                keep.append(member)
        if len(keep) == len(members):
            break
        members = keep
    return members


def _sub_split(
    similarity: np.ndarray,
    members: list[int],
    threshold: float = BLOB_SPLIT_THRESHOLD,
) -> list[list[int]]:
    """Re-cluster an oversized component with average linkage at a stricter threshold."""
    sub = similarity[np.ix_(members, members)]
    sub_labels = _linkage_labels(sub, threshold, linkage="average")
    groups: dict[int, list[int]] = {}
    for position, label in enumerate(sub_labels):
        groups.setdefault(int(label), []).append(members[position])
    return [group for group in groups.values() if len(group) >= MIN_CLUSTER_SIZE]


def _extract_keywords(texts: list[str], top_k: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    for text in texts:
        for token in set(tokenize(text)):
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [token for token, _ in ranked[:top_k]]


def _representative(artifacts: list[dict[str, Any]], indices: list[int]) -> dict[str, Any]:
    def weight(i: int) -> tuple[int, int, int]:
        a = artifacts[i]
        return (int(a.get("comments") or 0), int(a.get("reactions") or 0), len(a.get("body") or ""))

    best = max(indices, key=weight)
    return artifacts[best]


def cluster_artifacts(
    artifacts: list[dict[str, Any]],
    embedder: Embedder | None = None,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> list[Cluster]:
    if not artifacts:
        return []
    embedder = embedder or get_embedder()
    subset = artifacts[:MAX_ITEMS]
    texts = [_artifact_text(a) for a in subset]
    logger.info("Embedding %d artifacts with %s", len(texts), getattr(embedder, "name", "?"))
    vectors = embedder.embed(texts)
    similarity = np.maximum(_cosine_similarity_matrix(vectors), _overlap_matrix(texts))
    labels = _linkage_labels(similarity, threshold=similarity_threshold, linkage="single")

    by_label: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        by_label.setdefault(int(label), []).append(idx)

    groups: list[list[int]] = []
    for label in sorted(by_label):
        members = _prune_members(similarity, by_label[label])
        if len(members) < MIN_CLUSTER_SIZE:
            continue
        if len(members) > BLOB_SPLIT_SIZE:
            groups.extend(_sub_split(similarity, members))
        else:
            groups.append(members)
    groups.sort(key=lambda g: (-len(g), -float(np.mean(
        [similarity[i, j] for pos, i in enumerate(g) for j in g[pos + 1 :]]
    ) if len(g) > 1 else 0.0)))

    clusters: list[Cluster] = []
    for members in groups:
        if len(members) < MIN_CLUSTER_SIZE:
            continue
        if len(members) > MAX_CLUSTER_SIZE:
            members = members[:MAX_CLUSTER_SIZE]
        pair_scores = [
            float(similarity[i, j])
            for pos, i in enumerate(members)
            for j in members[pos + 1 :]
        ]
        cohesion = float(np.mean(pair_scores)) if pair_scores else 0.0
        member_texts = [texts[i] for i in members]
        clusters.append(
            Cluster(
                index=len(clusters),
                artifact_indices=members,
                cohesion=cohesion,
                representative=_representative(subset, members),
                keywords=_extract_keywords(member_texts),
            )
        )

    clusters.sort(key=lambda c: (-len(c.artifact_indices), -c.cohesion))
    for position, cluster in enumerate(clusters):
        cluster.index = position
    logger.info("Formed %d candidate clusters", len(clusters))
    return clusters


def cluster_summary_text(cluster: Cluster, artifacts: list[dict[str, Any]], limit: int = 12) -> str:
    lines: list[str] = []
    for i in cluster.artifact_indices[:limit]:
        artifact = artifacts[i]
        kind = artifact.get("kind", "issue")
        number = artifact.get("number")
        title = (artifact.get("title") or "").strip()
        body = clean_body(artifact.get("body"), max_len=400)
        lines.append(f"[{kind} #{number}] {title}\n{body}")
    return "\n\n".join(lines)
