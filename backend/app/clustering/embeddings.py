from __future__ import annotations

import logging
import os
import re
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-zA-Z0-9_#+]{2,}")
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "had", "not", "but", "you", "your", "can", "cant", "will",
    "would", "should", "when", "what", "which", "how", "why", "who", "all",
    "into", "out", "about", "than", "then", "them", "they", "their", "there",
    "been", "being", "does", "did", "its", "it's", "our", "over", "under",
    "any", "some", "only", "just", "also", "very", "more", "most", "other",
    "use", "using", "used", "need", "want", "get", "one", "like", "please",
    "issue", "bug", "error", "thanks", "hello", "hi", "does not", "don't",
    "is", "in", "to", "of", "on", "it", "be", "as", "at", "or", "we", "do",
    "if", "by", "my", "me", "up", "so", "no", "yes", "here", "there",
}


def fold_token(token: str) -> str:
    """Light stemmer: folds common English suffixes so variants cluster together."""
    if len(token) > 6 and token.endswith("ing"):
        token = token[:-3]
    elif len(token) > 6 and token.endswith("ed"):
        token = token[:-2]
    elif len(token) > 3 and token.endswith("s"):
        token = token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text.lower()):
        folded = fold_token(token)
        if folded not in STOPWORDS:
            tokens.append(folded)
    return tokens


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


class TfidfEmbedder:
    name = "tfidf"

    def __init__(self, max_features: int = 8000):
        self.max_features = max_features
        self._vectorizer = None

    def embed(self, texts: list[str]) -> np.ndarray:
        from sklearn.feature_extraction.text import TfidfVectorizer

        vectorizer = TfidfVectorizer(
            tokenizer=tokenize,
            token_pattern=None,
            max_features=self.max_features,
            sublinear_tf=True,
            ngram_range=(1, 2),
        )
        matrix = vectorizer.fit_transform(texts)
        norms = np.linalg.norm(matrix.toarray(), axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        dense = matrix.toarray() / norms
        return dense.astype(np.float32)


class SentenceTransformerEmbedder:
    name = "sentence-transformers"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)


def get_embedder(preference: str | None = None) -> Embedder:
    if preference is None:
        preference = os.environ.get("EMBEDDING_BACKEND", "").strip() or None
    if preference == "tfidf":
        return TfidfEmbedder()
    if preference == "sentence-transformers":
        try:
            return SentenceTransformerEmbedder()
        except Exception as exc:  # pragma: no cover - depends on local install
            logger.warning("sentence-transformers unavailable (%s), falling back", exc)
    elif preference is None:
        try:
            import sentence_transformers  # noqa: F401

            return SentenceTransformerEmbedder()
        except Exception:
            pass
    return TfidfEmbedder()
