"""Dependency-free retrieval over a local markdown corpus: TF-IDF + cosine, pure stdlib.

No numpy, no vector DB — a corpus of a handful of playbooks does not need one.

# ponytail: in-memory TF-IDF, O(vocab) per doc, linear scan at query time. Fine for
# tens-to-hundreds of local docs. If the corpus grows to thousands, swap in a real
# index (sqlite FTS5 or an embedding store) — the KnowledgeBase API stays the same.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class KnowledgeBase:
    def __init__(self) -> None:
        self._docs: dict[str, str] = {}
        self._tfidf: dict[str, dict[str, float]] = {}  # doc_id -> {term: weight} (L2-normalized)
        self._idf: dict[str, float] = {}

    def index(self, docs: list[tuple[str, str]]) -> None:
        """(Re)build the index from (doc_id, text) pairs."""
        self._docs = {doc_id: text for doc_id, text in docs}
        tokenized = {doc_id: _tokenize(text) for doc_id, text in self._docs.items()}

        n = len(tokenized) or 1
        df: Counter[str] = Counter()
        for toks in tokenized.values():
            df.update(set(toks))
        # Smoothed idf, always positive so a term in every doc still carries weight.
        self._idf = {term: math.log((n + 1) / (freq + 1)) + 1.0 for term, freq in df.items()}

        self._tfidf = {}
        for doc_id, toks in tokenized.items():
            self._tfidf[doc_id] = self._vector(toks)

    def _vector(self, toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        vec = {term: (1.0 + math.log(count)) * self._idf.get(term, 0.0) for term, count in tf.items()}
        norm = math.sqrt(sum(w * w for w in vec.values()))
        if norm:
            vec = {term: w / norm for term, w in vec.items()}
        return vec

    def search(self, query: str, k: int = 3) -> list[tuple[str, float, str]]:
        """Return up to k (doc_id, cosine_score, snippet), best first. Score > 0 only."""
        qvec = self._vector(_tokenize(query))
        if not qvec:
            return []
        scored: list[tuple[str, float]] = []
        for doc_id, dvec in self._tfidf.items():
            # Cosine = dot product (both vectors are L2-normalized).
            score = sum(w * dvec.get(term, 0.0) for term, w in qvec.items())
            if score > 0:
                scored.append((doc_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        qterms = set(_tokenize(query))
        return [(doc_id, score, self._snippet(doc_id, qterms)) for doc_id, score in scored[:k]]

    def _snippet(self, doc_id: str, qterms: set[str], width: int = 240) -> str:
        """A window of the doc centered on the first query-term hit."""
        text = self._docs.get(doc_id, "")
        lower = text.lower()
        best = -1
        for term in qterms:
            i = lower.find(term)
            if i != -1 and (best == -1 or i < best):
                best = i
        if best == -1:
            return text[:width].strip()
        start = max(0, best - width // 3)
        snippet = text[start:start + width].strip().replace("\n", " ")
        return ("…" if start > 0 else "") + snippet + ("…" if start + width < len(text) else "")
