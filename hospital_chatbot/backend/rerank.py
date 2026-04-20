"""Reranking strategies for retrieved candidates."""

from __future__ import annotations

import os

from .retrieval import RetrievalCandidate

USE_CROSS_ENCODER = os.getenv("USE_CROSS_ENCODER", "false").lower() == "true"
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _lexical_score(query: str, candidate: RetrievalCandidate) -> float:
    q = set(_normalize(query).split())
    c = set(_normalize(f"{candidate.question} {candidate.answer} {candidate.subcategory} {candidate.category}").split())
    if not q or not c:
        return 0.0
    overlap = len(q & c) / max(len(q), 1)
    bonus = 0.0
    if _normalize(candidate.category) in _normalize(query):
        bonus += 0.1
    if candidate.subcategory and _normalize(candidate.subcategory) in _normalize(query):
        bonus += 0.1
    return min(1.0, overlap + bonus)


class HybridReranker:
    def __init__(self) -> None:
        self._cross_encoder = None
        if USE_CROSS_ENCODER:
            try:
                from sentence_transformers import CrossEncoder
                self._cross_encoder = CrossEncoder(RERANKER_MODEL)
            except Exception:
                self._cross_encoder = None

    def rerank(self, query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        ranked = list(candidates)
        if not ranked:
            return ranked
        cross_scores: list[float] | None = None
        if self._cross_encoder is not None:
            pairs = [(query, f"{c.question}\n{c.answer}") for c in ranked]
            try:
                raw_scores = self._cross_encoder.predict(pairs)
                cross_scores = [float(s) for s in raw_scores]
                lo, hi = min(cross_scores), max(cross_scores)
                if hi > lo:
                    cross_scores = [(s - lo) / (hi - lo) for s in cross_scores]
                else:
                    cross_scores = [0.5 for _ in cross_scores]
            except Exception:
                cross_scores = None
        for idx, cand in enumerate(ranked):
            lexical = _lexical_score(query, cand)
            cand.rerank_score = round(cross_scores[idx], 6) if cross_scores is not None else round(lexical, 6)
            cand.final_score = round((cand.vector_score * 0.45) + (cand.keyword_score * 0.20) + (cand.rerank_score * 0.35), 6)
            if cand.stale:
                cand.final_score = round(max(0.0, cand.final_score - 0.08), 6)
        ranked.sort(key=lambda c: c.final_score, reverse=True)
        return ranked
