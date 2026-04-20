"""Chroma retrieval layer for the hospital chatbot."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .embedding_factory import EMBEDDING_PROVIDER, build_embedding_function
from .versioning import is_record_stale

CHROMA_DB_DIR = os.getenv("CHROMA_DB_DIR", "chroma_db")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "hospital_faq")
EMBEDDING_MODEL_NAME = os.getenv(
    "OLLAMA_EMBED_MODEL",
    os.getenv("SENTENCE_TRANSFORMERS_EMBED_MODEL", "bge-m3:latest"),
)


@dataclass(slots=True)
class RetrievalCandidate:
    id: str
    category: str
    subcategory: str
    question: str
    answer: str
    notes: str = ""
    department: str | None = None
    contact: str | None = None
    last_updated_at: str | None = None
    status: str = "active"
    vector_score: float = 0.0
    keyword_score: float = 0.0
    rerank_score: float = 0.0
    final_score: float = 0.0
    source_sheet: str | None = None
    source_row: int | None = None
    stale: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _keyword_overlap(query: str, text: str) -> float:
    q_tokens = set(_normalize_text(query).split())
    d_tokens = set(_normalize_text(text).split())
    if not q_tokens or not d_tokens:
        return 0.0
    return len(q_tokens & d_tokens) / max(len(q_tokens), 1)


class ChromaRetriever:
    def __init__(
        self,
        db_dir: str = CHROMA_DB_DIR,
        collection_name: str = CHROMA_COLLECTION,
        embedding_model: str = EMBEDDING_MODEL_NAME,
        embedding_provider: str = EMBEDDING_PROVIDER,
    ) -> None:
        try:
            import chromadb
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("chromadb must be installed before runtime") from exc

        self._db_dir = db_dir
        self._collection_name = collection_name
        self._embedding_fn = build_embedding_function(embedding_provider, model_name=embedding_model)
        self._client = chromadb.PersistentClient(path=db_dir)
        existing = {c.name for c in self._client.list_collections()}
        if collection_name not in existing:
            raise RuntimeError(
                f"Chroma collection '{collection_name}' not found in '{db_dir}'. Run scripts/reindex_kb.py first."
            )
        self._collection = self._client.get_collection(name=collection_name, embedding_function=self._embedding_fn)

    def search(self, query: str, top_k: int = 10, category: str | None = None) -> list[RetrievalCandidate]:
        where = {"category": category} if category else None
        result = self._collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
            include=["metadatas", "distances", "documents"],
        )
        ids = result.get("ids", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        documents = result.get("documents", [[]])[0]
        out: list[RetrievalCandidate] = []
        for item_id, meta, dist, document in zip(ids, metadatas, distances, documents):
            meta = meta or {}
            vector_score = max(0.0, 1.0 - float(dist or 0.0))
            keyword_score = _keyword_overlap(query, f"{meta.get('question','')} {document or ''}")
            candidate = RetrievalCandidate(
                id=str(item_id),
                category=str(meta.get("category") or ""),
                subcategory=str(meta.get("subcategory") or ""),
                question=str(meta.get("question") or ""),
                answer=str(meta.get("answer") or ""),
                notes=str(meta.get("notes") or ""),
                department=meta.get("department"),
                contact=meta.get("contact"),
                last_updated_at=meta.get("last_updated_at"),
                status=str(meta.get("status") or "active"),
                vector_score=round(vector_score, 6),
                keyword_score=round(keyword_score, 6),
                source_sheet=meta.get("source_sheet"),
                source_row=meta.get("source_row"),
                stale=is_record_stale(meta),
                metadata=meta,
            )
            candidate.final_score = round((candidate.vector_score * 0.68) + (candidate.keyword_score * 0.32), 6)
            out.append(candidate)
        return out


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
