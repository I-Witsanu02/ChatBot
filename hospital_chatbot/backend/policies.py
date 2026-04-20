"""Routing policies for answer / clarify / fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .retrieval import RetrievalCandidate

EMERGENCY_RE = re.compile(r"แน่นหน้าอก|หายใจไม่ออก|หมดสติ|ชัก|ฉุกเฉิน|1669", re.IGNORECASE)
OUT_OF_SCOPE_RE = re.compile(r"วินิจฉัย|สั่งยา|กินยาอะไร|รักษาหายไหม|โรคนี้อันตรายไหม", re.IGNORECASE)
BROAD_RE = re.compile(r"^(ราคา|ค่าใช้จ่าย|วัคซีน|นัดหมาย|ตรวจสุขภาพ|ตารางแพทย์|ไวรัสตับ|สิทธิ|เอกสาร)$")


@dataclass(slots=True)
class Decision:
    action: Literal["answer", "clarify", "fallback"]
    confidence: float
    reason: str
    warnings: list[str] = field(default_factory=list)


def decide(query: str, candidates: list[RetrievalCandidate]) -> Decision:
    q = query.strip()
    if not q:
        return Decision("fallback", 0.0, "empty_query")
    if EMERGENCY_RE.search(q):
        return Decision("fallback", 0.99, "emergency_redirect", ["emergency"])
    if OUT_OF_SCOPE_RE.search(q):
        return Decision("fallback", 0.95, "medical_diagnosis_out_of_scope", ["out_of_scope"])
    if not candidates:
        return Decision("fallback", 0.0, "no_candidates")

    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    score_gap = round(top.final_score - (second.final_score if second else 0.0), 6)
    broad = bool(BROAD_RE.search(q)) or len(q) <= 8

    warnings: list[str] = []
    if top.stale:
        warnings.append("top_result_stale")

    if top.final_score < 0.25:
        return Decision("fallback", round(top.final_score, 4), "low_retrieval_confidence", warnings)
    if broad and (second is not None and score_gap < 0.08):
        return Decision("clarify", round(top.final_score, 4), "broad_query_with_close_candidates", warnings)
    if second is not None and top.category != second.category and score_gap < 0.06:
        return Decision("clarify", round(top.final_score, 4), "cross_category_ambiguity", warnings)
    if top.metadata.get("requires_clarification"):
        return Decision("clarify", round(top.final_score, 4), "record_requires_clarification", warnings)
    return Decision("answer", round(top.final_score, 4), "top_candidate_confident", warnings)
