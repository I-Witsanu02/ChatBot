"""Production-oriented FastAPI app for the hospital chatbot.

V20 fixes:
- async lifespan replacing deprecated on_event("startup")
- KB-not-ready → friendly fallback instead of 503
- /health/ollama and /health/kb sub-endpoints
- structured logging (request, route, latency, errors)
- Ollama call wrapped with explicit timeout + logging
- frontend always gets answer even when model fails
- admin.html JavaScript completely fixed
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .audit import append_audit_event, tail_audit_events
from .handoff import (
    append_live_message,
    claim_ticket,
    create_handoff_ticket,
    fetch_session_responses,
    fetch_session_responses_after,
    list_handoff_tickets,
    respond_to_ticket,
)
from .request_log import analytics_summary, init_request_log_db, list_request_logs, log_chat_request
from .auth import AdminPrincipal, require_role
from .model_config import DEFAULT_LOCK_PATH, ensure_lock_file, runtime_summary
from .policies import decide
from .prompts import (
    GUIDE_ITEMS,
    WELCOME_MESSAGE,
    build_category_not_found_text,
    build_category_overview,
    build_clarification_options,
    build_clarification_text,
    build_followup_hint_text,
    build_llm_messages,
    display_category_name,
    emergency_text,
    fallback_text,
    format_direct_answer,
    handoff_waiting_text,
    unclear_input_text,
    typo_recovery_text,
    ambiguous_term_text,
)
from .rerank import HybridReranker
from .retrieval import ChromaRetriever, RetrievalCandidate
from .versioning import load_jsonl_records, load_manifest, now_bangkok_iso, stale_summary
from .topic_tree import build_topic_tree

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hospital_chatbot")

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

WORKBOOK_PATH = Path(os.getenv("WORKBOOK_PATH", str(DATA_DIR / "master_kb.xlsx")))
KNOWLEDGE_JSONL = Path(os.getenv("KNOWLEDGE_JSONL", str(DATA_DIR / "knowledge.jsonl")))
KNOWLEDGE_CSV = Path(os.getenv("KNOWLEDGE_CSV", str(DATA_DIR / "knowledge.csv")))
VALIDATION_REPORT_PATH = Path(os.getenv("VALIDATION_REPORT_PATH", str(DATA_DIR / "kb_validation_report.json")))
MANIFEST_PATH = Path(os.getenv("MANIFEST_PATH", str(DATA_DIR / "kb_manifest.json")))
EVAL_REPORT_PATH = Path(os.getenv("EVAL_REPORT_PATH", str(DATA_DIR / "evaluation_report.json")))
AUDIT_LOG_PATH = Path(os.getenv("AUDIT_LOG_PATH", str(LOG_DIR / "audit.jsonl")))
SERVING_LOCK_PATH = Path(os.getenv("SERVING_MODEL_LOCK_PATH", str(PROJECT_ROOT / DEFAULT_LOCK_PATH)))
ANALYTICS_DB_PATH = Path(os.getenv("ANALYTICS_DB_PATH", str(DATA_DIR / "chatbot_analytics.db")))

HITL_CONFIDENCE_THRESHOLD = float(os.getenv("HITL_CONFIDENCE_THRESHOLD", "0.60"))
HITL_FALLBACK_ALWAYS = os.getenv("HITL_FALLBACK_ALWAYS", "true").strip().lower() in {"1", "true", "yes", "y"}

OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))
CHROMA_DB_DIR = os.getenv("CHROMA_DB_DIR", "chroma_db")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "hospital_faq")
FOLLOWUP_TTL_SECONDS = int(os.getenv("SESSION_MEMORY_TTL_SECONDS", "1800"))


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def _lifespan(application: FastAPI):
    logger.info("🚀 Hospital Chatbot API starting up…")
    init_request_log_db(ANALYTICS_DB_PATH)
    logger.info("✅ Analytics DB ready: %s", ANALYTICS_DB_PATH)
    yield
    logger.info("🛑 Hospital Chatbot API shutting down.")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Hospital Chatbot API", version="20.0.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Category routing tables ───────────────────────────────────────────────────
CATEGORY_ALIASES: dict[str, list[str]] = {
    "การจัดการนัดหมาย": [
        "นัด", "นัดหมาย", "เลื่อนนัด", "ขอเลื่อนนัด", "ยกเลิกนัด", "เปลี่ยนนัด", "เปลี่ยนวันนัด", "ย้ายนัด",
        "จองคิว", "จองคิวพบแพทย์", "ต่อคิว", "คิว", "พบหมอ", "นัดแพทย์", "พบแพทย์", "จองพบแพทย์",
    ],
    "ตารางแพทย์และเวลาทำการ": [
        "ตารางแพทย์", "ตารางหมอ", "ตารางออกตรวจ", "แพทย์", "แพทยื", "เเพทย์", "เเพทยื", "คุณหมอ", "หมอ", "หมอเข้า",
        "แพทย์ออกตรวจ", "เวลาแพทย์", "เวลาทำการ", "เปิดกี่โมง", "เปิดวันไหน", "หมอตรวจวันไหน", "หมอกระดูก", "หมอตา",
    ],
    "คลินิกทันตกรรม": [
        "ทันตกรรม", "หมอฟัน", "ฟัน", "ทำฟัน", "ถอนฟัน", "อุดฟัน", "ปวดฟัน", "ช่องปาก", "เหงือก", "ฟันผุ",
    ],
    "ศูนย์ไตเทียม": [
        "ไตเทียม", "ฟอกไต", "ล้างไต", "ไต", "ศูนย์ไต", "ฟอกเลือด", "ไตวาย", "ล้างไตทางช่องท้อง",
    ],
    "สูตินรีเวช": [
        "สูตินรีเวช", "สูติ", "สูติฯ", "นรีเวช", "ครรภ์", "ฝากครรภ์", "ตรวจครรภ์", "ผู้หญิง", "สตรี", "ตรวจภายใน", "คลินิกสตรี",
        "ภรรยาตั้งครรภ์", "มดลูก", "รังไข่", "ประจำเดือน",
    ],
    "ประเมินค่าใช้จ่ายทั่วไป": [
        "ค่าใช้จ่าย", "ประเมินค่าใช้จ่าย", "ราคาค่ารักษา", "ค่ารักษา", "ตรวจสอบสิทธิ", "ย้ายสิทธิ", "สิทธิการรักษา",
        "ประวัติการรักษา", "ขอประวัติการรักษา", "เวชระเบียน", "ค่าใช้จ่ายในการรักษา", "สิทธิ",
    ],
    "วัคซีน": [
        "วัคซีน", "วักซีน", "วคซีน", "วัก", "วัปซีน", "วัคซีนผู้ใหญ่", "วัคซีนเด็ก", "ฉีดวัคซีน", "ฉีดยา",
        "วัคซีนไข้หวัดใหญ่", "วัคซีนตับอักเสบ", "hpv", "พิษสุนัขบ้า", "บาดทะยัก", "วัคซีนมะเร็งปากมดลูก",
        "วดหซีน", "วัดซีน", "วัคซิน",
    ],
    "สวัสดิการวัคซีนนักศึกษา": [
        "วัคซีนนักศึกษา", "วัคซีนสำหรับนักศึกษา", "สิทธิวัคซีนนักศึกษา", "นักศึกษาฉีดวัคซีน",
        "วัคซีนฟรีนักศึกษา", "วัคซีนนักศึกษา", "วัคซีน hpv นักศึกษา", "วัคซีนมะเร็งปากมดลูกฟรี",
    ],
    "ธนาคารเลือดและบริจาคเลือด": [
        "เลือด", "บริจาคเลือด", "ธนาคารเลือด", "ให้เลือด", "ธนาคารเลือดและบริจาคเลือด", "เลือดวันไหน", "ฟอกเลือด",
    ],
    "กลุ่มงานบุคคล": [
        "สมัครงาน", "รับสมัครงาน", "งานบุคคล", "บุคคล", "hr", "ตำแหน่งงาน", "งานว่าง",
    ],
    "ตรวจสุขภาพรายบุคคล": [
        "ตรวจสุขภาพ", "ตรวจร่างกาย", "แพ็กเกจตรวจสุขภาพ", "โปรแกรมตรวจสุขภาพ", "เช็กสุขภาพ", "ตรวจสุขภาพทั่วไป", "ตรจสุขภาพ",
    ],
    "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่า": [
        "ตรวจสุขภาพองค์กร", "ตรวจสุขภาพหมู่คณะ", "ตรวจสุขภาพหน่วยงาน", "ตรวจสุขภาพบริษัท", "เบิกจ่าย", "สิทธิเบิกจ่าย",
        "เบิกตรง", "ตรวจสุขภาพพนักงาน",
    ],
    "การขอเอกสารทางการแพทย์": [
        "เอกสารแพทย์", "ใบรับรองแพทย์", "ขอเอกสาร", "ขอใบรับรอง", "ใบรับรอง", "ขอเวชระเบียน", "เอกสารทางการแพทย์",
        "ใบขับขี่", "ใบรับรองสมัครงาน",
    ],
}

TOPIC_ALIAS_OVERRIDES: dict[str, tuple[str, str | None]] = {
    "วัคซีนสำหรับนักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "วัคซีนนักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "สิทธิวัคซีนนักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "นักศึกษาฉีดวัคซีน": ("สวัสดิการวัคซีนนักศึกษา", None),
    "ธนาคารเลือดและบริจาคเลือด": ("ธนาคารเลือดและบริจาคเลือด", None),
    "บริจาคเลือด": ("ธนาคารเลือดและบริจาคเลือด", None),
    "ติดต่อธนาคารเลือด": ("ธนาคารเลือดและบริจาคเลือด", None),
    "หมอฟัน": ("คลินิกทันตกรรม", None),
    "ทันตกรรม": ("คลินิกทันตกรรม", None),
    "ฟอกไต": ("ศูนย์ไตเทียม", None),
    "สูติ": ("สูตินรีเวช", None),
    "นรีเวช": ("สูตินรีเวช", None),
}

AMBIGUOUS_QUERY_CATEGORIES: dict[str, list[str]] = {
    "หมอ": ["ตารางแพทย์และเวลาทำการ", "การจัดการนัดหมาย"],
    "แพทย์": ["ตารางแพทย์และเวลาทำการ", "การจัดการนัดหมาย"],
    "คุณหมอ": ["ตารางแพทย์และเวลาทำการ", "การจัดการนัดหมาย"],
    "ศูนย์": ["ศูนย์ไตเทียม", "ตรวจสุขภาพรายบุคคล"],
    "สิทธิ": ["ประเมินค่าใช้จ่ายทั่วไป", "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่า", "ศูนย์ไตเทียม"],
}

TYPO_CANONICAL_MAP: dict[str, str] = {
    "วัปซีน": "วัคซีน",
    "วักซีน": "วัคซีน",
    "วคซีน": "วัคซีน",
    "วัดซีน": "วัคซีน",
    "วดหซีน": "วัคซีน",
    "วัคซิน": "วัคซีน",
    "แพทยื": "แพทย์",
    "เเพทยื": "แพทย์",
    "เเพทย์": "แพทย์",
    "kmsรีเวช": "สูตินรีเวช",
    "สูคินรีเวช": "สูตินรีเวช",
    "สิดการรักษา": "สิทธิการรักษา",
    "ตรจสุขภาพ": "ตรวจสุขภาพ",
    "ตรวดสุขภาพ": "ตรวจสุขภาพ",
    "บริจา่คเลือด": "บริจาคเลือด",
    "บรจาค": "บริจาค",
}

EMERGENCY_RE = re.compile(r"แน่นหน้าอก|หายใจไม่ออก|หมดสติ|ชัก|ฉุกเฉิน|1669", re.IGNORECASE)
FOLLOW_UP_RE = re.compile(r"ราคา|เท่าไหร่|เท่าไร|ติดต่อ|ที่ไหน|เปิด|วันไหน|เวลา|เข้าได้เลยไหม|เข้ามาได้เลยไหม|เข้ามาได้ไหม|มีไหม|ยังไง", re.IGNORECASE)
BACK_RE = re.compile(r"^กลับ|ย้อนกลับ|กลับไปหมวด", re.IGNORECASE)
SPECIFIC_AVAILABILITY_RE = re.compile(r"มีไหม|มีมั้ย|มีหรือไม่|มีรึเปล่า|มีเปล่า", re.IGNORECASE)
QUERY_STOPWORDS = {
    "ราคา", "เท่าไหร่", "เท่าไร", "เข้ามาได้เลยไหม", "เข้ามาได้ไหม", "ได้ไหม", "มีไหม", "ไหม",
    "ขอ", "สอบถาม", "เรื่อง", "ข้อมูล", "ของ", "ที่", "และ", "หรือ", "ครับ", "ค่ะ", "คะ",
    "บริการ", "หน่อย", "ที", "หน่อยครับ", "หน่อยค่ะ", "ให้หน่อย", "บ้าง", "อะไร", "ยังไง",
}


# ── Session memory ────────────────────────────────────────────────────────────
@dataclass(slots=True)
class SessionMemory:
    session_id: str
    last_category: str | None = None
    last_topic_id: str | None = None
    last_topic_question: str | None = None
    last_buttons: list[str] = field(default_factory=list)
    touched_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.touched_at = time.time()


# ── App state ─────────────────────────────────────────────────────────────────
class AppState:
    def __init__(self) -> None:
        self.retriever: ChromaRetriever | None = None
        self.reranker = HybridReranker()
        self.model_lock = ensure_lock_file(SERVING_LOCK_PATH)
        self.records: list[dict[str, Any]] = []
        self.category_examples: dict[str, list[str]] = {}
        self.sessions: dict[str, SessionMemory] = {}

    def rebuild_catalog(self) -> None:
        self.records = load_jsonl_records(KNOWLEDGE_JSONL) if KNOWLEDGE_JSONL.exists() else []
        category_examples: dict[str, list[str]] = {}
        for record in self.records:
            category = str(record.get("category") or "").strip()
            question = str(record.get("question") or "").strip()
            if not category or not question:
                continue
            category_examples.setdefault(category, [])
            if question not in category_examples[category]:
                category_examples[category].append(question)
        self.category_examples = category_examples

    def reload_retriever(self) -> None:
        self.retriever = ChromaRetriever()
        self.rebuild_catalog()

    def get_session(self, session_id: str) -> SessionMemory:
        self._gc_sessions()
        sid = session_id or "default"
        session = self.sessions.get(sid)
        if session is None:
            session = SessionMemory(session_id=sid)
            self.sessions[sid] = session
        session.touch()
        return session

    def _gc_sessions(self) -> None:
        now = time.time()
        for sid in list(self.sessions.keys()):
            if now - self.sessions[sid].touched_at > FOLLOWUP_TTL_SECONDS:
                del self.sessions[sid]


state = AppState()
try:
    logger.info("⏳ Loading retriever and knowledge base…")
    state.reload_retriever()
    logger.info("✅ Retriever ready. %d records loaded.", len(state.records))
except Exception as exc:
    logger.warning("⚠️  Retriever failed to load (will run in KB-only mode): %s", exc)
    state.retriever = None
    state.rebuild_catalog()
    logger.info("📚 KB-only mode. %d records loaded from JSONL.", len(state.records))


# ── Text normalization helpers ─────────────────────────────────────────────────
def _normalize(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^0-9a-zA-Zก-๙\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact_normalize(text: str) -> str:
    return _normalize(text).replace(" ", "")


def _thai_heavy_normalize(text: str) -> str:
    compact = _compact_normalize(text)
    thai_chunks = re.findall(r"[ก-๙0-9]+", compact)
    return " ".join(thai_chunks) if thai_chunks else compact


def _normalize_typo(query: str) -> tuple[str, str | None]:
    q = _normalize(query)
    compact = _compact_normalize(query)
    if not q:
        return query, None
    if q in TYPO_CANONICAL_MAP:
        return TYPO_CANONICAL_MAP[q], q
    if compact in {k.replace(" ", "") for k in TYPO_CANONICAL_MAP}:
        for k, v in TYPO_CANONICAL_MAP.items():
            if compact == k.replace(" ", ""):
                return v, k
    best = None
    best_score = 0.0
    for wrong, right in TYPO_CANONICAL_MAP.items():
        score = max(SequenceMatcher(None, q, wrong).ratio(), SequenceMatcher(None, compact, wrong.replace(" ", "")).ratio())
        if score > best_score:
            best_score = score
            best = (wrong, right)
    if best and best_score >= 0.78:
        return best[1], best[0]
    return query, None


def _looks_like_query_plus_noise(query: str) -> str:
    tokens = _meaningful_tokens(query)
    if not tokens:
        return query
    known = []
    for tok in tokens:
        if tok in TYPO_CANONICAL_MAP:
            known.append(tok)
            continue
        category, option, score = _best_alias_match(tok) if len(tok) >= 2 else (None, None, 0.0)
        if category or score >= 0.80:
            known.append(tok)
    if known:
        return " ".join(known)
    compact = _compact_normalize(query)
    thai_chunks = re.findall(r"[ก-๙]{2,}", compact)
    if thai_chunks:
        return " ".join(thai_chunks)
    return query


def _best_alias_match(query: str) -> tuple[str | None, str | None, float]:
    q = _normalize(query)
    compact = _compact_normalize(query)
    heavy = _thai_heavy_normalize(query)
    best = (None, None, 0.0)
    for category, aliases in CATEGORY_ALIASES.items():
        for option in [category, *aliases]:
            opt_n = _normalize(option)
            opt_c = _compact_normalize(option)
            opt_h = _thai_heavy_normalize(option)
            score = max(
                SequenceMatcher(None, q, opt_n).ratio(),
                SequenceMatcher(None, compact, opt_c).ratio(),
                SequenceMatcher(None, heavy, opt_h).ratio(),
            )
            if q and (q in opt_n or opt_n in q) and min(len(q), len(opt_n)) >= 3:
                score = max(score, 0.86)
            if score > best[2]:
                best = (category, option, score)
    return best


def _meaningful_tokens(text: str) -> list[str]:
    base = _normalize(text)
    tokens = [tok for tok in base.split() if tok and tok not in QUERY_STOPWORDS]
    out: list[str] = []
    for tok in tokens:
        if tok not in out:
            out.append(tok)
    return out


def _record_to_candidate(row: dict[str, Any], score: float, *, source: str = "catalog") -> RetrievalCandidate:
    return RetrievalCandidate(
        id=str(row.get("id") or ""),
        category=str(row.get("category") or ""),
        subcategory=str(row.get("subcategory") or ""),
        question=str(row.get("question") or ""),
        answer=str(row.get("answer") or ""),
        notes=str(row.get("notes") or ""),
        department=row.get("department"),
        contact=row.get("contact"),
        last_updated_at=row.get("last_updated_at"),
        status=str(row.get("status") or "active"),
        vector_score=round(score if source == "catalog" else 0.0, 6),
        keyword_score=round(score, 6),
        rerank_score=round(score, 6),
        final_score=round(score, 6),
        stale=False,
        metadata=row,
    )


def _topic_alias_candidates(query: str) -> list[RetrievalCandidate]:
    q_norm = _compact_normalize(query)
    if not q_norm:
        return []
    scored: list[RetrievalCandidate] = []
    for row in state.records:
        if str(row.get("status") or "active") != "active":
            continue
        question = str(row.get("question") or "")
        q_row = _compact_normalize(question)
        if not q_row:
            continue
        score = 0.0
        if q_norm == q_row:
            score = 1.0
        elif len(q_norm) >= 8 and q_norm in q_row:
            score = 0.96
        else:
            base_question = re.sub(r"\s*\([^)]*\)", "", question).strip()
            base_compact = _compact_normalize(base_question)
            if base_compact and q_norm == base_compact:
                score = 0.97
            else:
                sim = max(
                    SequenceMatcher(None, q_norm, q_row).ratio(),
                    SequenceMatcher(None, _thai_heavy_normalize(query), _thai_heavy_normalize(question)).ratio(),
                )
                if sim >= 0.88:
                    score = sim
        if score > 0:
            scored.append(_record_to_candidate(row, round(score, 6), source="topic_alias"))
    scored.sort(key=lambda c: c.final_score, reverse=True)
    return scored[:8]


def _ambiguous_category_candidates(query: str) -> list[RetrievalCandidate]:
    q = _normalize(query)
    categories = AMBIGUOUS_QUERY_CATEGORIES.get(q)
    if not categories:
        return []
    out: list[RetrievalCandidate] = []
    for category in categories:
        out.extend(_category_browse_candidates(category, limit=3))
    return out[:8]


def _is_probably_gibberish(query: str, *, matched: bool = False, best_candidate: RetrievalCandidate | None = None) -> bool:
    if matched:
        return False
    if best_candidate is not None and best_candidate.final_score >= 0.58:
        return False
    compact = _compact_normalize(query)
    if not compact:
        return True
    if compact in TYPO_CANONICAL_MAP or query in TYPO_CANONICAL_MAP:
        return False
    if len(compact) <= 2:
        return True
    if re.fullmatch(r"[a-z]{1,5}", compact):
        return True
    if re.fullmatch(r"[ก-๙]{1,3}", compact):
        return True
    consonants_only = re.sub(r"[ะาำิีึืุูเแโใไั็่้๊๋์0-9]", "", compact)
    if len(compact) >= 4 and len(consonants_only) == len(compact) and best_candidate is None:
        return True
    return False


def _catalog_match_score(query: str, row: dict[str, Any], category_hint: str | None = None) -> float:
    q = _normalize(query)
    q_compact = _compact_normalize(query)
    q_thai = _thai_heavy_normalize(query)
    question = str(row.get("question") or "")
    rq = _normalize(question)
    rq_compact = _compact_normalize(question)
    rq_thai = _thai_heavy_normalize(question)
    if not q or not rq:
        return 0.0
    if q == rq or q_compact == rq_compact:
        return 1.0
    if len(q_compact) >= 8 and q_compact in rq_compact:
        return 0.97
    if len(rq_compact) >= 8 and rq_compact in q_compact:
        return 0.93
    sim_full = SequenceMatcher(None, q, rq).ratio()
    sim_compact = SequenceMatcher(None, q_compact, rq_compact).ratio()
    sim_thai = SequenceMatcher(None, q_thai, rq_thai).ratio() if q_thai and rq_thai else 0.0
    q_tokens = set(_meaningful_tokens(query))
    r_tokens = set(_meaningful_tokens(question))
    keyword_tokens = set(str(k).lower() for k in row.get("keywords") or [])
    token_overlap = len(q_tokens & r_tokens) / max(len(q_tokens), 1) if q_tokens else 0.0
    keyword_overlap = len(q_tokens & keyword_tokens) / max(len(q_tokens), 1) if q_tokens else 0.0
    score = max(
        sim_full * 0.35 + sim_compact * 0.25 + sim_thai * 0.15 + token_overlap * 0.15 + keyword_overlap * 0.10,
        sim_compact * 0.55 + token_overlap * 0.25 + keyword_overlap * 0.20,
    )
    if category_hint and str(row.get("category") or "") == category_hint:
        score += 0.03
    return min(1.0, round(score, 6))


def _catalog_search(query: str, *, category: str | None = None, limit: int = 8) -> list[RetrievalCandidate]:
    rows = state.records
    if category:
        rows = [r for r in rows if str(r.get("category") or "") == category]
    scored: list[RetrievalCandidate] = []
    for row in rows:
        if str(row.get("status") or "active") != "active":
            continue
        score = _catalog_match_score(query, row, category_hint=category)
        if score >= 0.22:
            scored.append(_record_to_candidate(row, score))
    scored.sort(key=lambda c: c.final_score, reverse=True)
    return scored[:limit]


def _merge_candidates(*candidate_lists: list[RetrievalCandidate], limit: int = 10) -> list[RetrievalCandidate]:
    merged: dict[str, RetrievalCandidate] = {}
    for items in candidate_lists:
        for cand in items:
            existing = merged.get(cand.id)
            if existing is None or cand.final_score > existing.final_score:
                merged[cand.id] = cand
    out = sorted(merged.values(), key=lambda c: c.final_score, reverse=True)
    return out[:limit]


def _has_specific_match(query: str, candidate: RetrievalCandidate | None) -> bool:
    if candidate is None:
        return False
    q = _compact_normalize(query)
    cq = _compact_normalize(candidate.question)
    if not q or not cq:
        return False
    if q == cq:
        return True
    if len(q) >= 8 and q in cq:
        return True
    return candidate.final_score >= 0.82


def _detect_preferred_category(query: str) -> tuple[str | None, str | None, float]:
    q = query.strip()
    if not q:
        return None, None, 0.0
    normalized_query, typo_source = _normalize_typo(_looks_like_query_plus_noise(q))
    normalized = _normalize(normalized_query)
    compact = _compact_normalize(normalized_query)

    for override, (category, _) in TOPIC_ALIAS_OVERRIDES.items():
        ov = _compact_normalize(override)
        if ov == compact:
            return category, override, 1.0

    if normalized in AMBIGUOUS_QUERY_CATEGORIES:
        return None, normalized, 0.0

    exact_hits: list[tuple[str, str]] = []
    for category, aliases in CATEGORY_ALIASES.items():
        for option in [category, *aliases]:
            opt_norm = _normalize(option)
            opt_compact = _compact_normalize(option)
            if not opt_norm:
                continue
            if normalized == opt_norm or compact == opt_compact:
                exact_hits.append((category, option))
            elif len(opt_compact) >= 3 and opt_compact in compact:
                exact_hits.append((category, option))
            elif len(compact) >= 3 and compact in opt_compact and len(compact) >= max(3, len(opt_compact) - 2):
                exact_hits.append((category, option))
    if exact_hits:
        category, option = exact_hits[0]
        return category, (typo_source or option), 1.0

    category, option, score = _best_alias_match(normalized_query)
    if category and score >= 0.80:
        return category, (typo_source or option), score

    if len(compact) <= 4:
        if category and score >= 0.72:
            return category, (typo_source or option), score
        return None, (typo_source or option if typo_source else None), 0.0

    q_tokens = set(_meaningful_tokens(normalized_query))
    best_pair = None
    best_score = 0.0
    for category, aliases in CATEGORY_ALIASES.items():
        for option in [category, *aliases]:
            opt_tokens = set(_meaningful_tokens(option))
            token_overlap = len(q_tokens & opt_tokens) / max(len(q_tokens), 1) if q_tokens else 0.0
            score = max(
                token_overlap,
                SequenceMatcher(None, normalized, _normalize(option)).ratio() * 0.60 + token_overlap * 0.40,
                SequenceMatcher(None, _thai_heavy_normalize(normalized_query), _thai_heavy_normalize(option)).ratio() * 0.60 + token_overlap * 0.40,
            )
            if score > best_score:
                best_pair = (category, option)
                best_score = score
    if best_pair and best_score >= 0.58:
        return best_pair[0], (typo_source or best_pair[1]), best_score
    return None, (typo_source or None), 0.0


def _category_browse_candidates(category: str, limit: int = 8) -> list[RetrievalCandidate]:
    rows = [r for r in state.records if str(r.get("category") or "").strip() == category]
    out: list[RetrievalCandidate] = []
    for row in rows[:limit]:
        out.append(
            RetrievalCandidate(
                id=str(row.get("id") or ""),
                category=str(row.get("category") or ""),
                subcategory=str(row.get("subcategory") or ""),
                question=str(row.get("question") or ""),
                answer=str(row.get("answer") or ""),
                notes=str(row.get("notes") or ""),
                department=row.get("department"),
                contact=row.get("contact"),
                last_updated_at=row.get("last_updated_at"),
                status=str(row.get("status") or "active"),
                metadata=row,
            )
        )
    return out


def _is_broad_category_query(query: str, category_hint: str | None) -> bool:
    if not query.strip() or category_hint is None:
        return False
    q = _normalize(query)
    return len(q) <= 18 or len(q.split()) <= 2


def _should_category_overview(query: str, category_hint: str | None, category_candidates: list[RetrievalCandidate], matched_alias: str | None, best_candidate: RetrievalCandidate | None) -> bool:
    if not category_hint:
        return False
    q = _normalize(query)
    matched_norm = _normalize(matched_alias or "")
    category_norm = _normalize(category_hint)
    broad = q in {matched_norm, category_norm} or _is_broad_category_query(query, category_hint)
    if broad and len(category_candidates) >= 1 and not _has_specific_match(query, best_candidate):
        return True
    return False


def _unknown_specific_in_category(query: str, category_hint: str | None, best_candidate: RetrievalCandidate | None, matched_alias: str | None) -> bool:
    if not category_hint:
        return False
    q = _normalize(query)
    if q in {_normalize(category_hint), _normalize(matched_alias or "")}:
        return False
    if SPECIFIC_AVAILABILITY_RE.search(query):
        return not _has_specific_match(query, best_candidate)
    return len(q) >= 15 and not _has_specific_match(query, best_candidate)


def _is_follow_up_query(query: str) -> bool:
    q = _normalize(query)
    generic_phrases = {"ราคาเท่าไหร่", "เท่าไหร่", "ติดต่อที่ไหน", "เปิดวันไหน", "เปิดกี่โมง", "เข้าได้เลยไหม", "มีไหม"}
    if q in generic_phrases:
        return True
    return len(q) <= 18 and bool(FOLLOW_UP_RE.search(q))


def _topic_follow_up_buttons(topic: RetrievalCandidate) -> list[str]:
    category_title = display_category_name(topic.category)
    buttons = ["ราคาเท่าไหร่", "ติดต่อที่ไหน", "เปิดวันไหน", f"กลับไปหมวด{category_title}"]
    seen: list[str] = []
    for b in buttons:
        if b not in seen:
            seen.append(b)
    return seen


def _category_action_buttons(category: str, candidates: list[RetrievalCandidate]) -> list[str]:
    buttons = [c.question for c in candidates[:6] if c.question]
    buttons.append("กลับหน้าแรก")
    seen: list[str] = []
    for b in buttons:
        if b not in seen:
            seen.append(b)
    return seen[:8]


def _remember(session: SessionMemory, *, category: str | None, topic: RetrievalCandidate | None = None, buttons: list[str] | None = None) -> None:
    if category:
        session.last_category = category
    if topic is not None:
        session.last_topic_id = topic.id
        session.last_topic_question = topic.question
        session.last_category = topic.category
    if buttons is not None:
        session.last_buttons = buttons[:8]
    session.touch()


def _find_candidate_by_id(candidate_id: str | None) -> RetrievalCandidate | None:
    if not candidate_id:
        return None
    for row in state.records:
        if str(row.get("id") or "") == candidate_id:
            return _record_to_candidate(row, 1.0)
    return None


def _answer_from_topic_follow_up(query: str, session: SessionMemory) -> RetrievalCandidate | None:
    topic = _find_candidate_by_id(session.last_topic_id)
    if topic is None:
        return None
    combined = f"{topic.question} {query}"
    candidates = _catalog_search(combined, category=session.last_category, limit=5)
    if candidates and candidates[0].final_score >= 0.65:
        return candidates[0]
    return topic if _is_follow_up_query(query) else None


def _generate_answer(query: str, top: RetrievalCandidate, candidates: list[RetrievalCandidate], use_llm: bool) -> str:
    """Generate answer using LLM if available; fall back to KB direct answer."""
    model_state = runtime_summary(SERVING_LOCK_PATH)
    t_start = time.time()

    if use_llm and model_state.get("configured_provider") == "ollama":
        model_name = model_state.get("runtime_model", "")
        endpoint = model_state.get("runtime_endpoint", "http://127.0.0.1:11434")
        try:
            payload = {
                "model": model_name,
                "messages": build_llm_messages(query, top, candidates),
                "stream": False,
                "options": {"temperature": 0.1, "num_ctx": 2048},
            }
            logger.info("🤖 LLM call → model=%s endpoint=%s query='%s'", model_name, endpoint, query[:60])
            response = requests.post(
                f"{endpoint}/api/chat",
                json=payload,
                timeout=OLLAMA_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "").strip()
            latency = round(time.time() - t_start, 2)
            if content:
                logger.info("✅ LLM answer returned in %.2fs", latency)
                return content
            else:
                logger.warning("⚠️  LLM returned empty content after %.2fs", latency)
        except requests.exceptions.Timeout:
            latency = round(time.time() - t_start, 2)
            logger.error("⏱️  LLM timeout after %.2fs (limit=%ds) — using KB fallback", latency, OLLAMA_TIMEOUT_SECONDS)
        except requests.exceptions.ConnectionError:
            logger.error("🔌 LLM connection error (Ollama not running?) — using KB fallback")
        except Exception as exc:
            latency = round(time.time() - t_start, 2)
            logger.error("❌ LLM error after %.2fs: %s — using KB fallback", latency, exc)

    # KB direct answer fallback
    return format_direct_answer(top)


# ── Request / Response models ─────────────────────────────────────────────────
class ChatRequest(BaseModel):
    question: str | None = Field(default=None)
    message: str | None = Field(default=None, description="Legacy frontend compatibility field")
    top_k: int = Field(10, ge=1, le=20)
    preferred_category: str | None = None
    use_llm: bool = True
    session_id: str = "default"

    @model_validator(mode="after")
    def normalize_question(self) -> "ChatRequest":
        self.question = (self.question or self.message or "").strip()
        if not self.question:
            raise ValueError("question or message is required")
        return self


class CandidateResponse(BaseModel):
    id: str
    category: str
    subcategory: str
    question: str
    answer: str
    final_score: float
    vector_score: float
    keyword_score: float
    rerank_score: float
    stale: bool
    last_updated_at: str | None = None


class ChatResponse(BaseModel):
    route: Literal["answer", "clarify", "fallback"]
    answer: str
    confidence: float
    reason: str
    warnings: list[str] = []
    source_id: str | None = None
    selected_category: str | None = None
    clarification_options: list[str] = []
    action_buttons: list[str] = []
    candidates: list[CandidateResponse] = []
    handoff_required: bool = False
    handoff_ticket_id: int | None = None
    admin_reply: str | None = None


class GuideResponse(BaseModel):
    welcome_message: str
    supported_topics: list[str]
    topic_examples: dict[str, list[str]] = {}


# ── Handoff request models ─────────────────────────────────────────────────────
class HandoffRespondRequest(BaseModel):
    ticket_id: int
    response_text: str
    responder: str = "admin"
    close_ticket: bool = True


class HandoffTakeoverRequest(BaseModel):
    ticket_id: int
    responder: str = "admin"


class HandoffLiveMessageRequest(BaseModel):
    ticket_id: int
    responder: str = "admin"
    message_text: str
    close_ticket: bool = False


# ── Internal helpers ──────────────────────────────────────────────────────────
def _should_create_handoff(response: ChatResponse) -> bool:
    if response.handoff_required:
        return True
    if response.reason in {"unclear_input", "typo_recoverable"}:
        return False
    if response.route == "fallback" and HITL_FALLBACK_ALWAYS:
        return True
    if response.route in {"fallback", "clarify"} and response.confidence < HITL_CONFIDENCE_THRESHOLD:
        return True
    return False


def _finalize_chat_response(req: ChatRequest, session: SessionMemory, query: str, response: ChatResponse) -> ChatResponse:
    admin_reply = fetch_session_responses(ANALYTICS_DB_PATH, req.session_id, limit=1)
    if admin_reply:
        latest = admin_reply[0]
        response.admin_reply = latest.get("response_text")
    if _should_create_handoff(response):
        ticket_id = create_handoff_ticket(
            ANALYTICS_DB_PATH,
            session_id=req.session_id,
            question=query,
            category=response.selected_category,
            confidence=response.confidence,
            route=response.route,
            reason=response.reason,
            candidate_ids=[c.id for c in response.candidates],
            source_id=response.source_id,
        )
        response.handoff_required = True
        response.handoff_ticket_id = ticket_id
        if response.route == "fallback":
            response.answer = response.answer + "\n\n" + handoff_waiting_text(ticket_id)
    log_chat_request(
        ANALYTICS_DB_PATH,
        session_id=req.session_id,
        question=query,
        route=response.route,
        category=response.selected_category,
        confidence=response.confidence,
        reason=response.reason,
        source_id=response.source_id,
        warnings=response.warnings,
        handoff_required=response.handoff_required,
        handoff_ticket_id=response.handoff_ticket_id,
    )
    return response


def _category_examples_payload(limit: int = 4) -> dict[str, list[str]]:
    return {display_category_name(k): v[:limit] for k, v in state.category_examples.items()}


def _to_candidate_response(candidate: RetrievalCandidate) -> CandidateResponse:
    return CandidateResponse(
        id=candidate.id,
        category=candidate.category,
        subcategory=candidate.subcategory,
        question=candidate.question,
        answer=candidate.answer,
        final_score=round(candidate.final_score, 6),
        vector_score=round(candidate.vector_score, 6),
        keyword_score=round(candidate.keyword_score, 6),
        rerank_score=round(candidate.rerank_score, 6),
        stale=candidate.stale,
        last_updated_at=candidate.last_updated_at,
    )


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/admin-ui")
def admin_ui() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "admin.html")


@app.get("/admin/live-ui")
def admin_live_ui() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "admin_live.html")


@app.get("/health")
def health() -> dict[str, Any]:
    model_state = runtime_summary(SERVING_LOCK_PATH)
    return {
        "status": "ok" if state.retriever is not None else "index_missing",
        "kb_records": len(state.records),
        "retriever": "ready" if state.retriever is not None else "missing",
        "collection": CHROMA_COLLECTION,
        "db_dir": CHROMA_DB_DIR,
        "ollama_enabled": bool(model_state.get("runtime_endpoint") and model_state.get("runtime_model")),
        "model": model_state,
        "timestamp": now_bangkok_iso(),
    }


@app.get("/health/ollama")
def health_ollama() -> dict[str, Any]:
    """Quick Ollama connectivity and model list check."""
    model_state = runtime_summary(SERVING_LOCK_PATH)
    endpoint = model_state.get("runtime_endpoint", "http://127.0.0.1:11434")
    try:
        r = requests.get(f"{endpoint}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        configured_model = model_state.get("runtime_model", "")
        model_available = any(configured_model in m for m in models)
        return {
            "status": "ok",
            "endpoint": endpoint,
            "available_models": models,
            "configured_model": configured_model,
            "configured_model_available": model_available,
        }
    except Exception as exc:
        return {"status": "error", "endpoint": endpoint, "error": str(exc)}


@app.get("/health/kb")
def health_kb() -> dict[str, Any]:
    """Knowledge base readiness check."""
    return {
        "status": "ok" if state.records else "empty",
        "record_count": len(state.records),
        "category_count": len(state.category_examples),
        "jsonl_exists": KNOWLEDGE_JSONL.exists(),
        "jsonl_path": str(KNOWLEDGE_JSONL),
        "retriever_ready": state.retriever is not None,
    }


@app.get("/guide", response_model=GuideResponse)
def guide() -> GuideResponse:
    return GuideResponse(
        welcome_message=WELCOME_MESSAGE,
        supported_topics=[display_category_name(k) for k in state.category_examples.keys()] or GUIDE_ITEMS,
        topic_examples=_category_examples_payload(),
    )


@app.get("/guide/tree")
def guide_tree() -> dict[str, Any]:
    return {
        "topic_tree": build_topic_tree(state.records),
        "generated_at": now_bangkok_iso(),
    }


@app.get("/admin/auth/check")
def admin_auth_check(principal: AdminPrincipal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return {"ok": True, "role": principal.role, "auth_type": principal.auth_type, "subject": principal.subject}


@app.get("/admin/model-config")
def admin_model_config(principal: AdminPrincipal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return runtime_summary(SERVING_LOCK_PATH)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    t_start = time.time()
    query = req.question.strip()
    logger.info("📨 /chat session=%s query='%s'", req.session_id[:12], query[:80])

    # ── KB not ready — friendly fallback instead of 503 ──
    if not state.records and state.retriever is None:
        logger.warning("⚠️  KB not ready — returning friendly fallback for query: %s", query)
        return ChatResponse(
            route="fallback",
            answer=(
                "ขออภัยครับ/ค่ะ ขณะนี้ฐานข้อมูลโรงพยาบาลยังไม่พร้อมใช้งาน "
                "กรุณาติดต่อผู้ดูแลระบบเพื่อ build ฐานความรู้ก่อน "
                "หรือโทรสายด่วน 054-466666 ต่อ 7221/7222 ครับ/ค่ะ"
            ),
            confidence=0.0,
            reason="kb_not_ready",
            action_buttons=GUIDE_ITEMS[:6],
        )

    session = state.get_session(req.session_id)
    normalized_query, typo_source = _normalize_typo(_looks_like_query_plus_noise(query))
    if typo_source and normalized_query != query:
        query = normalized_query

    if BACK_RE.search(query):
        if session.last_category:
            category_candidates = _category_browse_candidates(session.last_category)
            buttons = _category_action_buttons(session.last_category, category_candidates)
            _remember(session, category=session.last_category, buttons=buttons)
            return ChatResponse(
                route="clarify",
                answer=build_category_overview(session.last_category, [c.question for c in category_candidates]),
                confidence=0.95,
                reason="session_back_to_category",
                selected_category=session.last_category,
                clarification_options=buttons,
                action_buttons=buttons,
                candidates=[_to_candidate_response(c) for c in category_candidates[:5]],
            )
        return ChatResponse(route="clarify", answer=WELCOME_MESSAGE, confidence=0.8, reason="session_back_home", action_buttons=GUIDE_ITEMS)

    if EMERGENCY_RE.search(query):
        response = ChatResponse(route="fallback", answer=emergency_text(), confidence=0.99, reason="emergency_redirect", action_buttons=["ฉุกเฉิน 1669", "ติดต่อแผนกฉุกเฉิน"])
        return _finalize_chat_response(req, session, query, response)

    category_hint, matched_alias, alias_score = _detect_preferred_category(req.preferred_category or query)
    if category_hint is None and session.last_category and _is_follow_up_query(query):
        category_hint = session.last_category
        matched_alias = session.last_category
        alias_score = 0.7

    if session.last_topic_id and _is_follow_up_query(query):
        follow_topic = _answer_from_topic_follow_up(query, session)
        if follow_topic is not None:
            answer = _generate_answer(f"{session.last_topic_question} {query}", follow_topic, [follow_topic], use_llm=req.use_llm)
            buttons = _topic_follow_up_buttons(follow_topic)
            buttons.insert(0, session.last_topic_question or follow_topic.question)
            _remember(session, category=follow_topic.category, topic=follow_topic, buttons=buttons)
            response = ChatResponse(
                route="answer",
                answer=answer + "\n\n" + build_followup_hint_text(follow_topic.category, follow_topic.question),
                confidence=0.9,
                reason="session_follow_up_answer",
                source_id=follow_topic.id,
                selected_category=follow_topic.category,
                action_buttons=buttons[:6],
                candidates=[_to_candidate_response(follow_topic)],
            )
            return _finalize_chat_response(req, session, query, response)

    category_browse = _category_browse_candidates(category_hint) if category_hint else []
    catalog_in_category = _catalog_search(query, category=category_hint, limit=req.top_k) if category_hint else []
    catalog_global = _catalog_search(query, category=None, limit=req.top_k)
    best_catalog = catalog_in_category[0] if catalog_in_category else (catalog_global[0] if catalog_global else None)

    ambiguous = _ambiguous_category_candidates(query)
    if ambiguous and not category_hint:
        clarification_options = [display_category_name(c.category) for c in ambiguous]
        response = ChatResponse(
            route="clarify",
            answer=ambiguous_term_text(query, [c.category for c in ambiguous]),
            confidence=0.74,
            reason="ambiguous_common_term",
            clarification_options=clarification_options,
            action_buttons=clarification_options,
            candidates=[_to_candidate_response(c) for c in ambiguous[:5]],
        )
        return _finalize_chat_response(req, session, query, response)

    if _is_probably_gibberish(query, matched=bool(category_hint), best_candidate=best_catalog):
        response = ChatResponse(
            route="fallback",
            answer=typo_recovery_text(typo_source) if typo_source else unclear_input_text(),
            confidence=0.92,
            reason="unclear_input",
            action_buttons=GUIDE_ITEMS[:8],
            candidates=[],
        )
        return _finalize_chat_response(req, session, query, response)

    if _should_category_overview(query, category_hint, category_browse, matched_alias, best_catalog):
        buttons = _category_action_buttons(category_hint or "", category_browse)
        _remember(session, category=category_hint, buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer=build_category_overview(category_hint or "", [c.question for c in category_browse], corrected_from=matched_alias if matched_alias and matched_alias != category_hint else None),
            confidence=round(max(alias_score, 0.76), 4),
            reason="category_overview",
            selected_category=category_hint,
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[_to_candidate_response(c) for c in category_browse[:5]],
        )
        return _finalize_chat_response(req, session, query, response)

    if _unknown_specific_in_category(query, category_hint, best_catalog, matched_alias):
        buttons = _category_action_buttons(category_hint or "", category_browse)
        _remember(session, category=category_hint, buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer=build_category_not_found_text(query, category_hint or "", [c.question for c in category_browse]),
            confidence=round(max(alias_score, 0.58), 4),
            reason="category_specific_not_found",
            selected_category=category_hint,
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[_to_candidate_response(c) for c in category_browse[:5]],
        )
        return _finalize_chat_response(req, session, query, response)

    if _has_specific_match(query, best_catalog):
        answer = _generate_answer(query, best_catalog, [best_catalog], use_llm=req.use_llm)
        buttons = _topic_follow_up_buttons(best_catalog)
        _remember(session, category=best_catalog.category, topic=best_catalog, buttons=buttons)
        response = ChatResponse(
            route="answer",
            answer=answer + "\n\n" + build_followup_hint_text(best_catalog.category, best_catalog.question),
            confidence=round(best_catalog.final_score, 4),
            reason="direct_catalog_match",
            source_id=best_catalog.id,
            selected_category=best_catalog.category,
            action_buttons=buttons,
            candidates=[_to_candidate_response(best_catalog)],
        )
        append_audit_event(AUDIT_LOG_PATH, {"event_type": "chat", "question": query, "route": response.route, "reason": response.reason, "source_id": response.source_id})
        latency = round(time.time() - t_start, 3)
        logger.info("✅ /chat done route=%s reason=%s latency=%.3fs", response.route, response.reason, latency)
        return response

    retrieved: list[RetrievalCandidate] = []
    if state.retriever is not None:
        retrieved = state.retriever.search(query=query, top_k=req.top_k, category=category_hint)
        if not retrieved and category_hint:
            retrieved = state.retriever.search(query=query, top_k=req.top_k, category=None)

    merged = _merge_candidates(catalog_in_category, catalog_global, retrieved, limit=req.top_k)
    reranked = state.reranker.rerank(query, merged)
    decision = decide(query, reranked)

    if decision.action == "fallback" and category_hint:
        buttons = _category_action_buttons(category_hint, category_browse)
        _remember(session, category=category_hint, buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer=build_category_overview(category_hint, [c.question for c in category_browse], corrected_from=matched_alias if matched_alias and matched_alias != category_hint else None),
            confidence=round(max(alias_score, 0.60), 4),
            reason="fallback_to_category_overview",
            selected_category=category_hint,
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[_to_candidate_response(c) for c in category_browse[:5]],
        )
        return _finalize_chat_response(req, session, query, response)

    if decision.action == "fallback":
        response = ChatResponse(
            route="fallback",
            answer=fallback_text(),
            confidence=decision.confidence,
            reason=decision.reason,
            warnings=decision.warnings,
            action_buttons=GUIDE_ITEMS[:8],
            candidates=[_to_candidate_response(c) for c in reranked[:5]],
        )
        return _finalize_chat_response(req, session, query, response)

    if decision.action == "clarify":
        clarification_options = build_clarification_options(reranked)
        session_category = reranked[0].category if reranked else category_hint
        _remember(session, category=session_category, buttons=clarification_options)
        response = ChatResponse(
            route="clarify",
            answer=build_clarification_text(query, reranked),
            confidence=decision.confidence,
            reason=decision.reason,
            warnings=decision.warnings,
            selected_category=session_category,
            clarification_options=clarification_options,
            action_buttons=clarification_options,
            candidates=[_to_candidate_response(c) for c in reranked[:5]],
        )
        return _finalize_chat_response(req, session, query, response)

    top = reranked[0]
    answer = _generate_answer(query, top, reranked[:4], use_llm=req.use_llm)
    buttons = _topic_follow_up_buttons(top)
    _remember(session, category=top.category, topic=top, buttons=buttons)
    response = ChatResponse(
        route="answer",
        answer=answer + "\n\n" + build_followup_hint_text(top.category, top.question),
        confidence=decision.confidence,
        reason=decision.reason,
        warnings=decision.warnings,
        source_id=top.id,
        selected_category=top.category,
        action_buttons=buttons,
        candidates=[_to_candidate_response(c) for c in reranked[:5]],
    )
    latency = round(time.time() - t_start, 3)
    logger.info("✅ /chat done route=%s reason=%s latency=%.3fs", response.route, response.reason, latency)
    return _finalize_chat_response(req, session, query, response)


# ── Admin routes ──────────────────────────────────────────────────────────────
@app.get("/admin/status")
def admin_status(principal: AdminPrincipal = Depends(require_role("viewer"))) -> dict[str, Any]:
    records = load_jsonl_records(KNOWLEDGE_JSONL)
    manifest = load_manifest(MANIFEST_PATH)
    return {
        "manifest": manifest,
        "health": health(),
        "paths": {
            "workbook": str(WORKBOOK_PATH),
            "knowledge_jsonl": str(KNOWLEDGE_JSONL),
            "knowledge_csv": str(KNOWLEDGE_CSV),
            "validation_report": str(VALIDATION_REPORT_PATH),
            "manifest": str(MANIFEST_PATH),
            "evaluation_report": str(EVAL_REPORT_PATH),
            "audit_log": str(AUDIT_LOG_PATH),
            "serving_model_lock": str(SERVING_LOCK_PATH),
            "analytics_db": str(ANALYTICS_DB_PATH),
        },
        "record_count": len(records),
        "stale_summary": stale_summary(records),
        "audit_count": len(tail_audit_events(AUDIT_LOG_PATH, limit=1000000)),
        "analytics_summary": analytics_summary(ANALYTICS_DB_PATH),
    }


@app.get("/admin/records")
def admin_records(limit: int = Query(200, ge=1, le=2000), category: str | None = None, principal: AdminPrincipal = Depends(require_role("viewer"))) -> dict[str, Any]:
    records = load_jsonl_records(KNOWLEDGE_JSONL)
    if category:
        records = [r for r in records if str(r.get("category")) == category]
    return {"records": records[:limit], "total": len(records)}


@app.get("/admin/audit")
def admin_audit(limit: int = Query(100, ge=1, le=1000), principal: AdminPrincipal = Depends(require_role("admin"))) -> dict[str, Any]:
    return {"events": tail_audit_events(AUDIT_LOG_PATH, limit=limit)}


@app.get("/admin/evaluation/summary")
def admin_eval_summary(principal: AdminPrincipal = Depends(require_role("viewer"))) -> dict[str, Any]:
    if not EVAL_REPORT_PATH.exists():
        return {}
    return json.loads(EVAL_REPORT_PATH.read_text(encoding="utf-8"))


@app.get("/admin/request-logs")
def admin_request_logs(limit: int = Query(200, ge=1, le=2000), category: str | None = None, route: str | None = None, principal: AdminPrincipal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return {"items": list_request_logs(ANALYTICS_DB_PATH, limit=limit, category=category, route=route)}


@app.get("/admin/analytics/summary")
def admin_analytics_summary(principal: AdminPrincipal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return analytics_summary(ANALYTICS_DB_PATH)


@app.get("/admin/handoff/queue")
def admin_handoff_queue(status: str = Query("open"), limit: int = Query(200, ge=1, le=2000), principal: AdminPrincipal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return {"items": list_handoff_tickets(ANALYTICS_DB_PATH, status=status, limit=limit)}


@app.get("/admin/handoff/stream")
def admin_handoff_stream(status: str = Query("open"), principal: AdminPrincipal = Depends(require_role("viewer"))):
    def event_gen():
        last_payload = None
        while True:
            items = list_handoff_tickets(ANALYTICS_DB_PATH, status=status, limit=100)
            payload = json.dumps({"items": items, "ts": now_bangkok_iso()}, ensure_ascii=False)
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            time.sleep(2)
    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/admin/handoff/takeover")
def admin_handoff_takeover(payload: HandoffTakeoverRequest, principal: AdminPrincipal = Depends(require_role("editor"))) -> dict[str, Any]:
    result = claim_ticket(ANALYTICS_DB_PATH, ticket_id=payload.ticket_id, responder=payload.responder or principal.subject)
    append_audit_event(AUDIT_LOG_PATH, {"event_type": "handoff_takeover", "ticket_id": payload.ticket_id, "responder": payload.responder or principal.subject})
    return result


@app.post("/admin/handoff/live-message")
def admin_handoff_live_message(payload: HandoffLiveMessageRequest, principal: AdminPrincipal = Depends(require_role("editor"))) -> dict[str, Any]:
    result = append_live_message(ANALYTICS_DB_PATH, ticket_id=payload.ticket_id, responder=payload.responder or principal.subject, message_text=payload.message_text, close_ticket=payload.close_ticket)
    append_audit_event(AUDIT_LOG_PATH, {"event_type": "handoff_live_message", "ticket_id": payload.ticket_id, "responder": payload.responder or principal.subject, "close_ticket": payload.close_ticket})
    return result


@app.post("/admin/handoff/respond")
def admin_handoff_respond(payload: HandoffRespondRequest, principal: AdminPrincipal = Depends(require_role("editor"))) -> dict[str, Any]:
    result = respond_to_ticket(ANALYTICS_DB_PATH, ticket_id=payload.ticket_id, response_text=payload.response_text, responder=payload.responder or principal.subject, close_ticket=payload.close_ticket)
    append_audit_event(AUDIT_LOG_PATH, {"event_type": "handoff_response", "ticket_id": payload.ticket_id, "responder": payload.responder or principal.subject, "close_ticket": payload.close_ticket})
    return result


@app.get("/chat/admin-replies")
def chat_admin_replies(session_id: str = Query(...), limit: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
    return {"items": fetch_session_responses(ANALYTICS_DB_PATH, session_id=session_id, limit=limit)}


@app.get("/chat/session-events")
def chat_session_events(session_id: str = Query(...), after_id: int = Query(0, ge=0)):
    def event_gen():
        cursor = after_id
        while True:
            items = fetch_session_responses_after(ANALYTICS_DB_PATH, session_id=session_id, after_id=cursor, limit=50)
            for item in items:
                cursor = max(cursor, int(item.get("message_id") or 0))
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            time.sleep(2)
    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/admin/upload-workbook")
async def upload_workbook(file: UploadFile = File(...), principal: AdminPrincipal = Depends(require_role("editor"))) -> dict[str, Any]:
    WORKBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WORKBOOK_PATH.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    append_audit_event(AUDIT_LOG_PATH, {"event_type": "upload_workbook", "filename": file.filename})
    return {"saved_to": str(WORKBOOK_PATH), "filename": file.filename}


@app.post("/admin/rebuild")
def admin_rebuild(reset_index: bool = True, principal: AdminPrincipal = Depends(require_role("editor"))) -> dict[str, Any]:
    build_cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "build_kb.py"),
        "--input", str(WORKBOOK_PATH),
        "--jsonl-output", str(KNOWLEDGE_JSONL),
        "--csv-output", str(KNOWLEDGE_CSV),
        "--report-output", str(VALIDATION_REPORT_PATH),
        "--manifest-output", str(MANIFEST_PATH),
    ]
    subprocess.run(build_cmd, check=True)
    reindex_cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "reindex_kb.py"),
        "--knowledge", str(KNOWLEDGE_JSONL),
        "--db-dir", CHROMA_DB_DIR,
        "--collection", CHROMA_COLLECTION,
    ]
    if reset_index:
        reindex_cmd.append("--reset")
    subprocess.run(reindex_cmd, check=True)
    state.reload_retriever()
    append_audit_event(AUDIT_LOG_PATH, {"event_type": "rebuild", "reset_index": reset_index})
    return {"status": "ok", "reset_index": reset_index}


@app.post("/admin/run-evaluation")
def admin_run_evaluation(principal: AdminPrincipal = Depends(require_role("editor"))) -> dict[str, Any]:
    details_path = DATA_DIR / "evaluation_details.jsonl"
    report_path = DATA_DIR / "evaluation_report.json"
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "evaluate.py"),
        "--test-set", str(DATA_DIR / "regression_test_set_realistic.jsonl"),
        "--report-output", str(report_path),
        "--details-output", str(details_path),
        "--manifest", str(MANIFEST_PATH),
    ]
    subprocess.run(cmd, check=True)
    append_audit_event(AUDIT_LOG_PATH, {"event_type": "run_evaluation"})
    return json.loads(report_path.read_text(encoding="utf-8"))


# ── Static UI Routes ─────────────────────────────────────────────────────────

@app.get("/admin-ui")
def get_admin_ui():
    """Serves the static admin.html console."""
    admin_path = FRONTEND_DIR / "admin.html"
    if not admin_path.exists():
        raise HTTPException(status_code=404, detail="admin.html not found")
    return FileResponse(admin_path)


@app.get("/guide")
def get_guide():
    """Serves the static index.html or guide page."""
    guide_path = FRONTEND_DIR / "index.html"
    if not guide_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(guide_path)


@app.get("/")
def get_root():
    """Simple root redirect or status message."""
    return {"status": "UP Hospital Chatbot API", "version": "20.0.0", "admin_ui": "/admin-ui"}
