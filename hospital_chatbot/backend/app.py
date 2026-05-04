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

import hashlib
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
from functools import lru_cache
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
    UPH_MAIN_PHONE,
    WELCOME_MESSAGE,
    build_category_not_found_text,
    build_category_overview,
    build_clarification_options,
    build_clarification_text,
    build_grounded_llm_messages,
    build_llm_messages,
    clean_user_visible_answer,
    dedupe_answer_lines,
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
SCHEDULE_IMAGE_DIR = DATA_DIR / "ตารางออกตรวจแพทย์"
HEALTH_CHECK_IMAGE_DIR = DATA_DIR / "ตรวจสุขภาพประจำปี"

WORKBOOK_PATH = Path(os.getenv("WORKBOOK_PATH", str(DATA_DIR / "AIคำถามคำตอบงานสื่อสาร01.04.69.xlsx")))
KNOWLEDGE_JSONL = Path(os.getenv("KNOWLEDGE_JSONL", str(DATA_DIR / "knowledge.jsonl")))
KNOWLEDGE_CSV = Path(os.getenv("KNOWLEDGE_CSV", str(DATA_DIR / "knowledge.csv")))
VALIDATION_REPORT_PATH = Path(os.getenv("VALIDATION_REPORT_PATH", str(DATA_DIR / "kb_validation_report.json")))
MANIFEST_PATH = Path(os.getenv("MANIFEST_PATH", str(DATA_DIR / "kb_manifest.json")))
EVAL_REPORT_PATH = Path(os.getenv("EVAL_REPORT_PATH", str(DATA_DIR / "evaluation_report.json")))
AUDIT_LOG_PATH = Path(os.getenv("AUDIT_LOG_PATH", str(LOG_DIR / "audit.jsonl")))
SERVING_LOCK_PATH = Path(os.getenv("SERVING_MODEL_LOCK_PATH", str(PROJECT_ROOT / DEFAULT_LOCK_PATH)))
ANALYTICS_DB_PATH = Path(os.getenv("ANALYTICS_DB_PATH", str(DATA_DIR / "chatbot_analytics.db")))

ALLOWED_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
ASSET_ROOTS: dict[str, Path] = {
    "schedule": SCHEDULE_IMAGE_DIR,
    "health-check": HEALTH_CHECK_IMAGE_DIR,
}

HITL_CONFIDENCE_THRESHOLD = float(os.getenv("HITL_CONFIDENCE_THRESHOLD", "0.60"))
HITL_FALLBACK_ALWAYS = os.getenv("HITL_FALLBACK_ALWAYS", "true").strip().lower() in {"1", "true", "yes", "y"}

OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))
CHROMA_DB_DIR = os.getenv("CHROMA_DB_DIR", "chroma_db")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "hospital_faq")
FOLLOWUP_TTL_SECONDS = int(os.getenv("SESSION_MEMORY_TTL_SECONDS", "1800"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
TYPHOON_API_KEY = os.getenv("TYPHOON_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TYPHOON_MODEL = os.getenv("TYPHOON_MODEL", "typhoon-v1.5x-70b-instruct")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
# kb_exact: returns raw KB answer for matches; llm_grounded: lets LLM paraphrase with KB context
ANSWER_MODE = os.getenv("ANSWER_MODE", "kb_exact").strip().lower()
RAG_GROUNDED_LLM = os.getenv("RAG_GROUNDED_LLM", "0").strip().lower() in {"1", "true", "yes", "y", "on"}
MENU_MODE = os.getenv("MENU_MODE", "tree_first").strip().lower()
FOLLOWUP_MODE = os.getenv("FOLLOWUP_MODE", "slot_first").strip().lower()

FALLBACK_ACTION_BUTTONS = ["กลับหน้าหลัก", "ติดต่อโรงพยาบาล"]


def _official_fallback_answer() -> str:
    return f"ไม่พบข้อมูลนี้ในระบบปัจจุบัน กรุณาติดต่อโรงพยาบาลมหาวิทยาลัยพะเยา โทร {UPH_MAIN_PHONE} เพื่อสอบถามเพิ่มเติม"


def _official_contact_answer() -> str:
    return f"ติดต่อโรงพยาบาลมหาวิทยาลัยพะเยา โทร {UPH_MAIN_PHONE}"


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def _lifespan(application: FastAPI):
    logger.info("🚀 Hospital Chatbot API starting up…")
    init_request_log_db(ANALYTICS_DB_PATH)
    logger.info("✅ Analytics DB ready: %s", ANALYTICS_DB_PATH)
    try:
        logger.info("⏳ Loading retriever and knowledge base…")
        state.reload_retriever()
        logger.info("✅ Retriever ready. %d records loaded.", len(state.records))
    except Exception as exc:
        logger.warning("⚠️  Retriever failed to load (will run in KB-only mode): %s", exc)
        state.retriever = None
        state.rebuild_catalog()
        logger.info("📚 KB-only mode. %d records loaded from JSONL.", len(state.records))
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
        "วัคซีนฟรีนักศึกษา", "วัคซีน hpv นักศึกษา", "วัคซีนมะเร็งปากมดลูกฟรี",
        "นักศึกษา วัคซีน", "สิทธิ นักศึกษา", "ฟรี นักศึกษา", "hpv นักศึกษา",
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
    "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย": [
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
    "นักศึกษา วัคซีน": ("สวัสดิการวัคซีนนักศึกษา", None),
    "สิทธิ นักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "ฟรี นักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "hpv นักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "วัคซีนhpvนักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "วัคซีน hpv นักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "วัคซีนhpvสำหรับนักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "วัคซีนฟรีนักศึกษา": ("สวัสดิการวัคซีนนักศึกษา", None),
    "วัคซีนมะเร็งปากมดลูกฟรี": ("สวัสดิการวัคซีนนักศึกษา", None),
    # Blood bank
    "ธนาคารเลือดและบริจาคเลือด": ("ธนาคารเลือดและบริจาคเลือด", None),
    "บริจาคเลือด": ("ธนาคารเลือดและบริจาคเลือด", None),
    "ติดต่อธนาคารเลือด": ("ธนาคารเลือดและบริจาคเลือด", None),
    # Dental
    "หมอฟัน": ("คลินิกทันตกรรม", None),
    "ทันตกรรม": ("คลินิกทันตกรรม", None),
    # Kidney
    "ฟอกไต": ("ศูนย์ไตเทียม", None),
    # Gynecology
    "สูติ": ("สูตินรีเวช", None),
    "นรีเวช": ("สูตินรีเวช", None),
    "สูตินรีเวช": ("สูตินรีเวช", None),
}

AMBIGUOUS_QUERY_CATEGORIES: dict[str, list[str]] = {
    "หมอ": ["ตารางแพทย์และเวลาทำการ", "การจัดการนัดหมาย"],
    "แพทย์": ["ตารางแพทย์และเวลาทำการ", "การจัดการนัดหมาย"],
    "คุณหมอ": ["ตารางแพทย์และเวลาทำการ", "การจัดการนัดหมาย"],
    "ศูนย์": ["ศูนย์ไตเทียม", "ตรวจสุขภาพรายบุคคล"],
    "สิทธิ": ["ประเมินค่าใช้จ่ายทั่วไป", "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย", "ศูนย์ไตเทียม"],
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
    # Appointment typos
    "นัฐ": "นัด",
    "เลื่อนนัฐ": "เลื่อนนัด",
    "นัฐพบแพทย์": "นัดพบแพทย์",
}

EMERGENCY_RE = re.compile(r"แน่นหน้าอก|หายใจไม่ออก|หมดสติ|ชัก|ฉุกเฉิน|1669", re.IGNORECASE)
FOLLOW_UP_RE = re.compile(r"ราคา|เท่าไหร่|เท่าไร|ติดต่อ|ที่ไหน|เปิด|วันไหน|เวลา|เข้าได้เลยไหม|เข้ามาได้เลยไหม|เข้ามาได้ไหม|มีไหม|ยังไง|มีรูป|ขอดูรูป|มีภาพ|ไฟล์|ลิงก์", re.IGNORECASE)

# Specific image/file follow-up phrases (context-sensitive to active schedule topic)
IMAGE_FOLLOW_UP_RE = re.compile(r"มีรูปไหม|มีภาพไหม|ขอดูรูป|มีไฟล์ไหม|มีลิงก์ไหม", re.IGNORECASE)
BACK_RE = re.compile(r"^กลับ|ย้อนกลับ|กลับไปหมวด", re.IGNORECASE)
SPECIFIC_AVAILABILITY_RE = re.compile(r"มีไหม|มีมั้ย|มีหรือไม่|มีรึเปล่า|มีเปล่า", re.IGNORECASE)
QUERY_STOPWORDS = {
    "ราคา", "เท่าไหร่", "เท่าไร", "เข้ามาได้เลยไหม", "เข้ามาได้ไหม", "ได้ไหม", "มีไหม", "ไหม",
    "ขอ", "สอบถาม", "เรื่อง", "ข้อมูล", "ของ", "ที่", "และ", "หรือ", "ครับ", "ค่ะ", "คะ",
    "บริการ", "หน่อย", "ที", "หน่อยครับ", "หน่อยค่ะ", "ให้หน่อย", "บ้าง", "อะไร", "ยังไง",
}


def _is_follow_up_query(query: str) -> bool:
    """Check if query is a follow-up question that should bind to current topic."""
    return bool(FOLLOW_UP_RE.search(query))


def _is_image_follow_up(query: str) -> bool:
    """Check if query is an image/file follow-up (context-sensitive to schedule topics)."""
    return bool(IMAGE_FOLLOW_UP_RE.search(query))


# ── Main theme buttons (shown on reset / first open) ─────────────────────────
MAIN_THEME_BUTTONS = [
    "นัดหมายและตารางแพทย์",
    "วัคซีนและบริการผู้ป่วยนอก",
    "เวชระเบียน สิทธิ และค่าใช้จ่าย",
    "ตรวจสุขภาพและใบรับรองแพทย์",
    "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
]

# Map displayed main-theme buttons to canonical category keys present in KB rows.
MAIN_THEME_CANONICAL: dict[str, str] = {
    "นัดหมายและตารางแพทย์": "นัดหมายและตารางแพทย์",
    "วัคซีนและบริการผู้ป่วยนอก": "วัคซีน",
    "เวชระเบียน สิทธิ และค่าใช้จ่าย": "ประเมินค่าใช้จ่ายทั่วไป",
    "ตรวจสุขภาพและใบรับรองแพทย์": "ตรวจสุขภาพรายบุคคล",
    "ติดต่อหน่วยงานเฉพาะและสมัครงาน": "กลุ่มงานบุคคล",
}

# Explicit child-button lists for each main theme (shown when user clicks main theme button)
MAIN_THEME_CHILDREN: dict[str, list[str]] = {
    "นัดหมายและตารางแพทย์": [
        "การจัดการนัดหมาย",
        "ตารางแพทย์และเวลาทำการ",
        "กลับหน้าหลัก",
    ],
    "วัคซีนและบริการผู้ป่วยนอก": [
        "วัคซีน HPV",
        "วัคซีนบาดทะยัก/พิษสุนัขบ้า",
        "วัคซีนไข้หวัดใหญ่",
        "วัคซีนไวรัสตับอักเสบบี",
        "กลับหน้าหลัก",
    ],
    "เวชระเบียน สิทธิ และค่าใช้จ่าย": [
        "ขอประวัติการรักษา",
        "ค่าใช้จ่ายในการรักษา",
        "ย้ายสิทธิการรักษา / ตรวจสอบสิทธิ",
        "กลับหน้าหลัก",
    ],
    "ตรวจสุขภาพและใบรับรองแพทย์": [
        "ตรวจสุขภาพรายบุคคล",
        "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย",
        "การขอเอกสารทางการแพทย์",
        "กลับหน้าหลัก",
    ],
    "ติดต่อหน่วยงานเฉพาะและสมัครงาน": [
        "ศูนย์ไตเทียม",
        "ธนาคารเลือดและบริจาคเลือด",
        "คลินิกทันตกรรม",
        "กลุ่มงานบุคคล",
        "กลับหน้าหลัก",
    ],
}

# Map canonical category back to its parent main-theme label
CATEGORY_TO_MAIN_THEME: dict[str, str] = {}
for _theme, _children in MAIN_THEME_CHILDREN.items():
    for _child in _children:
        if _child != "กลับหน้าหลัก":
            CATEGORY_TO_MAIN_THEME[_child] = _theme
# Also map canonical names
CATEGORY_TO_MAIN_THEME.update({
    "นัดหมายและตารางแพทย์": "นัดหมายและตารางแพทย์",
    "การจัดการนัดหมาย": "นัดหมายและตารางแพทย์",
    "ตารางแพทย์และเวลาทำการ": "นัดหมายและตารางแพทย์",
    "วัคซีน": "วัคซีนและบริการผู้ป่วยนอก",
    "สวัสดิการวัคซีนนักศึกษา": "วัคซีนและบริการผู้ป่วยนอก",
    "ประเมินค่าใช้จ่ายทั่วไป": "เวชระเบียน สิทธิ และค่าใช้จ่าย",
    "ตรวจสุขภาพรายบุคคล": "ตรวจสุขภาพและใบรับรองแพทย์",
    "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย": "ตรวจสุขภาพและใบรับรองแพทย์",
    "การขอเอกสารทางการแพทย์": "ตรวจสุขภาพและใบรับรองแพทย์",
    "ศูนย์ไตเทียม": "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
    "ธนาคารเลือดและบริจาคเลือด": "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
    "คลินิกทันตกรรม": "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
    "กลุ่มงานบุคคล": "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
})

# OPD specialty list shown when user asks broad schedule question
SCHEDULE_SPECIALTY_MENU: list[str] = [
    "ระบบทางเดินปัสสาวะ",
    "ทั่วไป (GP)",
    "อายุรกรรม",
    "สุขภาพจิตชุมชน",
    "เวชศาสตร์ครอบครัว",
    "ผิวหนัง",
    "ตรวจสุขภาพ",
    "อายุรแพทย์ผู้สูงอายุ",
    "อายุรแพทย์มะเร็งวิทยา",
    "สูตินรีเวช",
    "จักษุแพทย์ (ตา)",
    "หู คอ จมูก",
    "กุมารแพทย์",
    "กุมารแพทย์ โรคหัวใจ",
    "อายุรแพทย์โรคหัวใจ",
    "ระบบประสาทและสมอง",
    "ศัลยแพทย์กระดูกและข้อ",
    "เวชศาสตร์การกีฬา",
    "ออร์โธปิดิคส์บูรณสภาพ",
    "กลับไปหมวดนัดหมายและตารางแพทย์",
]

SCHEDULE_DEPARTMENT_MENU: list[str] = [
    "ค้นหาตามเฉพาะทาง",
    "ผู้ป่วยนอก 1/OPD 1",
    "ผู้ป่วยนอก 2/OPD 2",
    "ผู้ป่วยนอก 3/OPD 3",
    "ผู้ป่วยนอก 4/OPD 4",
    "ศูนย์ศัลยกรรมกระดูกและข้อ",
    "กลับไปหมวดนัดหมายและตารางแพทย์",
]

HEALTH_CHECK_SHORTCUTS: dict[str, tuple[str, str]] = {
    "เวลาตรวจสุขภาพ": ("qa-0050", "ตรวจสุขภาพรายบุคคล"),
    "โปรแกรมตรวจสุขภาพ": ("qa-0049", "ตรวจสุขภาพรายบุคคล"),
    "ใบรับรองแพทย์": ("qa-0053", "การขอเอกสารทางการแพทย์"),
}

HEALTH_CHECK_PROGRAM_ANSWER = (
    "ติดต่อแผนกตรวจสุขภาพ โทร 054 466 666 ต่อ 7173 เวลา 08.00-16.00 น. "
    "ทุกวันทำการ หยุดทุกวันเสาร์-อาทิตย์ และวันหยุดนักขัตฤกษ์ หรือแอดไลน์ @897idbib"
)
HEALTH_CHECK_HOURS_ANSWER = (
    "เวลา 08.00-16.00 น. ทุกวันทำการ หยุดทุกวันเสาร์-อาทิตย์ "
    "และวันหยุดนักขัตฤกษ์ หรือแอดไลน์ @897idbib"
)
HEALTH_CHECK_CERTIFICATE_ANSWER = HEALTH_CHECK_PROGRAM_ANSWER

SCHEDULE_DEPARTMENT_SPECIALTIES: dict[str, list[str]] = {
    "ผู้ป่วยนอก 1/OPD 1": [
        "ระบบทางเดินปัสสาวะ",
        "ทั่วไป (GP)",
        "อายุรกรรม",
        "สุขภาพจิตชุมชน",
        "เวชศาสตร์ครอบครัว",
        "กลับไปเลือกแผนกตารางแพทย์",
    ],
    "ผู้ป่วยนอก 2/OPD 2": [
        "ผิวหนัง",
        "ตรวจสุขภาพ",
        "อายุรแพทย์ผู้สูงอายุ",
        "อายุรแพทย์มะเร็งวิทยา",
        "กลับไปเลือกแผนกตารางแพทย์",
    ],
    "ผู้ป่วยนอก 3/OPD 3": [
        "สูตินรีเวช",
        "จักษุแพทย์ (ตา)",
        "หู คอ จมูก",
        "กุมารแพทย์",
        "กุมารแพทย์ โรคหัวใจ",
        "กลับไปเลือกแผนกตารางแพทย์",
    ],
    "ผู้ป่วยนอก 4/OPD 4": [
        "อายุรแพทย์โรคหัวใจ",
        "ระบบประสาทและสมอง",
        "กลับไปเลือกแผนกตารางแพทย์",
    ],
    "ศูนย์ศัลยกรรมกระดูกและข้อ": [
        "เวชศาสตร์การกีฬา",
        "ออร์โธปิดิคส์บูรณสภาพ",
        "ศัลยแพทย์กระดูกและข้อ",
        "กลับไปเลือกแผนกตารางแพทย์",
    ],
}

CANONICAL_CATEGORY_RULES: dict[str, dict[str, Any]] = {
    "การจัดการนัดหมาย": {
        "raw_category": "นัดหมายและตารางแพทย์",
        "subcategories": {"ขอเลื่อนนัดพบแพทย์", "ลืมวันนัด / เช็ควันนัด"},
    },
    "ตารางแพทย์และเวลาทำการ": {
        "raw_category": "นัดหมายและตารางแพทย์",
        "subcategories": {"ตารางแพทย์ออกตรวจ", "เวลาทำการแผนกผู้ป่วยนอก"},
    },
    "วัคซีน": {"raw_category": "วัคซีนและบริการผู้ป่วยนอก"},
    "สวัสดิการวัคซีนนักศึกษา": {"raw_category": "วัคซีนและบริการผู้ป่วยนอก"},
    "ตรวจสุขภาพรายบุคคล": {
        "raw_category": "ตรวจสุขภาพและใบรับรองแพทย์",
        "subcategories": {"โปรแกรมตรวจสุขภาพ", "เวลาตรวจสุขภาพ"},
    },
    "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย": {
        "raw_category": "ตรวจสุขภาพและใบรับรองแพทย์",
        "subcategories": {"ตรวจสุขภาพหมู่คณะ / หน่วยงาน", "ใช้สิทธิเบิกตรงตรวจสุขภาพได้ไหม"},
    },
    "การขอเอกสารทางการแพทย์": {
        "raw_category": "ตรวจสุขภาพและใบรับรองแพทย์",
        "subcategories": {"ขอใบรับรองแพทย์"},
    },
    "ประเมินค่าใช้จ่ายทั่วไป": {"raw_category": "เวชระเบียน สิทธิ และค่าใช้จ่าย"},
    "ศูนย์ไตเทียม": {
        "raw_category": "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
        "subcategories": {"หน่วยไตเทียม"},
    },
    "ธนาคารเลือดและบริจาคเลือด": {
        "raw_category": "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
        "subcategories": {"ธนาคารเลือด / บริจาคเลือด"},
    },
    "คลินิกทันตกรรม": {
        "raw_category": "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
        "subcategories": {"โรงพยาบาลทันตกรรม"},
    },
    "กลุ่มงานบุคคล": {
        "raw_category": "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
        "subcategories": {"สมัครงาน / งานบุคคล"},
    },
}

RUNTIME_QUERY_REPLACEMENTS: dict[str, str] = {
    "opd1": "opd 1",
    "opd2": "opd 2",
    "opd3": "opd 3",
    "opd4": "opd 4",
    "check up": "ตรวจสุขภาพ",
    "check-up": "ตรวจสุขภาพ",
    "ent": "หูคอจมูก",
    "วักซีน": "วัคซีน",
    "วัปซีน": "วัคซีน",
    "วคซีน": "วัคซีน",
    "หมอหนัง": "หมอผิวหนังวันไหน",
    "หมอกระดุก": "หมอกระดูก",
    "ตรจสุขภาพ": "ตรวจสุขภาพ",
    "ลืมนัด": "ลืมวันนัด",
    "เชคนัด": "เช็ควันนัด",
    "เช็คสิทธิ": "ย้ายสิทธิการรักษา ตรวจสอบสิทธิ",
    "นัดหมอ": "นัดพบแพทย์",
    "ตารางหมอ": "ตารางแพทย์ออกตรวจ",
    "หมอฟัน": "ทันตกรรม",
    "หมอทันตกรรม": "ทันตกรรม",
    "ทำฟัน": "ทันตกรรม",
    "ฟอกไต": "ไตเทียม",
    "หมอเด็ก": "กุมารแพทย์",
    "หมอตา": "จักษุแพทย์",
    "สูตินรีเวช": "สูติ นรีเวช",
    "วัคซีนตับบี": "วัคซีนไวรัสตับอักเสบบี",
    "วัคซีนบาดทะยัก": "วัคซีนบาดทะยัก พิษสุนัขบ้า",
    "วัคซีนพิษสุนัขบ้า": "วัคซีนบาดทะยัก พิษสุนัขบ้า",
    "วัคซีน hpv": "วัคซีนมะเร็งปากมดลูก",
    "วัคซีนมะเร็งปากมดลูก": "วัคซีนมะเร็งปากมดลูก",
    "วัคซีนไข้หวัดใหญ่": "วัคซีนไข้หวัดใหญ่",
    "วัคซีนอินฟลูเอนซา": "วัคซีนไข้หวัดใหญ่",
    "ตรวจสุขภาพ": "โปรแกรมตรวจสุขภาพ",
    "ตรวจร่างกาย": "โปรแกรมตรวจสุขภาพ",
    "ตรวจสุขภาพบริษัท": "ตรวจสุขภาพหมู่คณะ หน่วยงาน",
    "ตรวจสุขภาพพนักงาน": "ตรวจสุขภาพหมู่คณะ หน่วยงาน",
    "ตรวจสุขภาพหมู่คณะ": "ตรวจสุขภาพเป็นหมู่คณะหรือหน่วยงานราชการ",
    "ตรวจสุขภาพบริษัท": "ตรวจสุขภาพเป็นหมู่คณะหรือหน่วยงานราชการ",
    "ตรวจสุขภาพพนักงาน": "ตรวจสุขภาพเป็นหมู่คณะหรือหน่วยงานราชการ",
    "ใช้สิทธิเบิกตรงได้ไหม": "ใช้สิทธิเบิกตรงตรวจสุขภาพได้ไหม",
    "ใบรับรองแพทย์": "ขอใบรับรองแพทย์",
    "ใบรับรอง": "ขอใบรับรองแพทย์",
    "ใบขับขี่": "ใบรับรองแพทย์ ทำใบขับขี่",
    "ราคาเท่าไร": "ราคาเท่าไหร่",
    "สิทธิการรักษา": "ย้ายสิทธิการรักษาหรือตรวจสอบสิทธิการรักษา",
    "เวชระเบียน": "ขอประวัติการรักษา",
    "ค่ารักษา": "ค่าใช้จ่ายในการรักษา",
    "ค่าใช้จ่าย": "ค่าใช้จ่ายในการรักษา",
    "ติดต่อการเงิน": "ค่าใช้จ่ายในการรักษา",
    "ตรวจตาราคาเท่าไหร่": "ค่าใช้จ่ายในการรักษา ตรวจตาราคาเท่าไหร่",
    "ศูนย์ไตเทียม": "หน่วยไตเทียม",
    "ไตเทียม": "หน่วยไตเทียม",
    "ฟอกไต": "ที่โรงพยาบาลมีบริการฟอกไตไหม หากต้องการฟอกไตที่โรงพยาบาลมหาวิทยาลัยพะเยา ต้องทำอย่างไร",
    "ใช้สิทธิฟอกไตได้ไหม": "สามารถใช้สิทธิการรักษาอะไรได้บ้าง หรือมีค่าใช้จ่ายส่วนเกินไหม",
    "ฟอกไตใช้สิทธิไรได้บ้าง": "สามารถใช้สิทธิการรักษาอะไรได้บ้าง หรือมีค่าใช้จ่ายส่วนเกินไหม",
    "สมัครงานต้องใช้ใบรับรองไหม": "ใบรับรองแพทย์สมัครงาน",
    "มีวัคซีนสำหรับนักศึกษาไหม": "วัคซีนมะเร็งปากมดลูกฟรีมีไหม กรณีนิสิตอายุไม่เกิน 20 ปี",
    "วัคซีนสำหรับนักศึกษา": "วัคซีนมะเร็งปากมดลูกฟรีมีไหม กรณีนิสิตอายุไม่เกิน 20 ปี",
    "วัคซีนนักศึกษา": "วัคซีนมะเร็งปากมดลูกฟรีมีไหม กรณีนิสิตอายุไม่เกิน 20 ปี",
    "ให้เลือดวันไหน": "บริจาคเลือดวันไหนได้บ้าง สามารถเข้ามาได้วันไหน",
    "บริจาคเลือด": "ติดต่อธนาคารเลือด/บริจาคเลือด",
    "ธนาคารเลือด": "ติดต่อธนาคารเลือด/บริจาคเลือด",
    "หมอฟัน": "ติดต่อโรงพยาบาลทันตกรรม สอบถามเกี่ยวกับช่องปากหรือฟัน",
    "ทันตกรรม": "ติดต่อโรงพยาบาลทันตกรรม สอบถามเกี่ยวกับช่องปากหรือฟัน",
    "ทำฟัน": "ติดต่อโรงพยาบาลทันตกรรม สอบถามเกี่ยวกับช่องปากหรือฟัน",
    "สมัครงาน": "เกี่ยวกับการสมัครงาน",
    "งานบุคคล": "เกี่ยวกับการสมัครงาน",
    "มีรับสมัครงานไหม": "เกี่ยวกับการสมัครงาน",
    "ent วันไหน": "ตารางแพทย์ หูคอจมูก",
    "opd 1 เปิดกี่โมง": "ตารางแพทย์ ทั่วไป opd 1",
    "opd 2 มีหมอผิวหนังไหม": "ตารางแพทย์ ผิวหนัง opd 2",
}

FOLLOWUP_SLOT_PATTERNS: dict[str, re.Pattern[str]] = {
    "price": re.compile(r"ราคา|ค่าใช้จ่าย|กี่บาท|เท่าไหร่|เท่าไร", re.IGNORECASE),
    "contact": re.compile(r"ติดต่อ|โทร|เบอร์|ที่ไหน|line|ไลน์", re.IGNORECASE),
    "hours": re.compile(r"เปิด|วันไหน|เวลา|กี่โมง|วันทำการ", re.IGNORECASE),
    "walkin": re.compile(r"เข้าได้เลย|walk ?in|walk-in|ต้องนัด|ใช้สิทธิ|สำรองจ่าย|ต้องทำหนังสือ", re.IGNORECASE),
    "link": re.compile(r"ลิงก์|link|เว็บไซต์|facebook|เพจ", re.IGNORECASE),
    "image": re.compile(r"รูป|ภาพ|ไฟล์แนบ|ตาราง|มีรูปไหม", re.IGNORECASE),
}

SCHEDULE_QUERY_RE = re.compile(r"ตารางแพทย์|ตารางหมอ|แพทย์ออกตรวจ|หมอ.*วันไหน|ออกตรวจ|หมอ.+มีไหม|คลินิก.+วันไหน", re.IGNORECASE)

# ── Session memory ────────────────────────────────────────────────────────────
SCHEDULE_SPECIALTY_ALIASES: dict[str, list[str]] = {
    "จักษุแพทย์ (ตา)": ["หมอตา", "จักษุแพทย์", "ตา"],
    "อายุรแพทย์โรคผิวหนัง (ผิวหนัง)": ["หมอผิวหนัง", "หมอหนัง", "ผิวหนัง"],
    "ศัลยแพทย์กระดูกและข้อ": ["หมอกระดูก", "หมอกระดุก", "กระดูก", "กระดูกและข้อ"],
    "กุมารแพทย์": ["กุมารแพทย์", "หมอเด็ก", "เด็ก"],
    "กุมารแพทย์ โรคหัวใจ": ["กุมารแพทย์ โรคหัวใจ"],
    "แพทย์สูติศาสตร์และนรีเวช ฯ (สูตินรีเวช)": ["สูตินรีเวช", "สูติ", "นรีเวช", "สูติและนรีเวช"],
    "อายุรกรรม (med)": ["อายุรกรรม", "med"],
    "หู คอ จมูก": ["ent", "หูคอจมูก", "หู คอ จมูก"],
    "ผู้ป่วยนอก 1/opd 1": ["opd 1", "opd1", "ผู้ป่วยนอก 1"],
    "ผู้ป่วยนอก 2/opd 2": ["opd 2", "opd2", "ผู้ป่วยนอก 2"],
    "ผู้ป่วยนอก 3/opd 3": ["opd 3", "opd3", "ผู้ป่วยนอก 3"],
    "ผู้ป่วยนอก 4/opd 4": ["opd 4", "opd4", "ผู้ป่วยนอก 4"],
}

@dataclass(slots=True)
class SessionMemory:
    session_id: str
    last_category: str | None = None
    last_topic_id: str | None = None
    last_topic_question: str | None = None
    last_buttons: list[str] = field(default_factory=list)
    fallback_count: int = 0
    touched_at: float = field(default_factory=time.time)
    last_reset_at: float | None = None

    def touch(self) -> None:
        self.touched_at = time.time()

    def reset_context(self, auto: bool = False) -> None:
        """Clear category/topic context for fallback recovery.
        
        Args:
            auto: If True, this is an automatic reset (e.g., fallback recovery).
                  If False, this is an explicit reset (e.g., user goHome action).
        """
        self.last_category = None
        self.last_topic_id = None
        self.last_topic_question = None
        self.last_buttons = []
        self.fallback_count = 0
        # Only set last_reset_at for auto-resets, not for explicit resets
        if auto:
            self.last_reset_at = time.time()
        else:
            self.last_reset_at = None


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
    if q in {_normalize(v) for v in TYPO_CANONICAL_MAP.values()} or compact in {_compact_normalize(v) for v in TYPO_CANONICAL_MAP.values()}:
        return query, None
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


def _looks_like_query_plus_noise_legacy(query: str) -> str:
    # Legacy placeholder retained only to minimize patch churn after earlier merges.
    return query


def _looks_like_query_plus_noise(query: str) -> str:
    normalized_query = _normalize(query)
    if _is_schedule_query(query):
        return query
    if any(token in normalized_query for token in ("opd 1", "opd 2", "opd 3", "opd 4", "ent", "ตารางแพทย์", "ตารางหมอ")):
        return query
    if any(token in normalized_query for token in ("หมอฟัน", "ทันตกรรม", "หมอทันตกรรม")) and any(
        marker in normalized_query for marker in ("วันไหน", "วันนี้", "มีไหม", "เปิด", "เวลา")
    ):
        return query
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


QUERY_WRAPPER_PREFIXES = (
    "ขอสอบถาม",
    "อยากทราบ",
    "รบกวนสอบถาม",
    "ช่วยเช็กให้หน่อย",
    "ช่วยเช็คให้หน่อย",
    "ขอข้อมูล",
    "สอบถาม",
)

QUERY_POLITE_SUFFIXES = (
    "ครับ",
    "ค่ะ",
    "คะ",
    "หน่อย",
)


def _strip_runtime_wrappers(text: str) -> str:
    current = str(text or "").strip()
    if not current:
        return current
    while True:
        updated = current
        for prefix in QUERY_WRAPPER_PREFIXES:
            if updated.startswith(prefix):
                updated = updated[len(prefix):].strip()
        for suffix in QUERY_POLITE_SUFFIXES:
            if updated.endswith(suffix):
                updated = updated[: -len(suffix)].strip()
        if updated == current:
            break
        current = updated
    return current


def _menu_query_forms(text: str) -> list[str]:
    stripped = _strip_runtime_wrappers(text)
    forms = [str(text or "").strip(), stripped]
    extra_forms: list[str] = []
    for form in forms:
        cleaned = form.strip()
        if cleaned.endswith("ได้ไหม"):
            extra_forms.append(cleaned[: -len("ได้ไหม")].strip())
        if cleaned.endswith("ไหม"):
            extra_forms.append(cleaned[: -len("ไหม")].strip())
    out: list[str] = []
    for form in [*forms, *extra_forms]:
        if form and form not in out:
            out.append(form)
    return out


def _extract_menu_navigation_label(text: str) -> str | None:
    for form in _menu_query_forms(text):
        for label in MAIN_THEME_BUTTONS:
            if _looks_like_menu_label(form, label):
                return label
    return None


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


def _record_type(row: dict[str, Any] | RetrievalCandidate | None) -> str:
    if row is None:
        return ""
    if isinstance(row, RetrievalCandidate):
        row = row.metadata or {}
    return str(row.get("record_type") or "").strip()


def _parse_list_field(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except Exception:
            pass
    parts = re.split(r"\s*\|\s*|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _rewrite_runtime_query(query: str) -> str:
    text = str(query or "").strip()
    if not text:
        return text
    rewritten = re.sub(r"\s+", " ", text.lower())
    exact_replacements = {
        wrong.lower(): right.lower()
        for wrong, right in RUNTIME_QUERY_REPLACEMENTS.items()
        if " " not in wrong.strip() and len(wrong.strip()) <= 18
    }
    if rewritten in exact_replacements:
        return exact_replacements[rewritten]
    for wrong, right in RUNTIME_QUERY_REPLACEMENTS.items():
        wrong_l = wrong.lower()
        right_l = right.lower()
        if rewritten == wrong_l:
            rewritten = right_l
            continue
        if len(wrong_l) >= 8 and wrong_l in rewritten:
            rewritten = rewritten.replace(wrong_l, right_l)
    return rewritten.strip()


def _category_rule(category: str | None) -> dict[str, Any] | None:
    if not category:
        return None
    return CANONICAL_CATEGORY_RULES.get(str(category).strip())


def _row_matches_category_scope(row: dict[str, Any], category: str | None) -> bool:
    if not category:
        return True
    rule = _category_rule(category)
    row_category = str(row.get("category") or "").strip()
    row_subcategory = str(row.get("subcategory") or "").strip()
    if rule is None:
        return row_category == category
    if row_category != str(rule.get("raw_category") or "").strip():
        return False
    allowed_subcategories = set(rule.get("subcategories") or [])
    if not allowed_subcategories:
        return True
    return row_subcategory in allowed_subcategories or str(row.get("record_type") or "").strip() == "menu_node"


def _rows_for_category_scope(category: str | None) -> list[dict[str, Any]]:
    return [row for row in _active_rows() if _row_matches_category_scope(row, category)]


def _canonical_category_from_values(raw_category: str | None, subcategory: str | None, query: str = "") -> str | None:
    raw = str(raw_category or "").strip()
    sub = str(subcategory or "").strip()
    q = _normalize(query)

    for label, canonical in MAIN_THEME_CANONICAL.items():
        if raw == label and label != "นัดหมายและตารางแพทย์":
            return canonical

    if _is_schedule_query(query) and q != "นัดหมายและตารางแพทย์":
        return "ตารางแพทย์และเวลาทำการ"

    if raw == "นัดหมายและตารางแพทย์":
        if q == "นัดหมายและตารางแพทย์" and not sub:
            return "นัดหมายและตารางแพทย์"
        if sub in {"ตารางแพทย์ออกตรวจ", "เวลาทำการแผนกผู้ป่วยนอก"}:
            return "ตารางแพทย์และเวลาทำการ"
        return "การจัดการนัดหมาย"

    if raw == "วัคซีนและบริการผู้ป่วยนอก":
        if any(token in q for token in ("นักศึกษา",)):
            return "สวัสดิการวัคซีนนักศึกษา"
        return "วัคซีน"

    if raw == "ตรวจสุขภาพและใบรับรองแพทย์":
        if sub == "ขอใบรับรองแพทย์" or any(token in q for token in ("ใบรับรอง", "ใบขับขี่")):
            return "การขอเอกสารทางการแพทย์"
        if sub in {"ตรวจสุขภาพหมู่คณะ / หน่วยงาน", "ใช้สิทธิเบิกตรงตรวจสุขภาพได้ไหม"} or any(token in q for token in ("บริษัท", "หมู่คณะ", "พนักงาน", "หน่วยงาน", "เบิกตรง")):
            return "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย"
        return "ตรวจสุขภาพรายบุคคล"

    if raw == "เวชระเบียน สิทธิ และค่าใช้จ่าย":
        return "ประเมินค่าใช้จ่ายทั่วไป"

    if raw == "ติดต่อหน่วยงานเฉพาะและสมัครงาน":
        if sub == "หน่วยไตเทียม" or any(token in q for token in ("ไต", "ฟอกไต")):
            return "ศูนย์ไตเทียม"
        if sub == "ธนาคารเลือด / บริจาคเลือด" or any(token in q for token in ("เลือด", "บริจาค")):
            return "ธนาคารเลือดและบริจาคเลือด"
        if sub == "โรงพยาบาลทันตกรรม" or any(token in q for token in ("ฟัน", "ทันต")):
            return "คลินิกทันตกรรม"
        if sub == "สมัครงาน / งานบุคคล" or any(token in q for token in ("สมัครงาน", "บุคคล")):
            return "กลุ่มงานบุคคล"
        if "ใบรับรอง" in q:
            return "การขอเอกสารทางการแพทย์"
        return "กลุ่มงานบุคคล"

    for label, canonical in MAIN_THEME_CANONICAL.items():
        if raw == label:
            return canonical
    return raw or None


def _canonical_category_for_candidate(candidate: RetrievalCandidate | None, query: str = "") -> str | None:
    if candidate is None:
        return _canonical_category_from_values(None, None, query)
    meta = candidate.metadata or {}
    return _canonical_category_from_values(
        str(meta.get("category") or candidate.category or "").strip(),
        str(meta.get("subcategory") or candidate.subcategory or "").strip(),
        query,
    )


def _resolved_response_category(candidate: RetrievalCandidate | None, query: str = "", category_hint: str | None = None) -> str | None:
    q = _normalize(query)
    if candidate is not None and str(candidate.id or "") == "qa-0021":
        return "ศูนย์ไตเทียม"
    if "วัคซีน" in q and any(token in q for token in ("นักศึกษา", "นิสิต")):
        return "สวัสดิการวัคซีนนักศึกษา"
    if "วัคซีนมะเร็งปากมดลูกฟรี" in q and not any(token in q for token in ("นักศึกษา", "นิสิต")):
        return "วัคซีน"
    if any(token in q for token in ("ฟอกไต", "ไตเทียม", "ล้างไต")):
        return "ศูนย์ไตเทียม"
    if "สมัครงาน" in q and "ใบรับรอง" in q:
        return "การขอเอกสารทางการแพทย์"
    if any(token in q for token in ("ใบรับรอง", "ใบขับขี่")):
        return "การขอเอกสารทางการแพทย์"
    if any(token in q for token in ("ตรวจร่างกาย", "ตรวจสุขภาพ", "โปรแกรมตรวจสุขภาพ", "check up", "check-up")) and not any(
        token in q for token in ("บริษัท", "หมู่คณะ", "หน่วยงาน", "พนักงาน", "เบิกตรง")
    ):
        return "ตรวจสุขภาพรายบุคคล"
    if "หมอหนัง" in q or q in {"หมอผิวหนัง", "ผิวหนัง"}:
        return "ตารางแพทย์และเวลาทำการ"
    canonical = _canonical_category_for_candidate(candidate, query)
    if candidate is None:
        return canonical or category_hint
    raw_category = str(candidate.category or "").strip()
    if category_hint and raw_category in MAIN_THEME_CANONICAL and category_hint != MAIN_THEME_CANONICAL.get(raw_category, raw_category):
        return category_hint
    return canonical or category_hint or raw_category or None


def _active_rows(*, category: str | None = None, subcategory: str | None = None, record_type: str | None = None) -> list[dict[str, Any]]:
    rows = [r for r in state.records if str(r.get("status") or "active") == "active"]
    if category is not None:
        rows = [r for r in rows if str(r.get("category") or "").strip() == category]
    if subcategory is not None:
        rows = [r for r in rows if str(r.get("subcategory") or "").strip() == subcategory]
    if record_type is not None:
        rows = [r for r in rows if str(r.get("record_type") or "").strip() == record_type]
    return rows


def _unique_category_children(category: str) -> list[str]:
    children: list[str] = []
    for row in _rows_for_category_scope(category):
        if _record_type(row) in {"menu_node"}:
            continue
        child = str(row.get("subcategory") or "").strip()
        if child and child not in children:
            children.append(child)
    return children


def _child_topic_leaf_rows(category: str, child_topic: str) -> list[dict[str, Any]]:
    rows = [
        r for r in _rows_for_category_scope(category)
        if str(r.get("subcategory") or "").strip() == child_topic
        if _record_type(r) in {"faq_leaf", "guidance", "schedule_specific"}
    ]
    rows.sort(key=lambda r: (-float(r.get("source_priority") or 0), str(r.get("question") or "")))
    return rows


def _looks_like_exact(text: str, target: str) -> bool:
    q = _compact_normalize(text)
    t = _compact_normalize(target)
    return bool(q and t and (q == t or q in t or t in q))


def _looks_like_menu_label(text: str, target: str) -> bool:
    q = _compact_normalize(text)
    t = _compact_normalize(target)
    return bool(q and t and q == t)


def _detect_followup_slot(query: str) -> str | None:
    for slot, pattern in FOLLOWUP_SLOT_PATTERNS.items():
        if pattern.search(query):
            return slot
    return None


def _extract_slot_from_text(text: str, slot: str) -> str:
    if slot == "price":
        matches = re.findall(r"[^.\n]*\d[\d,]*(?:\.\d+)?\s*บาท[^.\n]*", text)
        return "\n".join([m.strip() for m in matches if m.strip()])
    if slot == "contact":
        matches = re.findall(r"(?:0\d[\d\s-]{6,}\d)(?:\s*ต่อ\s*\d+)?", text)
        return "\n".join([m.strip() for m in matches if m.strip()])
    if slot == "hours":
        matches = re.findall(r"(?:วัน[^\n]*?|ทุกวัน[^\n]*?)(?:\d{1,2}[.:]\d{2}\s*-\s*\d{1,2}[.:]\d{2}\s*น\.?|หยุด[^\n]*)", text)
        return "\n".join([m.strip() for m in matches if m.strip()])
    if slot == "link":
        matches = re.findall(r"https?://[^\s)>\]]+", text)
        return "\n".join([m.strip() for m in matches if m.strip()])
    return ""


def _slot_value(topic: RetrievalCandidate, slot: str) -> str:
    meta = topic.metadata or {}
    if slot == "image":
        return "\n".join(_parse_list_field(meta.get("followup_image_paths")))
    value = str(meta.get(f"followup_{slot}") or "").strip()
    if value:
        return value
    fallback_text = str(meta.get("answer") or topic.answer or "")
    return _extract_slot_from_text(fallback_text, slot)


def _build_followup_slot_answer(topic: RetrievalCandidate, query: str) -> str | None:
    slot = _detect_followup_slot(query)
    if not slot:
        return None
    value = _slot_value(topic, slot)
    if value:
        return clean_user_visible_answer(value)
    contact = _slot_value(topic, "contact")
    if contact:
        return clean_user_visible_answer(contact)
    return "ยังไม่มีรายละเอียดเฉพาะเรื่องนี้ในระบบค่ะ"


def _is_schedule_query(query: str) -> bool:
    if SCHEDULE_QUERY_RE.search(query):
        return True
    compact = _compact_normalize(query)
    if not compact:
        return False
    direct_markers = [
        "ตารางแพทย์",
        "ตารางหมอ",
        "หมอกระดูก",
        "หมอผิวหนัง",
        "หมอตา",
        "สูตินรีเวช",
        "กุมารแพทย์",
        "หมอเด็ก",
        "ent",
        "อายุรกรรม",
        "ทันตกรรม",
        "หมอฟัน",
        "หมอทันตกรรม",
        "opd1",
        "opd2",
        "opd3",
        "opd4",
    ]
    intent_markers = ["วันไหน", "วันนี้", "มีไหม", "เปิด", "เวลา", "ออกตรวจ", "ตาราง"]
    if any(_compact_normalize(marker) in compact for marker in direct_markers) and any(marker in query for marker in intent_markers):
        return True
    for aliases in SCHEDULE_SPECIALTY_ALIASES.values():
        for alias in aliases:
            alias_compact = _compact_normalize(alias)
            if alias_compact and alias_compact in compact:
                if "วันไหน" in query or "วันนี้" in query or "มีไหม" in query or "เปิด" in query or "เวลา" in query:
                    return True
    return False


def _schedule_rows() -> list[dict[str, Any]]:
    return _active_rows(category="นัดหมายและตารางแพทย์", subcategory="ตารางแพทย์ออกตรวจ", record_type="schedule_specific")


SCHEDULE_TOPIC_ROW_OVERRIDES: dict[str, list[str]] = {
    "จักษุแพทย์ (ตา)": [
        "- วันจันทร์วันพุธ 08.00-16.00 น. : นายแพทย์ดนัยภัทร วงษ์วรศรีโรจน์",
        "- วันพุธ 08.00-12.00 น. : ยังไม่ระบุชื่อแพทย์ในข้อมูล",
        "- วันอังคาร 08.00-12.00 น. : แพทย์หญิงชญานี วิวัฒนเศรษฐ์",
        "- วันพฤหัสบดี 08.00-16.00 น. : ยังไม่ระบุชื่อแพทย์ในข้อมูล",
    ],
}


def _schedule_row_entries_from_text(answer: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for raw_line in str(answer or "").splitlines():
        line = str(raw_line or "").strip()
        if not line.startswith("-"):
            continue
        body = line[1:].strip()
        if ":" in body:
            left, right = body.split(":", 1)
            entries.append((left.strip(), right.strip() or "ยังไม่ระบุชื่อแพทย์ในข้อมูล"))
        elif body:
            entries.append((body, "ยังไม่ระบุชื่อแพทย์ในข้อมูล"))
    return entries


def _doctor_aliases(doctor_name: str) -> set[str]:
    doctor = str(doctor_name or "").strip()
    if not doctor or doctor == "ยังไม่ระบุชื่อแพทย์ในข้อมูล":
        return set()
    aliases = {doctor}
    for title in ("นายแพทย์", "แพทย์หญิง", "นพ.", "พญ."):
        if doctor.startswith(title):
            stripped = doctor[len(title):].strip()
            if stripped:
                first_name = stripped.split()[0]
                aliases.update({stripped, first_name, f"หมอ{first_name}", f"{title}{first_name}"})
    parts = doctor.split()
    if parts:
        aliases.add(parts[-1])
        if len(parts) >= 2:
            aliases.add(parts[-2] if parts[0] in {"นายแพทย์", "แพทย์หญิง", "นพ.", "พญ."} and len(parts) >= 3 else parts[0])
    return {alias for alias in aliases if alias}


def _match_schedule_doctor(query: str) -> dict[str, Any] | None:
    qc = _compact_normalize(query)
    if not qc:
        return None

    # BUG 3 FIX: Add stricter matching rules to prevent generic words from matching doctor names
    generic_words = {
        "สุขภาพ", "จิต", "ชุมชน", "ตรวจสุขภาพ", "อายุรกรรม",
        "ผู้สูงอายุ", "คลินิก", "แพทย์", "หมอ", "นพ", "พญ",
        "โรงพยาบาล", "แผนก", "บริการ", "ตรวจ", "รักษา",
    }
    if qc in generic_words or len(qc) <= 2:
        return None

    # Check if query has explicit doctor intent markers
    doctor_intent_markers = {"หมอ", "แพทย์", "นพ", "พญ", "นายแพทย์", "แพทย์หญิง"}
    has_explicit_doctor_intent = any(marker in query for marker in doctor_intent_markers)

    matches: list[dict[str, Any]] = []
    min_alias_len = 2 if len(qc) <= 3 else 3
    for row in _schedule_rows():
        topic = _record_to_candidate(row, 0.95, source="schedule")
        specialty = str((topic.metadata or {}).get("topic") or topic.question or "").strip()
        for day_text, doctor_name in _schedule_row_entries_from_text(topic.answer):
            for alias in _doctor_aliases(doctor_name):
                alias_compact = _compact_normalize(alias)
                if not alias_compact or len(alias_compact) < min_alias_len:
                    continue
                score = 0.0
                if qc == alias_compact:
                    score = 1.0
                elif alias_compact in qc and len(alias_compact) >= 3:
                    # BUG 3 FIX: Stricter scoring - require higher confidence
                    if len(qc) >= 6 or has_explicit_doctor_intent:
                        score = 0.96
                elif qc in alias_compact and len(qc) >= 4:
                    # BUG 3 FIX: Stricter scoring - require higher confidence
                    if len(qc) >= 5 or has_explicit_doctor_intent:
                        score = 0.94
                if score:
                    matches.append({
                        "topic": topic,
                        "doctor": doctor_name,
                        "specialty": specialty,
                        "day_text": day_text,
                        "score": score,
                    })
                    break
    if not matches:
        return None
    matches.sort(key=lambda item: (-item["score"], item["doctor"], item["day_text"]))
    # BUG 3 FIX: Require higher confidence threshold
    if matches[0]["score"] < 0.94:
        return None
    unique_doctors = list(dict.fromkeys(item["doctor"] for item in matches))
    if len(unique_doctors) > 1 and len(qc) <= 2:
        return {"ambiguous_doctors": unique_doctors[:5]}
    top_doctor = matches[0]["doctor"]
    top_matches = [item for item in matches if item["doctor"] == top_doctor]
    return {"topic": top_matches[0]["topic"], "doctor": top_doctor, "rows": top_matches}


def _format_schedule_doctor_answer(match: dict[str, Any]) -> str:
    topic = match["topic"]
    doctor_name = str(match["doctor"] or "").strip()
    specialty = str((topic.metadata or {}).get("topic") or topic.question or "").strip()
    department = str((topic.metadata or {}).get("clinic") or topic.department or "").strip()
    lines = [f"{doctor_name} ออกตรวจเฉพาะทาง{specialty} ที่{department}"]
    seen_rows: set[str] = set()
    for row in match.get("rows", []):
        day_text = str(row.get("day_text") or "").strip()
        if day_text and day_text not in seen_rows:
            seen_rows.add(day_text)
            lines.append(f"- {day_text}")
    return clean_user_visible_answer("\n".join(lines))


def _match_schedule_record(query: str) -> RetrievalCandidate | None:
    qn = _normalize(query)
    qc = _compact_normalize(query)
    requested_specialties: set[str] = set()
    requested_clinics: set[str] = set()
    for key, values in SCHEDULE_SPECIALTY_ALIASES.items():
        for alias in values:
            alias_compact = _compact_normalize(alias)
            if alias_compact and alias_compact in qc:
                requested_specialties.add(key)
    for clinic_alias in ("ผู้ป่วยนอก 1/OPD 1", "ผู้ป่วยนอก 2/OPD 2", "ผู้ป่วยนอก 3/OPD 3", "ผู้ป่วยนอก 4/OPD 4"):
        clinic_alias_compact = _compact_normalize(clinic_alias)
        if clinic_alias_compact and clinic_alias_compact in qc:
            requested_clinics.add(clinic_alias)
    best: tuple[dict[str, Any] | None, float] = (None, 0.0)
    for row in _schedule_rows():
        specialty = str(row.get("topic") or row.get("specialty") or "").strip()
        aliases = _parse_list_field(row.get("aliases"))
        clinic = str(row.get("clinic") or row.get("department") or "").strip()
        keywords = [str(k).strip() for k in (row.get("keywords") or []) if str(k).strip()]
        runtime_aliases: list[str] = []
        row_specialties: set[str] = set()
        specialty_compact = _compact_normalize(specialty)
        clinic_compact = _compact_normalize(clinic)
        question_compact = _compact_normalize(str(row.get("question") or ""))
        for key, values in SCHEDULE_SPECIALTY_ALIASES.items():
            key_compact = _compact_normalize(key)
            if key_compact and (
                key_compact == specialty_compact
                or key_compact == clinic_compact
                or key_compact == question_compact
                or key_compact in specialty_compact
                or specialty_compact in key_compact
                or key_compact in question_compact
            ):
                row_specialties.add(key)
                runtime_aliases.extend(values)
        if requested_specialties and not (requested_specialties & row_specialties):
            continue
        if requested_clinics:
            clinic_match = False
            for clinic_alias in requested_clinics:
                clinic_alias_compact = _compact_normalize(clinic_alias)
                if clinic_alias_compact and (
                    clinic_alias_compact == clinic_compact
                    or clinic_alias_compact in clinic_compact
                    or clinic_compact in clinic_alias_compact
                    or clinic_alias_compact in question_compact
                ):
                    clinic_match = True
                    break
            if not clinic_match:
                continue
        for option in [specialty, clinic, row.get("question", ""), row.get("note", ""), *aliases, *keywords, *runtime_aliases]:
            opt = str(option or "").strip()
            if not opt:
                continue
            on = _normalize(opt)
            oc = _compact_normalize(opt)
            if qc and oc and len(oc) >= 3 and oc in qc:
                score = 0.99
                if score > best[1]:
                    best = (row, score)
                continue
            score = max(
                SequenceMatcher(None, qn, on).ratio(),
                SequenceMatcher(None, qc, oc).ratio(),
            )
            if qc and (qc in oc or oc in qc):
                score = max(score, 0.96 if len(oc) >= 3 else score)
            if qc and len(qc) >= 4 and len(oc) >= 4:
                query_parts = re.findall(r"[ก-๙a-z0-9]{4,}", qc)
                if any(part in oc for part in query_parts):
                    score = max(score, 0.88)
            option_tokens = {tok for tok in _meaningful_tokens(opt) if len(tok) >= 2}
            query_tokens = {tok for tok in _meaningful_tokens(query) if len(tok) >= 2}
            if option_tokens and query_tokens and (option_tokens & query_tokens):
                score = max(score, 0.90)
            if score > best[1]:
                best = (row, score)
    if best[0] is not None and best[1] >= 0.62:
        return _record_to_candidate(best[0], best[1], source="schedule")
    return None


@dataclass
class ScheduleMasterRow:
    day_text: str
    time_text: str
    doctor_name: str
    subspecialty: str = ""
    department: str = ""


@dataclass
class ScheduleMasterEntry:
    specialty: str
    department: str = ""
    aliases: list[str] = field(default_factory=list)
    rows: list[ScheduleMasterRow] = field(default_factory=list)
    image_filenames: list[str] = field(default_factory=list)
    source_id: str | None = None
    has_hidden_rows: bool = False


SCHEDULE_UNNAMED_PUBLIC_NOTICE = "บางช่วงเวลาในรูปตารางอาจยังไม่ระบุชื่อแพทย์ กรุณาดูรูปประกอบค่ะ"
SCHEDULE_GENERIC_ALIASES = {
    "ตารางแพทย์",
    "ตารางแพทย์ออกตรวจ",
    "นัดหมายและตารางแพทย์",
    "นัดหมาย",
    "วันนัด",
    "opd",
    "หมอ",
    "แพทย์",
    "med",
}
SCHEDULE_SOURCE_TO_CANONICAL: dict[str, str] = {
    "จักษุแพทย์ (ตา)": "จักษุแพทย์ (ตา)",
    "ระบบทางเดินปัสสาวะ": "ระบบทางเดินปัสสาวะ",
    "อายุรแพทย์โรคผิวหนัง (ผิวหนัง)": "ผิวหนัง",
    "โสต ศอ นาสิกแพทย์ (หูคอจมูก)": "หู คอ จมูก",
    "แพทย์สูติศาสตร์และนรีเวช ฯ (สูตินรีเวช)": "สูตินรีเวช",
    "กุมารแพทย์": "กุมารแพทย์",
    "กุมารแพทย์ โรคหัวใจ": "กุมารแพทย์ โรคหัวใจ",
    "อายุรกรรม (Med)": "อายุรกรรม",
    "อายุรแพทย์ ระบบประสาทและสมอง": "ระบบประสาทและสมอง",
    "อายุรแพทย์ผู้สูงอายุ": "อายุรแพทย์คลินิกผู้สูงอายุ",
    "อายุรแพทย์มะเร็งวิทยา": "อายุรแพทย์มะเร็งวิทยา",
    "อายุรแพทย์โรคหัวใจ": "อายุรแพทย์โรคหัวใจ",
    "ทั่วไป (GP)": "ทั่วไป",
    "สุขภาพจิตชุมชน": "สุขภาพจิตชุมชน",
    "เวชศาสตร์ป้องกัน (ตรวจสุขภาพ)": "ตรวจสุขภาพ",
    "ออร์โธปิดิคส์บูรณสภาพ": "ออร์โธปิดิคส์บูรณสภาพ",
}
SCHEDULE_CANONICAL_ALIASES: dict[str, list[str]] = {
    "ระบบทางเดินปัสสาวะ": ["ทางเดินปัสสาวะ", "หมอทางเดินปัสสาวะ", "urology"],
    "ผิวหนัง": ["อายุรแพทย์โรคผิวหนัง", "หมอผิวหนัง", "หมอหนัง", "คลินิกผิวหนัง"],
    "จักษุแพทย์ (ตา)": ["จักษุแพทย์", "หมอตา", "ตา", "จักษุ"],
    "หู คอ จมูก": ["หูคอจมูก", "หมอหูคอจมูก", "ent", "โสต ศอ นาสิกแพทย์"],
    "กุมารแพทย์": ["กุมาร", "หมอเด็ก", "เด็ก"],
    "กุมารแพทย์ โรคหัวใจ": ["กุมารแพทย์โรคหัวใจ", "กุมารแพทย์ โรคหัวใจ", "เด็กโรคหัวใจ"],
    "สูตินรีเวช": ["สูติ", "นรีเวช", "สูติและนรีเวช"],
    "ศัลยแพทย์กระดูกและข้อ": ["หมอกระดูก", "กระดูก", "กระดูกและข้อ", "ออร์โธ", "orthopedic"],
    "เวชศาสตร์การกีฬา": ["เวชศาสตร์", "เวชศาสตร์กีฬา"],
    "อายุรกรรม": ["อายุรแพทย์", "อายุรแพทย์ทั่วไป", "อายุรกรรม med", "internal medicine"],
    "อายุรแพทย์โรคหัวใจ": ["อายุรแพทย์โรคหัวใจ", "อายุรแพทย์ หัวใจ", "หมอหัวใจ"],
    "รังสีวินิจฉัย": ["รังสี", "รังสีวินิจฉัย"],
    "สุขภาพจิตชุมชน": ["สุขภาพจิตชุมชน", "จิตชุมชน"],
    "ตรวจสุขภาพ": ["ตรวจสุขภาพ", "เวชศาสตร์ป้องกัน", "เวชศาสตร์ป้องกัน (ตรวจสุขภาพ)"],
    "อายุรแพทย์คลินิกผู้สูงอายุ": ["อายุรแพทย์ผู้สูงอายุ", "อายุรแพทย์คลินิกผู้สูงอายุ"],
    "อายุรแพทย์มะเร็งวิทยา": ["อายุรแพทย์มะเร็งวิทยา", "มะเร็งวิทยา"],
    "ระบบประสาทและสมอง": ["ระบบประสาทและสมอง", "อายุรแพทย์ระบบประสาทและสมอง", "อายุรแพทย์ ระบบประสาทและสมอง"],
    "ออร์โธปิดิคส์บูรณสภาพ": ["ออร์โธปิดิคส์บูรณสภาพ", "ออร์โธปิดิคส์", "บูรณสภาพ"],
}

# BUG 8 FIX: Add canonical constants for validation
CANONICAL_SCHEDULE_SPECIALTIES = frozenset(SCHEDULE_CANONICAL_ALIASES.keys())
CANONICAL_CATEGORIES = frozenset([
    "นัดหมายและตารางแพทย์",
    "วัคซีนและบริการผู้ป่วยนอก",
    "เวชระเบียน สิทธิ และค่าใช้จ่าย",
    "ตรวจสุขภาพและใบรับรองแพทย์",
    "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
])

logger = logging.getLogger(__name__)
SCHEDULE_CANONICAL_IMAGE_MAP: dict[str, tuple[str, ...]] = {
    "ระบบทางเดินปัสสาวะ": ("ทางเดินปัสสาวะ.png",),
    "ผิวหนัง": ("ผิวหนัง.png",),
    "จักษุแพทย์ (ตา)": ("ตา.png",),
    "หู คอ จมูก": ("หูคอจมูก.png",),
    "กุมารแพทย์": ("กุมารแพทย์.png",),
    "กุมารแพทย์ โรคหัวใจ": ("กุมารแพทย์.png",),
    "สูตินรีเวช": ("สูติ-นรีเวช.jpg",),
    "ศัลยแพทย์กระดูกและข้อ": ("กระดูกและข้อ.png",),
    "เวชศาสตร์การกีฬา": ("เวชศาสตร์.png",),
    "เวชศาสตร์ครอบครัว": ("เวชศาสตร์.png",),
    "เวชศาสตร์ป้องกัน (ตรวจสุขภาพ)": ("เวชศาสตร์.png",),
    "ตรวจสุขภาพ": ("เวชศาสตร์.png",),
    "สุขภาพจิตชุมชน": ("เวชศาสตร์.png",),
    "อายุรแพทย์คลินิกผู้สูงอายุ": ("อายุรกรรม 1.png",),
    "อายุรแพทย์มะเร็งวิทยา": ("อายุรกรรม 1.png",),
    "อายุรแพทย์โรคหัวใจ": ("อายุรกรรม 1.png",),
    "ระบบประสาทและสมอง": ("อายุรกรรม 1.png", "อายุรกรรม 2.png"),
    "ออร์โธปิดิคส์บูรณสภาพ": ("กระดูกและข้อ.png",),
    "อายุรกรรม": ("อายุรกรรม 1.png", "อายุรกรรม 2.png"),
    "รังสีวินิจฉัย": ("รังสีวินิจฉัย.png",),
}
SCHEDULE_MASTER_ROW_OVERRIDES: dict[str, list[ScheduleMasterRow]] = {
    "จักษุแพทย์ (ตา)": [
        ScheduleMasterRow(day_text="วันอังคาร", time_text="08.00-12.00 น.", doctor_name="แพทย์หญิงชญานี วิวัฒนเศรษฐ์", subspecialty="จักษุแพทย์", department="ผู้ป่วยนอก 3/OPD 3"),
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงชญานี วิวัฒนเศรษฐ์", subspecialty="จักษุแพทย์", department="ผู้ป่วยนอก 3/OPD 3"),
        ScheduleMasterRow(day_text="วันจันทร์", time_text="08.00-16.00 น.", doctor_name="นายแพทย์ดนัยภัทร วงษ์วรศรีโรจน์", subspecialty="จักษุแพทย์", department="ผู้ป่วยนอก 3/OPD 3"),
        ScheduleMasterRow(day_text="วันพุธ", time_text="08.00-12.00 น.", doctor_name="นายแพทย์ดนัยภัทร วงษ์วรศรีโรจน์", subspecialty="จักษุแพทย์", department="ผู้ป่วยนอก 3/OPD 3"),
    ],
    "กุมารแพทย์": [
        ScheduleMasterRow(day_text="วันจันทร์", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงเพ็ญพรรณ กันฑะษา", subspecialty="กุมารแพทย์", department="ผู้ป่วยนอก 3/OPD 3"),
        ScheduleMasterRow(day_text="วันอังคาร", time_text="13.00-16.00 น.", doctor_name="แพทย์หญิงเพ็ญพรรณ กันฑะษา", subspecialty="กุมารแพทย์", department="ผู้ป่วยนอก 3/OPD 3"),
        ScheduleMasterRow(day_text="วันอังคาร", time_text="08.00-12.00 น.", doctor_name="นายแพทย์สรกิจ ภาคีชีพ", subspecialty="กุมารแพทย์", department="ผู้ป่วยนอก 3/OPD 3"),
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="08.00-12.00 น.", doctor_name="นายแพทย์สรกิจ ภาคีชีพ", subspecialty="กุมารแพทย์", department="ผู้ป่วยนอก 3/OPD 3"),
        ScheduleMasterRow(day_text="วันศุกร์", time_text="08.00-12.00 น.", doctor_name="แพทย์หญิงเพ็ญพรรณ กันฑะษา", subspecialty="กุมารแพทย์", department="ผู้ป่วยนอก 3/OPD 3"),
    ],
    "กุมารแพทย์ โรคหัวใจ": [
        ScheduleMasterRow(day_text="วันอังคาร", time_text="13.00-16.00 น.", doctor_name="แพทย์หญิงสรัสวดี เถลิงศก", subspecialty="กุมารแพทย์ โรคหัวใจ", department="ผู้ป่วยนอก 3/OPD 3"),
        ScheduleMasterRow(day_text="วันพุธ", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงสรัสวดี เถลิงศก", subspecialty="กุมารแพทย์ โรคหัวใจ", department="ผู้ป่วยนอก 3/OPD 3"),
        ScheduleMasterRow(day_text="วันศุกร์", time_text="08.00-12.00 น.", doctor_name="แพทย์หญิงสรัสวดี เถลิงศก", subspecialty="กุมารแพทย์ โรคหัวใจ", department="ผู้ป่วยนอก 3/OPD 3"),
    ],
    "ผิวหนัง": [
        ScheduleMasterRow(day_text="วันจันทร์", time_text="09.00-16.00 น.", doctor_name="แพทย์หญิงภัทรภร กุมภวิจิตร", subspecialty="แพทย์โรคผิวหนัง ตจวิทยา", department="ผู้ป่วยนอก 2/OPD 2"),
        ScheduleMasterRow(day_text="วันพุธ", time_text="09.00-16.00 น.", doctor_name="แพทย์หญิงภัทรภร กุมภวิจิตร", subspecialty="แพทย์โรคผิวหนัง ตจวิทยา", department="ผู้ป่วยนอก 2/OPD 2"),
        ScheduleMasterRow(day_text="วันศุกร์", time_text="09.00-12.00 น.", doctor_name="แพทย์หญิงภัทรภร กุมภวิจิตร", subspecialty="แพทย์โรคผิวหนัง ตจวิทยา", department="ผู้ป่วยนอก 2/OPD 2"),
        ScheduleMasterRow(day_text="วันอังคาร", time_text="09.00-16.00 น.", doctor_name="นายแพทย์วสุชล ชัยชาญ", subspecialty="อายุรแพทย์โรคผิวหนัง", department="ผู้ป่วยนอก 2/OPD 2"),
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="09.00-16.00 น.", doctor_name="นายแพทย์วสุชล ชัยชาญ", subspecialty="อายุรแพทย์โรคผิวหนัง", department="ผู้ป่วยนอก 2/OPD 2"),
        ScheduleMasterRow(day_text="วันศุกร์", time_text="09.00-12.00 น.", doctor_name="นายแพทย์วสุชล ชัยชาญ", subspecialty="อายุรแพทย์โรคผิวหนัง", department="ผู้ป่วยนอก 2/OPD 2"),
    ],
    "อายุรกรรม": [
        ScheduleMasterRow(day_text="วันศุกร์", time_text="08.00-16.00 น.", doctor_name="นายแพทย์ภาษา สุขสอน", subspecialty="อายุรแพทย์คลินิกผู้สูงอายุ", department="ผู้ป่วยนอก 2/OPD 2"),
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="08.00-12.00 น.", doctor_name="แพทย์หญิงมัลลิกา ขวัญเมือง", subspecialty="อายุรแพทย์มะเร็งวิทยา", department="ผู้ป่วยนอก 2/OPD 2"),
        ScheduleMasterRow(day_text="วันพุธ", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงกานต์ธิรา กิตติสีแสง", subspecialty="อายุรแพทย์โรคระบบทางเดินอาหาร"),
        ScheduleMasterRow(day_text="วันศุกร์", time_text="08.00-12.00 น.", doctor_name="แพทย์หญิงกานต์ธิรา กิตติสีแสง", subspecialty="อายุรแพทย์โรคระบบทางเดินอาหาร"),
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="08.00-16.00 น.", doctor_name="นายแพทย์พงศธร ทั้งสุข", subspecialty="อายุรแพทย์โรคหัวใจ", department="ผู้ป่วยนอก 4/OPD 4"),
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="08.00-16.00 น.", doctor_name="นายแพทย์วัชเรสร พันธ์พัฒนกุล", subspecialty="อายุรแพทย์ระบบประสาทและสมอง", department="ผู้ป่วยนอก 4/OPD 4"),
        ScheduleMasterRow(day_text="วันศุกร์", time_text="08.00-16.00 น.", doctor_name="นายแพทย์วัชเรสร พันธ์พัฒนกุล", subspecialty="อายุรแพทย์ระบบประสาทและสมอง", department="ผู้ป่วยนอก 4/OPD 4"),
        ScheduleMasterRow(day_text="วันจันทร์", time_text="08.00-16.00 น.", doctor_name="นายแพทย์คามิน สุทธิกุลบุตร", subspecialty="อายุรแพทย์ทั่วไป", department="ผู้ป่วยนอก 1/OPD 1"),
        ScheduleMasterRow(day_text="วันพุธ", time_text="08.00-12.00 น.", doctor_name="นายแพทย์คามิน สุทธิกุลบุตร", subspecialty="อายุรแพทย์ทั่วไป", department="ผู้ป่วยนอก 1/OPD 1"),
        ScheduleMasterRow(day_text="วันอังคาร", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงเพชราภรณ์ ชัชวรัตน์", subspecialty="อายุรแพทย์ทั่วไป", department="ผู้ป่วยนอก 1/OPD 1"),
        ScheduleMasterRow(day_text="วันพุธ", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงเพชราภรณ์ ชัชวรัตน์", subspecialty="อายุรแพทย์ทั่วไป", department="ผู้ป่วยนอก 1/OPD 1"),
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="08.00-16.00 น.", doctor_name="นายแพทย์มนัส โชติเจริญรัตน์", subspecialty="อายุรแพทย์ทั่วไป", department="ผู้ป่วยนอก 1/OPD 1"),
        ScheduleMasterRow(day_text="วันศุกร์", time_text="08.00-16.00 น.", doctor_name="นายแพทย์มนัส โชติเจริญรัตน์", subspecialty="อายุรแพทย์ทั่วไป", department="ผู้ป่วยนอก 1/OPD 1"),
        ScheduleMasterRow(day_text="วันอังคาร", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงจิตราภรณ์ วงษ์เพิก", subspecialty="อายุรแพทย์ระบบประสาทและสมอง", department="ผู้ป่วยนอก 4/OPD 4"),
        ScheduleMasterRow(day_text="วันพุธ", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงจิตราภรณ์ วงษ์เพิก", subspecialty="อายุรแพทย์ระบบประสาทและสมอง", department="ผู้ป่วยนอก 4/OPD 4"),
    ],
    # BUG 2 & 4 FIX: Add entry for สุขภาพจิตชุมชน
    "สุขภาพจิตชุมชน": [
        ScheduleMasterRow(day_text="วันจันทร์-วันศุกร์", time_text="08.00-12.00 น.", doctor_name="นายแพทย์เธียรชัย คฤหโยธิน", subspecialty="สุขภาพจิตชุมชน", department="ผู้ป่วยนอก 1/OPD 1"),
    ],
    "ตรวจสุขภาพ": [
        ScheduleMasterRow(day_text="วันจันทร์และวันอังคาร", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงชนกนันท์ เนติศุภลักษณ์", subspecialty="เวชศาสตร์ป้องกัน (ตรวจสุขภาพ)", department="ผู้ป่วยนอก 2/OPD 2"),
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงอชิรญา ชนะพาล", subspecialty="เวชศาสตร์ป้องกัน (ตรวจสุขภาพ)", department="ผู้ป่วยนอก 2/OPD 2"),
        ScheduleMasterRow(day_text="วันศุกร์", time_text="08.00-12.00 น.", doctor_name="แพทย์หญิงอชิรญา ชนะพาล", subspecialty="เวชศาสตร์ป้องกัน (ตรวจสุขภาพ)", department="ผู้ป่วยนอก 2/OPD 2"),
    ],
    "อายุรแพทย์คลินิกผู้สูงอายุ": [
        ScheduleMasterRow(day_text="วันศุกร์", time_text="08.00-16.00 น.", doctor_name="นายแพทย์ภาษา สุขสอน", subspecialty="อายุรแพทย์คลินิกผู้สูงอายุ", department="ผู้ป่วยนอก 2/OPD 2"),
    ],
    "อายุรแพทย์มะเร็งวิทยา": [
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="08.00-12.00 น.", doctor_name="แพทย์หญิงมัลลิกา ขวัญเมือง", subspecialty="อายุรแพทย์มะเร็งวิทยา", department="ผู้ป่วยนอก 2/OPD 2"),
    ],
    "อายุรแพทย์โรคหัวใจ": [
        ScheduleMasterRow(day_text="วันพฤหัสบดี", time_text="08.00-16.00 น.", doctor_name="นายแพทย์พงศธร ทั้งสุข", subspecialty="อายุรแพทย์โรคหัวใจ", department="ผู้ป่วยนอก 4/OPD 4"),
    ],
    "ระบบประสาทและสมอง": [
        ScheduleMasterRow(day_text="วันอังคาร-วันพุธ", time_text="08.00-16.00 น.", doctor_name="แพทย์หญิงจิตราภรณ์ วงษ์เพิก", subspecialty="อายุรแพทย์ระบบประสาทและสมอง", department="ผู้ป่วยนอก 4/OPD 4"),
        ScheduleMasterRow(day_text="วันพฤหัสบดี-วันศุกร์", time_text="08.00-16.00 น.", doctor_name="นายแพทย์วัชเรสร พันธ์พัฒนกุล", subspecialty="อายุรแพทย์ระบบประสาทและสมอง", department="ผู้ป่วยนอก 4/OPD 4"),
    ],
    "ออร์โธปิดิคส์บูรณสภาพ": [
        ScheduleMasterRow(day_text="วันอังคาร", time_text="08.00-16.00 น.", doctor_name="นายแพทย์ฐิตินันท์ ธาราทิพยกุล", subspecialty="ออร์โธปิดิคส์บูรณสภาพ", department="ศูนย์ศัลยกรรมกระดูและข้อ"),
    ],
}


def _schedule_time_parts(text: str) -> tuple[str, str]:
    value = str(text or "").strip()
    match = re.search(r"(\d{1,2}[.:]\d{2}\s*-\s*\d{1,2}[.:]\d{2}\s*น\.)", value)
    if not match:
        return value, ""
    time_text = match.group(1).replace(" - ", "-").replace(" -", "-").replace("- ", "-").strip()
    day_text = value[:match.start()].strip()
    return day_text, time_text


def _parse_schedule_master_rows(answer: str, *, specialty: str = "", department: str = "") -> tuple[list[ScheduleMasterRow], bool]:
    rows: list[ScheduleMasterRow] = []
    has_hidden_rows = False
    for day_text, doctor_name in _schedule_row_entries_from_text(answer):
        clean_doctor = str(doctor_name or "").strip()
        if clean_doctor == "ยังไม่ระบุชื่อแพทย์ในข้อมูล":
            clean_doctor = ""
        left_day, time_text = _schedule_time_parts(day_text)
        rows.append(ScheduleMasterRow(
            day_text=left_day or day_text,
            time_text=time_text,
            doctor_name=clean_doctor,
            subspecialty=specialty,
            department=department,
        ))
        if not clean_doctor:
            has_hidden_rows = True
    return rows, has_hidden_rows


def _is_useful_schedule_alias(alias: str) -> bool:
    value = str(alias or "").strip()
    compact = _compact_normalize(value)
    if not value or len(compact) < 2:
        return False
    if value.lower() in SCHEDULE_GENERIC_ALIASES or compact in {_compact_normalize(item) for item in SCHEDULE_GENERIC_ALIASES}:
        return False
    return True


def _doctor_title_parts(doctor_name: str) -> tuple[str, str]:
    doctor = str(doctor_name or "").strip()
    for title in ("นายแพทย์", "แพทย์หญิง", "นพ.", "พญ."):
        if doctor.startswith(title):
            return title, doctor[len(title):].strip()
    return "", doctor


def _doctor_alias_seed(doctor_name: str) -> set[str]:
    doctor = str(doctor_name or "").strip()
    if not doctor:
        return set()
    title, stripped = _doctor_title_parts(doctor)
    aliases = {doctor, doctor.replace(" ", "")}
    if stripped:
        aliases.update({stripped, stripped.replace(" ", "")})
        parts = stripped.split()
        if parts:
            first_name = parts[0]
            aliases.add(first_name)
            aliases.add(f"หมอ{first_name}")
            if title:
                aliases.add(f"{title}{first_name}")
                aliases.add(f"{title} {first_name}")
        if len(parts) >= 2:
            aliases.add(parts[-1])
    return {alias.strip() for alias in aliases if alias and alias.strip()}


def _schedule_master_exact_alias_map() -> dict[str, ScheduleMasterEntry]:
    alias_map: dict[str, ScheduleMasterEntry] = {}
    for entry in _schedule_master_entries().values():
        for alias in [entry.specialty, *entry.aliases]:
            compact_alias = _compact_normalize(alias)
            if not compact_alias:
                continue
            current = alias_map.get(compact_alias)
            if current is None or len(entry.specialty) > len(current.specialty):
                alias_map[compact_alias] = entry
    return alias_map


def _schedule_master_entries() -> dict[str, ScheduleMasterEntry]:
    entries: dict[str, ScheduleMasterEntry] = {}
    for row in _schedule_rows():
        topic = _record_to_candidate(row, 0.95, source="schedule")
        raw_specialty = str((topic.metadata or {}).get("topic") or topic.question or "").strip()
        canonical_specialty = SCHEDULE_SOURCE_TO_CANONICAL.get(raw_specialty, raw_specialty)
        department = str((topic.metadata or {}).get("clinic") or topic.department or "").strip()
        entry = entries.setdefault(canonical_specialty, ScheduleMasterEntry(
            specialty=canonical_specialty,
            department=department,
            source_id=topic.id,
        ))
        if not entry.department and department:
            entry.department = department
        if entry.source_id is None:
            entry.source_id = topic.id
        alias_values = {
            canonical_specialty,
            raw_specialty,
            str(topic.question or "").strip(),
            str((topic.metadata or {}).get("specialty") or "").strip(),
        }
        alias_values.update(_parse_list_field((topic.metadata or {}).get("aliases")))
        alias_values.update(SCHEDULE_CANONICAL_ALIASES.get(canonical_specialty, []))
        if canonical_specialty == "กุมารแพทย์ โรคหัวใจ":
            alias_values.difference_update({"กุมารแพทย์", "กุมาร", "เด็ก", "หมอเด็ก", "โรคหัวใจ"})
        elif canonical_specialty == "อายุรแพทย์โรคหัวใจ":
            alias_values.difference_update({"โรคหัวใจ"})
        for alias in alias_values:
            if _is_useful_schedule_alias(alias):
                entry.aliases.append(str(alias).strip())
        rows, hidden_rows = _parse_schedule_master_rows(topic.answer, specialty=raw_specialty or canonical_specialty, department=department)
        entry.rows.extend(rows)
        entry.has_hidden_rows = entry.has_hidden_rows or hidden_rows
        image_names = [Path(path).name for path in _parse_list_field((topic.metadata or {}).get("followup_image_paths"))]
        if canonical_specialty in SCHEDULE_CANONICAL_IMAGE_MAP:
            image_names.extend(SCHEDULE_CANONICAL_IMAGE_MAP[canonical_specialty])
        for image_name in image_names:
            if image_name and image_name not in entry.image_filenames:
                entry.image_filenames.append(image_name)

    for specialty, override_rows in SCHEDULE_MASTER_ROW_OVERRIDES.items():
        entry = entries.setdefault(specialty, ScheduleMasterEntry(specialty=specialty))
        entry.rows = list(override_rows)
        entry.has_hidden_rows = False
        entry.aliases.extend(SCHEDULE_CANONICAL_ALIASES.get(specialty, []))
        entry.aliases.append(specialty)
        for row in override_rows:
            if row.department and not entry.department:
                entry.department = row.department
        for image_name in SCHEDULE_CANONICAL_IMAGE_MAP.get(specialty, ()):
            if image_name not in entry.image_filenames:
                entry.image_filenames.append(image_name)

    for entry in entries.values():
        entry.aliases = list(dict.fromkeys([alias for alias in entry.aliases if _is_useful_schedule_alias(alias)]))
        deduped_rows: list[ScheduleMasterRow] = []
        seen_rows: set[tuple[str, str, str, str, str]] = set()
        for row in entry.rows:
            key = (row.day_text, row.time_text, row.doctor_name, row.subspecialty, row.department)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            deduped_rows.append(row)
        entry.rows = deduped_rows
        entry.image_filenames = list(dict.fromkeys(entry.image_filenames))
    return entries


def _schedule_master_doctor_aliases() -> dict[str, set[str]]:
    entries = _schedule_master_entries()
    doctor_aliases: dict[str, set[str]] = {}
    first_name_prefix_counts: dict[str, int] = {}
    surname_prefix_counts: dict[str, int] = {}
    doctor_parts: dict[str, tuple[str, str, str]] = {}

    for entry in entries.values():
        for row in entry.rows:
            doctor = str(row.doctor_name or "").strip()
            if not doctor:
                continue
            doctor_aliases.setdefault(doctor, set()).update(_doctor_alias_seed(doctor))
            title, stripped = _doctor_title_parts(doctor)
            parts = stripped.split()
            first_name = parts[0] if parts else ""
            surname = parts[-1] if len(parts) >= 2 else ""
            doctor_parts[doctor] = (title, first_name, surname)
            for token, counter in ((first_name, first_name_prefix_counts), (surname, surname_prefix_counts)):
                compact = _compact_normalize(token)
                for length in range(3, min(len(compact), 5) + 1):
                    prefix = compact[:length]
                    counter[prefix] = counter.get(prefix, 0) + 1

    for doctor, aliases in doctor_aliases.items():
        title, first_name, surname = doctor_parts.get(doctor, ("", "", ""))
        for token, counter in ((first_name, first_name_prefix_counts), (surname, surname_prefix_counts)):
            compact_token = _compact_normalize(token)
            for length in range(3, min(len(compact_token), 5) + 1):
                compact_prefix = compact_token[:length]
                if counter.get(compact_prefix, 0) != 1:
                    continue
                prefix = token[:length]
                aliases.add(prefix)
                if token == first_name:
                    aliases.add(f"หมอ{prefix}")
                    if title:
                        aliases.add(f"{title}{prefix}")
                        aliases.add(f"{title} {prefix}")
        doctor_aliases[doctor] = {alias.strip() for alias in aliases if alias and alias.strip()}
    return doctor_aliases


def _schedule_entry_score(query: str, entry: ScheduleMasterEntry) -> float:
    qc = _compact_normalize(query)
    if not qc:
        return 0.0
    # BUG 3 FIX: Reject generic words from matching via substring
    # Note: "อายุรกรรม" and "ผู้สูงอายุ" are valid specialty names and should match
    generic_words = {
        "สุขภาพ", "จิต", "ชุมชน", "ตรวจสุขภาพ",
        "คลินิก", "แพทย์", "หมอ", "นพ", "พญ",
        "โรงพยาบาล", "แผนก", "บริการ", "ตรวจ", "รักษา",
    }
    if qc in generic_words or len(qc) <= 2:
        return 0.0
    best = 0.0
    for alias in [entry.specialty, *entry.aliases]:
        alias_compact = _compact_normalize(alias)
        if not alias_compact:
            continue
        if qc == alias_compact:
            best = max(best, 1.0)
        elif alias_compact in qc and len(alias_compact) >= 2:
            # BUG 3 FIX: Only allow substring match if query is long enough
            if len(qc) >= 5:
                best = max(best, 0.97)
        elif qc in alias_compact and len(qc) >= 3:
            # BUG 3 FIX: Only allow substring match if query is long enough
            if len(qc) >= 4:
                best = max(best, 0.94)
    return best


def _find_schedule_master_entry(query: str) -> ScheduleMasterEntry | None:
    best_entry: ScheduleMasterEntry | None = None
    best_score = 0.0
    for entry in _schedule_master_entries().values():
        score = _schedule_entry_score(query, entry)
        if score > best_score:
            best_entry = entry
            best_score = score
    return best_entry if best_score >= 0.94 else None


def _schedule_master_exact_alias_map() -> dict[str, ScheduleMasterEntry]:
    alias_map: dict[str, ScheduleMasterEntry] = {}
    for entry in _schedule_master_entries().values():
        for alias in [entry.specialty, *entry.aliases]:
            compact_alias = _compact_normalize(alias)
            if not compact_alias:
                continue
            current = alias_map.get(compact_alias)
            if current is None or len(entry.specialty) > len(current.specialty):
                alias_map[compact_alias] = entry
    return alias_map


def _schedule_entry_score(query: str, entry: ScheduleMasterEntry) -> float:
    qc = _compact_normalize(query)
    if not qc:
        return 0.0
    generic_words = {
        "สุขภาพ", "จิต", "ชุมชน", "คลินิก", "แพทย์", "หมอ", "นพ", "พญ",
        "โรงพยาบาล", "แผนก", "บริการ", "ตรวจ", "รักษา",
    }
    if qc in generic_words or len(qc) <= 2:
        return 0.0
    best = 0.0
    for alias in [entry.specialty, *entry.aliases]:
        alias_compact = _compact_normalize(alias)
        if not alias_compact:
            continue
        if qc == alias_compact:
            best = max(best, 1.0)
        elif alias_compact in qc and len(alias_compact) >= 2:
            if len(qc) >= 5:
                best = max(best, 0.97)
        elif qc in alias_compact and len(qc) >= 3:
            if len(qc) >= 4:
                best = max(best, 0.94)
    return best


def _find_schedule_master_entry(query: str) -> ScheduleMasterEntry | None:
    qc = _compact_normalize(query)
    if not qc:
        return None

    exact_entry = _schedule_master_exact_alias_map().get(qc)
    if exact_entry is not None:
        return exact_entry

    best_entry: ScheduleMasterEntry | None = None
    best_score = 0.0
    for entry in _schedule_master_entries().values():
        score = _schedule_entry_score(query, entry)
        if score > best_score:
            best_entry = entry
            best_score = score
    return best_entry if best_score >= 0.94 else None


def _build_schedule_master_attachments(entry: ScheduleMasterEntry) -> list[Attachment]:
    attachments: list[Attachment] = []
    total_images = len(entry.image_filenames)
    for image_name in entry.image_filenames:
        if not image_name:
            continue
        label = f"รูปตารางแพทย์ {entry.specialty}"
        if total_images > 1:
            label = f"รูปตารางแพทย์ {entry.specialty} {Path(image_name).stem}"
        attachments.append(Attachment(
            type="image",
            label=label,
            url=f"/assets/schedule/{image_name}",
            filename=image_name,
        ))
    return _dedupe_attachments(attachments)


def _format_schedule_master_answer(entry: ScheduleMasterEntry, day_filter: str | None = None) -> str:
    rows = list(entry.rows)
    if day_filter:
        rows = [row for row in rows if day_filter in row.day_text]
        if not rows:
            return (
                f"ไม่พบตารางออกตรวจของ {entry.specialty} ในวัน{day_filter} ในระบบปัจจุบัน\n"
                "กรุณาดูรูปตารางประกอบหรือเลือกสาขาอื่นได้เลยค่ะ"
            )

    body_lines: list[str] = []
    hidden_rows = False
    for row in rows:
        if not row.doctor_name:
            hidden_rows = True
            continue
        slot_text = f"{row.day_text} {row.time_text}".strip()
        detail_parts: list[str] = []
        if row.subspecialty and row.subspecialty not in {entry.specialty, "จักษุแพทย์", "อายุรแพทย์ทั่วไป"}:
            detail_parts.append(row.subspecialty)
        if row.department and entry.specialty == "อายุรกรรม":
            detail_parts.append(row.department)
        suffix = f" ({', '.join(dict.fromkeys(detail_parts))})" if detail_parts else ""
        body_lines.append(f"- {slot_text} : {row.doctor_name}{suffix}")

    if hidden_rows or entry.has_hidden_rows:
        body_lines.append(SCHEDULE_UNNAMED_PUBLIC_NOTICE)

    header = entry.specialty
    if entry.department and entry.specialty not in {"อายุรกรรม", "ทั่วไป"}:
        header = f"{entry.specialty} ({entry.department})"
    return clean_user_visible_answer("\n".join([header, *body_lines]))


def _format_schedule_master_answer(entry: ScheduleMasterEntry, day_filter: str | None = None) -> str:
    rows = list(entry.rows)
    if day_filter:
        rows = [row for row in rows if day_filter in row.day_text]
        if not rows:
            return (
                f"ไม่พบตารางออกตรวจของ {entry.specialty} ในวัน{day_filter} ในระบบปัจจุบัน\n"
                "กรุณาดูรูปตารางประกอบหรือเลือกสาขาอื่นได้เลยค่ะ"
            )

    body_lines: list[str] = []
    hidden_rows = False
    detail_entries = {"อายุรแพทย์คลินิกผู้สูงอายุ", "อายุรแพทย์มะเร็งวิทยา", "ระบบประสาทและสมอง"}
    for row in rows:
        if not row.doctor_name:
            hidden_rows = True
            continue
        slot_text = f"{row.day_text} {row.time_text}".strip()
        detail_parts: list[str] = []
        if row.subspecialty and (entry.specialty in detail_entries or row.subspecialty not in {entry.specialty, "จักษุแพทย์", "อายุรแพทย์ทั่วไป"}):
            detail_parts.append(row.subspecialty)
        if row.department and entry.specialty in {"อายุรกรรม", *detail_entries}:
            detail_parts.append(row.department)
        suffix = f" ({', '.join(dict.fromkeys(detail_parts))})" if detail_parts else ""
        body_lines.append(f"- {slot_text} : {row.doctor_name}{suffix}")

    if hidden_rows or entry.has_hidden_rows:
        body_lines.append(SCHEDULE_UNNAMED_PUBLIC_NOTICE)

    if entry.specialty == "สุขภาพจิตชุมชน" and rows and len(body_lines) == 1:
        row = rows[0]
        return clean_user_visible_answer(
            "\n".join([
                f"{row.doctor_name} ออกตรวจเฉพาะทางสุขภาพจิตชุมชน ที่{row.department}",
                f"- {row.day_text} {row.time_text}".strip(),
            ])
        )

    header = entry.specialty
    if entry.department and entry.specialty not in {"อายุรกรรม", "ทั่วไป", "สุขภาพจิตชุมชน", "อายุรแพทย์คลินิกผู้สูงอายุ", "อายุรแพทย์มะเร็งวิทยา", "ระบบประสาทและสมอง"}:
        header = f"{entry.specialty} ({entry.department})"
    return clean_user_visible_answer("\n".join([header, *body_lines]))


def _format_schedule_master_answer(entry: ScheduleMasterEntry, day_filter: str | None = None) -> str:
    rows = list(entry.rows)
    if day_filter:
        rows = [row for row in rows if day_filter in row.day_text]
        if not rows:
            return (
                f"ไม่พบตารางออกตรวจของ {entry.specialty} ในวัน{day_filter} ในระบบปัจจุบัน\n"
                "กรุณาดูรูปตารางประกอบหรือเลือกสาขาอื่นได้เลยค่ะ"
            )

    body_lines: list[str] = []
    hidden_rows = False
    detail_entries = {
        "อายุรแพทย์คลินิกผู้สูงอายุ",
        "อายุรแพทย์มะเร็งวิทยา",
        "ระบบประสาทและสมอง",
        "อายุรแพทย์โรคหัวใจ",
    }
    for row in rows:
        if not row.doctor_name:
            hidden_rows = True
            continue
        slot_text = f"{row.day_text} {row.time_text}".strip()
        detail_parts: list[str] = []
        if row.subspecialty and (entry.specialty in detail_entries or row.subspecialty not in {entry.specialty, "จักษุแพทย์", "อายุรแพทย์ทั่วไป"}):
            detail_parts.append(row.subspecialty)
        if row.department and entry.specialty in {"อายุรกรรม", *detail_entries}:
            detail_parts.append(row.department)
        suffix = f" ({', '.join(dict.fromkeys(detail_parts))})" if detail_parts else ""
        body_lines.append(f"- {slot_text} : {row.doctor_name}{suffix}")

    if hidden_rows or entry.has_hidden_rows:
        body_lines.append(SCHEDULE_UNNAMED_PUBLIC_NOTICE)

    if entry.specialty == "สุขภาพจิตชุมชน" and rows and len(body_lines) == 1:
        row = rows[0]
        return clean_user_visible_answer(
            "\n".join([
                f"{row.doctor_name} ออกตรวจเฉพาะทางสุขภาพจิตชุมชน ที่{row.department}",
                f"- {row.day_text} {row.time_text}".strip(),
            ])
        )

    header = entry.specialty
    if entry.department and entry.specialty not in {
        "อายุรกรรม",
        "ทั่วไป",
        "สุขภาพจิตชุมชน",
        "อายุรแพทย์คลินิกผู้สูงอายุ",
        "อายุรแพทย์มะเร็งวิทยา",
        "ระบบประสาทและสมอง",
        "อายุรแพทย์โรคหัวใจ",
    }:
        header = f"{entry.specialty} ({entry.department})"
    return clean_user_visible_answer("\n".join([header, *body_lines]))


def _match_schedule_master_doctor(query: str) -> dict[str, Any] | None:
    qc = _compact_normalize(query)
    if not qc:
        return None

    # BUG 3 FIX: Add stricter matching rules to prevent generic words from matching doctor names
    # Generic words that should NOT match doctor names
    # Note: "อายุรกรรม" and "ผู้สูงอายุ" are valid specialty names and should match
    generic_words = {
        "สุขภาพ", "จิต", "ชุมชน", "ตรวจสุขภาพ",
        "คลินิก", "แพทย์", "หมอ", "นพ", "พญ",
        "โรงพยาบาล", "แผนก", "บริการ", "ตรวจ", "รักษา",
    }
    if qc in generic_words or len(qc) <= 2:
        logger.info("🚫 Doctor match rejected: generic word or too short (query='%s')", query[:40])
        return None

    # Check if query has explicit doctor intent markers
    doctor_intent_markers = {"หมอ", "แพทย์", "นพ", "พญ", "นายแพทย์", "แพทย์หญิง"}
    has_explicit_doctor_intent = any(marker in query for marker in doctor_intent_markers)

    doctor_aliases = _schedule_master_doctor_aliases()
    matches: list[tuple[str, float]] = []
    for doctor_name, aliases in doctor_aliases.items():
        best_score = 0.0
        for alias in aliases:
            alias_compact = _compact_normalize(alias)
            if len(alias_compact) < 3:
                continue
            # BUG 3 FIX: Stricter scoring - require higher confidence for partial matches
            if qc == alias_compact:
                best_score = max(best_score, 1.0)
            elif alias_compact in qc and len(alias_compact) >= 4:
                # Only allow partial match if query is long enough or has explicit doctor intent
                if len(qc) >= 6 or has_explicit_doctor_intent:
                    best_score = max(best_score, 0.97)
            elif qc in alias_compact and len(qc) >= 4:
                # Only allow if query is reasonably long
                if len(qc) >= 5 or has_explicit_doctor_intent:
                    best_score = max(best_score, 0.94)
        if best_score:
            matches.append((doctor_name, best_score))

    if not matches:
        logger.info("🚫 Doctor match failed: no matches found (query='%s')", query[:40])
        return None

    matches.sort(key=lambda item: (-item[1], item[0]))
    top_score = matches[0][1]
    # BUG 3 FIX: Require higher confidence threshold to avoid false positives
    if top_score < 0.94:
        logger.info("🚫 Doctor match rejected: score too low %.2f (query='%s')", top_score, query[:40])
        return None
    top_doctors = [doctor for doctor, score in matches if score >= top_score - 0.01]
    if len(top_doctors) > 1:
        logger.info("⚠️  Doctor match ambiguous: %d doctors (query='%s')", len(top_doctors), query[:40])
        return {"ambiguous_doctors": top_doctors[:6]}

    doctor_name = top_doctors[0]
    doctor_rows: list[dict[str, Any]] = []
    for entry in _schedule_master_entries().values():
        for row in entry.rows:
            if str(row.doctor_name or "").strip() == doctor_name:
                doctor_rows.append({"entry": entry, "row": row})
    logger.info("✅ Doctor match found: %s with %d rows (query='%s')", doctor_name, len(doctor_rows), query[:40])
    return {"doctor": doctor_name, "rows": doctor_rows}


def _format_schedule_master_doctor_answer(match: dict[str, Any]) -> str:
    doctor_name = str(match.get("doctor") or "").strip()
    rows = list(match.get("rows") or [])
    if not doctor_name or not rows:
        return ""

    grouped: dict[str, list[ScheduleMasterRow]] = {}
    specialty_meta: dict[str, tuple[str, str]] = {}
    for item in rows:
        entry: ScheduleMasterEntry = item["entry"]
        row: ScheduleMasterRow = item["row"]
        specialty_label = row.subspecialty or entry.specialty
        grouped.setdefault(specialty_label, []).append(row)
        specialty_meta.setdefault(specialty_label, (entry.specialty, row.department or entry.department))

    lines: list[str] = []
    if len(grouped) == 1:
        specialty_label = next(iter(grouped))
        root_specialty, department = specialty_meta[specialty_label]
        heading = f"{doctor_name} ออกตรวจเฉพาะทาง{specialty_label}"
        if department:
            heading += f" ที่{department}"
        if root_specialty != specialty_label and root_specialty:
            heading += f" ในหมวด{root_specialty}"
        lines.append(heading)
        for row in grouped[specialty_label]:
            lines.append(f"- {row.day_text} {row.time_text}".strip())
    else:
        lines.append(f"{doctor_name} มีตารางออกตรวจดังนี้")
        for specialty_label, specialty_rows in grouped.items():
            root_specialty, department = specialty_meta[specialty_label]
            header = specialty_label
            if department:
                header += f" ที่{department}"
            if root_specialty and root_specialty != specialty_label:
                header += f" ({root_specialty})"
            lines.append(header)
            for row in specialty_rows:
                lines.append(f"- {row.day_text} {row.time_text}".strip())
    return clean_user_visible_answer("\n".join(lines))


def _schedule_master_attachments_for_doctor(match: dict[str, Any]) -> list[Attachment]:
    attachments: list[Attachment] = []
    seen_specialties: set[str] = set()
    for item in match.get("rows", []):
        entry: ScheduleMasterEntry = item["entry"]
        if entry.specialty in seen_specialties:
            continue
        seen_specialties.add(entry.specialty)
        attachments.extend(_build_schedule_master_attachments(entry))
    return _dedupe_attachments(attachments)


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
    meaningful = _meaningful_tokens(query)
    if not compact:
        return True
    if compact in TYPO_CANONICAL_MAP or query in TYPO_CANONICAL_MAP:
        return False
    if len(compact) >= 8 and len(meaningful) >= 2:
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
    if category_hint and _row_matches_category_scope(row, category_hint):
        score += 0.03
    return min(1.0, round(score, 6))


def _catalog_search(query: str, *, category: str | None = None, limit: int = 8) -> list[RetrievalCandidate]:
    rows = _rows_for_category_scope(category) if category else state.records
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


def _category_browse_candidates(category: str, limit: int = 8) -> list[RetrievalCandidate]:
    rows = _rows_for_category_scope(category)
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
    if best_candidate and best_candidate.final_score >= 0.95:
        return False
    q = _normalize(query)
    if category_hint == "วัคซีน" and q == "วัคซีน":
        return True
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


def _looks_like_specific_unknown_query(query: str, best_candidate: RetrievalCandidate | None = None) -> bool:
    if best_candidate is not None and best_candidate.final_score >= 0.35:
        return False
    compact = _compact_normalize(query)
    if len(compact) < 10:
        return False
    if _is_schedule_query(query):
        return False
    consonants_only = re.sub(r"[ะาำิีึืุูเแโใไั็ง่้๊๋์0-9]", "", compact)
    if len(compact) >= 4 and len(consonants_only) == len(compact):
        return False
    return True


def _is_follow_up_query(query: str) -> bool:
    if _is_schedule_query(query):
        return False
    q = _normalize(query)
    generic_phrases = {"ราคาเท่าไหร่", "เท่าไหร่", "ติดต่อที่ไหน", "เปิดวันไหน", "เปิดกี่โมง", "เข้าได้เลยไหม", "มีไหม", "มีรูปไหม", "มีภาพไหม", "ขอดูรูป", "มีไฟล์ไหม", "มีลิงก์ไหม"}
    if q in generic_phrases:
        return True
    return len(q) <= 18 and bool(FOLLOW_UP_RE.search(q))


def _remember(session: SessionMemory, *, category: str | None, topic: RetrievalCandidate | None = None, buttons: list[str] | None = None) -> None:
    if category:
        session.last_category = category
    if topic is not None:
        session.last_topic_id = topic.id
        session.last_topic_question = topic.question
        session.last_category = _canonical_category_for_candidate(topic, topic.question) or topic.category
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


def _image_path_to_url(path: str) -> str:
    """Convert a local Windows image path to a public /assets/... URL."""
    p = str(path or "").strip()
    if not p:
        return ""
    # Already a URL
    if p.startswith("/assets/") or p.startswith("http"):
        return p
    path_obj = Path(p)
    filename = path_obj.name
    # Determine asset root by checking which root directory is a parent
    if SCHEDULE_IMAGE_DIR.exists():
        try:
            path_obj.relative_to(SCHEDULE_IMAGE_DIR)
            return f"/assets/schedule/{filename}"
        except ValueError:
            pass
    if HEALTH_CHECK_IMAGE_DIR.exists():
        try:
            path_obj.relative_to(HEALTH_CHECK_IMAGE_DIR)
            return f"/assets/health-check/{filename}"
        except ValueError:
            pass
    # Fallback: guess by folder name in path
    if "ตารางออกตรวจแพทย์" in p or "ตารางออกตรวจ" in p:
        return f"/assets/schedule/{filename}"
    if "ตรวจสุขภาพ" in p:
        return f"/assets/health-check/{filename}"
    return ""


def _topic_follow_up_buttons(topic: RetrievalCandidate) -> list[str]:
    """Return category-aware quick-reply buttons for a topic."""
    raw_category = str(topic.category or "").strip()
    canonical_cat = _canonical_category_for_candidate(topic, topic.question) or raw_category
    parent_theme = CATEGORY_TO_MAIN_THEME.get(canonical_cat, CATEGORY_TO_MAIN_THEME.get(raw_category, ""))

    # Determine which slots are relevant
    is_schedule = canonical_cat in {"\u0e15\u0e32\u0e23\u0e32\u0e07\u0e41\u0e1e\u0e17\u0e22\u0e4c\u0e41\u0e25\u0e30\u0e40\u0e27\u0e25\u0e32\u0e17\u0e33\u0e01\u0e32\u0e23"} or raw_category in {"\u0e19\u0e31\u0e14\u0e2b\u0e21\u0e32\u0e22\u0e41\u0e25\u0e30\u0e15\u0e32\u0e23\u0e32\u0e07\u0e41\u0e1e\u0e17\u0e22\u0e4c"}
    is_job = canonical_cat == "\u0e01\u0e25\u0e38\u0e48\u0e21\u0e07\u0e32\u0e19\u0e1a\u0e38\u0e04\u0e04\u0e25" or raw_category in {"\u0e15\u0e34\u0e14\u0e15\u0e48\u0e2d\u0e2b\u0e19\u0e48\u0e27\u0e22\u0e07\u0e32\u0e19\u0e40\u0e09\u0e1e\u0e32\u0e30\u0e41\u0e25\u0e30\u0e2a\u0e21\u0e31\u0e04\u0e23\u0e07\u0e32\u0e19"}
    is_health_check = canonical_cat in {
        "\u0e15\u0e23\u0e27\u0e08\u0e2a\u0e38\u0e02\u0e20\u0e32\u0e1e\u0e23\u0e32\u0e22\u0e1a\u0e38\u0e04\u0e04\u0e25",
        "\u0e15\u0e23\u0e27\u0e08\u0e2a\u0e38\u0e02\u0e20\u0e32\u0e1e\u0e2d\u0e07\u0e04\u0e4c\u0e01\u0e23\u0e41\u0e25\u0e30\u0e2a\u0e34\u0e17\u0e18\u0e34\u0e40\u0e1a\u0e34\u0e01\u0e08\u0e48\u0e32\u0e22",
        "\u0e15\u0e23\u0e27\u0e08\u0e2a\u0e38\u0e02\u0e20\u0e32\u0e1e\u0e41\u0e25\u0e30\u0e43\u0e1a\u0e23\u0e31\u0e1a\u0e23\u0e2d\u0e07\u0e41\u0e1e\u0e17\u0e22\u0e4c",
        "\u0e01\u0e32\u0e23\u0e02\u0e2d\u0e40\u0e2d\u0e01\u0e2a\u0e32\u0e23\u0e17\u0e32\u0e07\u0e01\u0e32\u0e23\u0e41\u0e1e\u0e17\u0e22\u0e4c",
    }
    is_vaccine = canonical_cat == "\u0e27\u0e31\u0e04\u0e0b\u0e35\u0e19" or canonical_cat == "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e34\u0e01\u0e32\u0e23\u0e27\u0e31\u0e04\u0e0b\u0e35\u0e19\u0e19\u0e31\u0e01\u0e28\u0e36\u0e01\u0e29\u0e32"
    buttons: list[str] = []
    if is_schedule:
        buttons += ["ค้นหาตามเฉพาะทาง", "ดูตารางสาขาอื่น", "เวลาทำการแผนกผู้ป่วยนอก"]
        back_label = f"\u0e01\u0e25\u0e31\u0e1a\u0e44\u0e1b\u0e2b\u0e21\u0e27\u0e14\u0e19\u0e31\u0e14\u0e2b\u0e21\u0e32\u0e22\u0e41\u0e25\u0e30\u0e15\u0e32\u0e23\u0e32\u0e07\u0e41\u0e1e\u0e17\u0e22\u0e4c"
    elif is_job:
        if _slot_value(topic, "contact"):
            buttons.append("ติดต่อที่ไหน")
        back_label = f"\u0e01\u0e25\u0e31\u0e1a\u0e44\u0e1b\u0e2b\u0e21\u0e27\u0e14\u0e15\u0e34\u0e14\u0e15\u0e48\u0e2d\u0e2b\u0e19\u0e48\u0e27\u0e22\u0e07\u0e32\u0e19\u0e40\u0e09\u0e1e\u0e32\u0e30\u0e41\u0e25\u0e30\u0e2a\u0e21\u0e31\u0e04\u0e23\u0e07\u0e32\u0e19"
    elif is_vaccine:
        if _slot_value(topic, "price"):
            buttons.append("ราคาเท่าไหร่")
        if _slot_value(topic, "contact"):
            buttons.append("ติดต่อที่ไหน")
        if _slot_value(topic, "hours"):
            buttons.append("เปิดวันไหน")
        back_label = f"\u0e01\u0e25\u0e31\u0e1a\u0e44\u0e1b\u0e2b\u0e21\u0e27\u0e14\u0e27\u0e31\u0e04\u0e0b\u0e35\u0e19\u0e41\u0e25\u0e30\u0e1a\u0e23\u0e34\u0e01\u0e32\u0e23\u0e1c\u0e39\u0e49\u0e1b\u0e48\u0e27\u0e22\u0e19\u0e2d\u0e01"
    elif is_health_check:
        buttons += ["เวลาตรวจสุขภาพ", "โปรแกรมตรวจสุขภาพ", "ใบรับรองแพทย์"]
        back_label = f"\u0e01\u0e25\u0e31\u0e1a\u0e44\u0e1b\u0e2b\u0e21\u0e27\u0e14\u0e15\u0e23\u0e27\u0e08\u0e2a\u0e38\u0e02\u0e20\u0e32\u0e1e\u0e41\u0e25\u0e30\u0e43\u0e1a\u0e23\u0e31\u0e1a\u0e23\u0e2d\u0e07\u0e41\u0e1e\u0e17\u0e22\u0e4c"
    else:
        if _slot_value(topic, "price"):
            buttons.append("ราคาเท่าไหร่")
        if _slot_value(topic, "contact"):
            buttons.append("ติดต่อที่ไหน")
        if _slot_value(topic, "hours"):
            buttons.append("เปิดวันไหน")
        if _slot_value(topic, "walkin"):
            buttons.append("เข้าได้เลยไหม")
        if parent_theme:
            back_label = f"\u0e01\u0e25\u0e31\u0e1a\u0e44\u0e1b\u0e2b\u0e21\u0e27\u0e14{parent_theme}"
        else:
            category_title = display_category_name(raw_category)
            back_label = f"\u0e01\u0e25\u0e31\u0e1a\u0e44\u0e1b\u0e2b\u0e21\u0e27\u0e14{category_title}"
    buttons.append(back_label)
    return list(dict.fromkeys(buttons))


def _category_action_buttons(category: str, candidates: list[RetrievalCandidate]) -> list[str]:
    # Use MAIN_THEME_CHILDREN if category is a main-theme label
    if category in MAIN_THEME_CHILDREN:
        return list(MAIN_THEME_CHILDREN[category])
    if category == "ตรวจสุขภาพรายบุคคล":
        return ["เวลาตรวจสุขภาพ", "โปรแกรมตรวจสุขภาพ", "ใบรับรองแพทย์", "กลับหน้าหลัก"]
    if category == "ตารางแพทย์และเวลาทำการ":
        return ["ตารางแพทย์ออกตรวจ", "เวลาทำการแผนกผู้ป่วยนอก", "กลับไปหมวดนัดหมายและตารางแพทย์"]

    if category == "ตารางแพทย์และเวลาทำการ":
        return ["ตารางแพทย์ออกตรวจ", "เวลาทำการแผนกผู้ป่วยนอก", "กลับหน้าหลัก"]

    # Special case for main theme raw categories that should show child canonical categories
    if category == "\u0e19\u0e31\u0e14\u0e2b\u0e21\u0e32\u0e22\u0e41\u0e25\u0e30\u0e15\u0e32\u0e23\u0e32\u0e07\u0e41\u0e1e\u0e17\u0e22\u0e4c":
        return list(MAIN_THEME_CHILDREN.get("\u0e19\u0e31\u0e14\u0e2b\u0e21\u0e32\u0e22\u0e41\u0e25\u0e30\u0e15\u0e32\u0e23\u0e32\u0e07\u0e41\u0e1e\u0e17\u0e22\u0e4c", ["\u0e01\u0e32\u0e23\u0e08\u0e31\u0e14\u0e01\u0e32\u0e23\u0e19\u0e31\u0e14\u0e2b\u0e21\u0e32\u0e22", "\u0e15\u0e32\u0e23\u0e32\u0e07\u0e41\u0e1e\u0e17\u0e22\u0e4c\u0e41\u0e25\u0e30\u0e40\u0e27\u0e25\u0e32\u0e17\u0e33\u0e01\u0e32\u0e23", "\u0e01\u0e25\u0e31\u0e1a\u0e2b\u0e19\u0e49\u0e32\u0e2b\u0e25\u0e31\u0e01"]))

    child_topics = _unique_category_children(category)
    buttons = list(child_topics[:6]) if child_topics else [c.question for c in candidates[:6] if c.question]
    buttons.append("\u0e01\u0e25\u0e31\u0e1a\u0e2b\u0e19\u0e49\u0e32\u0e2b\u0e25\u0e31\u0e01")
    return list(dict.fromkeys([b for b in buttons if b]))[:8]


def _child_topic_action_buttons(category: str, child_topic: str) -> list[str]:
    """Buttons shown after user selects a child topic."""
    if child_topic == "ตารางแพทย์ออกตรวจ":
        return list(SCHEDULE_DEPARTMENT_MENU)
    rows = _child_topic_leaf_rows(category, child_topic)
    buttons = [str(r.get("question") or "").strip() for r in rows[:8]]
    buttons = [b for b in buttons if b]
    parent_theme = CATEGORY_TO_MAIN_THEME.get(child_topic, CATEGORY_TO_MAIN_THEME.get(category, ""))
    if parent_theme:
        buttons.append(f"\u0e01\u0e25\u0e31\u0e1a\u0e44\u0e1b\u0e2b\u0e21\u0e27\u0e14{parent_theme}")
    else:
        buttons.append(f"\u0e01\u0e25\u0e31\u0e1a\u0e44\u0e1b\u0e2b\u0e21\u0e27\u0e14{display_category_name(category)}")
    return list(dict.fromkeys(buttons))[:8]


def _normalize_schedule_department(query: str) -> str | None:
    q = _compact_normalize(query)
    if not q:
        return None
    for department in SCHEDULE_DEPARTMENT_SPECIALTIES:
        dept_compact = _compact_normalize(department)
        if dept_compact and (q == dept_compact or q in dept_compact or dept_compact in q):
            return department
    return None


def _answer_from_topic_follow_up(query: str, session: SessionMemory) -> RetrievalCandidate | None:
    topic = _find_candidate_by_id(session.last_topic_id)
    if topic is None:
        return None
    if _detect_followup_slot(query):
        return topic
    combined = f"{topic.question} {query}"
    candidates = _catalog_search(combined, category=session.last_category, limit=5)
    if candidates and candidates[0].final_score >= 0.65:
        return candidates[0]
    return topic if _is_follow_up_query(query) else None


GROUNDED_LLM_FALLBACK_TEXT = _official_fallback_answer()


def _candidate_title(candidate: RetrievalCandidate | None) -> str:
    if candidate is None:
        return ""
    return (candidate.question or candidate.subcategory or candidate.category or "").strip()


def _kb_context_blob(candidates: list[RetrievalCandidate]) -> str:
    lines: list[str] = []
    for cand in candidates[:3]:
        lines.append(f"source_id={cand.id}")
        lines.append(f"category={cand.category}")
        lines.append(f"title={_candidate_title(cand)}")
        lines.append(f"answer={cand.answer}")
        if cand.department:
            lines.append(f"department={cand.department}")
        if cand.contact:
            lines.append(f"contact={cand.contact}")
    return "\n".join(lines)


def _extract_structured_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for pattern in (
        r"https?://\S+",
        r"www\.\S+",
        r"\b\d{2,}(?:[-/:]\d+)*\b",
    ):
        tokens.update(re.findall(pattern, text or "", flags=re.IGNORECASE))
    return {token.strip() for token in tokens if token.strip()}


def _grounded_llm_reject_reason(content: str, kb_context: str) -> str | None:
    text = (content or "").strip()
    if not text:
        return "empty_content"
    if text == GROUNDED_LLM_FALLBACK_TEXT:
        return None
    if len(text) > 1200:
        return "too_long"
    lowered = text.lower()
    for marker in ("http://", "https://", "www.", "@line", "facebook"):
        if marker in lowered and marker not in kb_context.lower():
            return "unsupported_url_or_handle"
    kb_tokens = _extract_structured_tokens(kb_context)
    for token in _extract_structured_tokens(text):
        if token not in kb_tokens:
            return f"structured_fact_not_in_kb:{token}"
    for keyword in (
        "วินิจฉัย",
        "รับประทานยา",
        "กินยา",
        "ใช้ยา",
        "รักษาเอง",
        "แนะนำยา",
        "จ่ายยา",
        "ปรับยา",
    ):
        if keyword in text and keyword not in kb_context:
            return f"unsafe_keyword:{keyword}"
    return None


def _log_answer_mode(mode: str, *, top: RetrievalCandidate, model_name: str | None = None, fallback_reason: str | None = None) -> None:
    logger.info(
        "answer_mode=%s source_id=%s category=%s title=%s model=%s fallback_reason=%s",
        mode,
        top.id,
        top.category,
        _candidate_title(top),
        model_name or "-",
        fallback_reason or "-",
    )


def _generate_answer(query: str, top: RetrievalCandidate, candidates: list[RetrievalCandidate], use_llm: bool) -> str:
    """Generate answer using LLM if available; fall back to KB direct answer."""
    model_state = runtime_summary(SERVING_LOCK_PATH)
    t_start = time.time()
    kb_direct_answer = format_direct_answer(top)
    model_name = (
        TYPHOON_MODEL if LLM_PROVIDER == "typhoon"
        else OPENAI_MODEL if LLM_PROVIDER == "openai"
        else model_state.get("runtime_model", "")
    )
    kb_context_candidates = [cand for cand in candidates if cand][:3] or [top]
    kb_context = _kb_context_blob(kb_context_candidates)

    if not use_llm:
        _log_answer_mode("kb_direct", top=top, model_name=model_name, fallback_reason="use_llm_false")
        return kb_direct_answer
    if not RAG_GROUNDED_LLM:
        _log_answer_mode("kb_direct", top=top, model_name=model_name, fallback_reason="grounded_llm_disabled")
        return kb_direct_answer
    if not kb_context.strip():
        _log_answer_mode("kb_direct", top=top, model_name=model_name, fallback_reason="empty_kb_context")
        return kb_direct_answer
    if ANSWER_MODE == "kb_exact" and top:
        _log_answer_mode("kb_direct", top=top, model_name=model_name, fallback_reason="answer_mode_kb_exact")
        return kb_direct_answer

    if use_llm and LLM_PROVIDER in {"typhoon", "openai"}:
        try:
            from openai import OpenAI
            api_key = TYPHOON_API_KEY if LLM_PROVIDER == "typhoon" else OPENAI_API_KEY
            base_url = "https://api.opentyphoon.ai/v1" if LLM_PROVIDER == "typhoon" else None
            model_name = TYPHOON_MODEL if LLM_PROVIDER == "typhoon" else OPENAI_MODEL
            
            if not api_key:
                logger.error("❌ %s API Key missing in environment — using KB fallback", LLM_PROVIDER.upper())
            else:
                client = OpenAI(api_key=api_key, base_url=base_url)
                logger.info("🤖 %s call (mode=%s) → model=%s query='%s'", LLM_PROVIDER.upper(), ANSWER_MODE, model_name, query[:60])
                chat_completion = client.chat.completions.create(
                    messages=build_grounded_llm_messages(query, top, kb_context_candidates),
                    model=model_name,
                    temperature=0.0,
                    max_tokens=512,
                )
                content = chat_completion.choices[0].message.content.strip()
                reject_reason = _grounded_llm_reject_reason(content, kb_context)
                latency = round(time.time() - t_start, 2)
                if content and not reject_reason:
                    logger.info("✅ %s answer returned in %.2fs", LLM_PROVIDER.upper(), latency)
                    _log_answer_mode("llm_grounded_rewrite", top=top, model_name=model_name)
                    return content
                _log_answer_mode("kb_direct", top=top, model_name=model_name, fallback_reason=reject_reason or "empty_content")
        except Exception as exc:
            latency = round(time.time() - t_start, 2)
            logger.error("❌ %s error after %.2fs: %s — using KB fallback", LLM_PROVIDER.upper(), latency, exc)

    if use_llm and (LLM_PROVIDER == "ollama" or model_state.get("configured_provider") == "ollama"):
        model_name = model_state.get("runtime_model", "")
        endpoint = model_state.get("runtime_endpoint", "http://127.0.0.1:11434")
        try:
            payload = {
                "model": model_name,
                "messages": build_grounded_llm_messages(query, top, kb_context_candidates),
                "stream": False,
                "options": {"temperature": 0.0, "num_ctx": 2048},
            }
            logger.info("🤖 LLM call (Ollama, mode=%s) → model=%s endpoint=%s query='%s'", ANSWER_MODE, model_name, endpoint, query[:60])
            response = requests.post(
                f"{endpoint}/api/chat",
                json=payload,
                timeout=OLLAMA_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "").strip()
            reject_reason = _grounded_llm_reject_reason(content, kb_context)
            latency = round(time.time() - t_start, 2)
            if content and not reject_reason:
                logger.info("✅ LLM answer returned in %.2fs", latency)
                _log_answer_mode("llm_grounded_rewrite", top=top, model_name=model_name)
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
    _log_answer_mode("kb_direct", top=top, model_name=model_name, fallback_reason="llm_fallback")
    return kb_direct_answer


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


class Attachment(BaseModel):
    type: Literal["image", "file"] = "image"
    label: str = ""
    url: str = ""
    filename: str = ""


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
    attachments: list[Attachment] = []
    candidates: list[CandidateResponse] = []
    handoff_required: bool = False
    handoff_ticket_id: int | None = None
    admin_reply: str | None = None
    is_fallback_reset: bool = False


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
def _dedupe_attachments(attachments: list[Attachment]) -> list[Attachment]:
    seen: set[tuple[str, str]] = set()
    cleaned: list[Attachment] = []
    for attachment in attachments or []:
        url = str(attachment.url or "").strip()
        if not url or ":\\" in url:
            continue
        key = (str(attachment.type or "image"), url)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(Attachment(
            type=attachment.type or "image",
            label=str(attachment.label or "").strip(),
            url=url,
            filename=str(attachment.filename or "").strip(),
        ))
    return cleaned


def _normalize_response_buttons(response: ChatResponse) -> list[str]:
    if response.reason == "emergency_redirect":
        buttons = [str(button).strip() for button in response.action_buttons if str(button).strip()]
        return list(dict.fromkeys(buttons)) or ["ฉุกเฉิน 1669", "ติดต่อแผนกฉุกเฉิน"]
    if response.route == "fallback":
        return list(FALLBACK_ACTION_BUTTONS)

    selected_category = str(response.selected_category or "").strip()
    source_topic = _find_candidate_by_id(response.source_id) if response.source_id else None
    source_category = _canonical_category_for_candidate(source_topic, source_topic.question if source_topic else "") if source_topic else ""

    if selected_category == "ตารางแพทย์และเวลาทำการ" or source_category == "ตารางแพทย์และเวลาทำการ":
        if response.route == "answer":
            return ["ค้นหาตามเฉพาะทาง", "ดูตารางสาขาอื่น", "เวลาทำการแผนกผู้ป่วยนอก", "กลับไปหมวดนัดหมายและตารางแพทย์"]
    if selected_category in {"ตรวจสุขภาพรายบุคคล", "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย", "ตรวจสุขภาพและใบรับรองแพทย์"} or source_category in {"ตรวจสุขภาพรายบุคคล", "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย"}:
        if response.route == "answer":
            return ["เวลาตรวจสุขภาพ", "โปรแกรมตรวจสุขภาพ", "ใบรับรองแพทย์", "กลับไปหมวดตรวจสุขภาพและใบรับรองแพทย์"]

    buttons = [str(button).strip() for button in response.action_buttons if str(button).strip()]
    return list(dict.fromkeys(buttons))


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
    if response.selected_category and _category_rule(response.selected_category):
        response.selected_category = response.selected_category
    elif response.source_id:
        response.selected_category = _canonical_category_for_candidate(_find_candidate_by_id(response.source_id), query) or response.selected_category
    else:
        response.selected_category = _canonical_category_from_values(response.selected_category, None, query) or response.selected_category

    response.answer = clean_user_visible_answer(response.answer)
    response.attachments = _dedupe_attachments(response.attachments)
    if not response.answer and response.route == "fallback":
        response.answer = _official_fallback_answer()
    # ── Fallback tracking & auto-reset ────────────────────────────────────
    # Safe reasons that must NOT be overwritten by auto-reset
    _safe_fallback_reasons = {"unsupported_specific_query", "chat_unhandled_exception", "safe_unsupported_fallback", "emergency_redirect"}
    is_safe_fallback = response.reason in _safe_fallback_reasons

    # If route is fallback OR (clarify with very low confidence), count as failure
    is_failure = response.route == "fallback" or (response.route == "clarify" and response.confidence < 0.45)

    if is_failure and not is_safe_fallback:
        session.fallback_count += 1
        logger.info("⚠️ Session %s fallback_count incremented to %d (route=%s, confidence=%.2f)", session.session_id[:12], session.fallback_count, response.route, response.confidence)
        if session.fallback_count >= 2:
            logger.info("🔄 Fallback auto-reset for session %s (count=%d)", session.session_id[:12], session.fallback_count)
            session.reset_context(auto=True)
            response.is_fallback_reset = True
            response.answer = unclear_input_text()
            response.action_buttons = list(MAIN_THEME_BUTTONS)
            response.selected_category = None
    else:
        if session.fallback_count > 0:
            logger.info("✅ Session %s fallback_count reset from %d to 0 (route=%s)", session.session_id[:12], session.fallback_count, response.route)
        session.fallback_count = 0

    response.action_buttons = _normalize_response_buttons(response)

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


def _has_specific_match(query: str, candidate: RetrievalCandidate | None) -> bool:
    if candidate is None:
        return False
    if _record_type(candidate) in {"menu_node", "child_topic", "guidance"}:
        return False
    q = _compact_normalize(query)
    cq = _compact_normalize(candidate.question)
    if not q or not cq:
        return False
    if q == cq:
        return True
    if len(q) >= 8 and q in cq:
        return True
    meta = candidate.metadata or {}
    broad_labels = {
        _compact_normalize(candidate.category),
        _compact_normalize(_canonical_category_for_candidate(candidate, query) or ""),
        *(_compact_normalize(label) for label in MAIN_THEME_BUTTONS),
        *(_compact_normalize(label) for label in MAIN_THEME_CANONICAL.values()),
    }
    alias_fields = []
    alias_fields.extend(_parse_list_field(meta.get("aliases")))
    alias_fields.extend(_parse_list_field(meta.get("keywords")))
    alias_fields.extend([
        str(meta.get("topic") or "").strip(),
        str(meta.get("subcategory") or "").strip(),
    ])
    for alias in alias_fields:
        alias_compact = _compact_normalize(alias)
        if not alias_compact or alias_compact in broad_labels:
            continue
        if q == alias_compact:
            return True
        if len(q) >= 8 and q in alias_compact:
            return True
    return candidate.final_score >= 0.82


def _detect_preferred_category(query: str) -> tuple[str | None, str | None, float]:
    q = _strip_runtime_wrappers(query.strip())
    if not q:
        return None, None, 0.0
    normalized_query, typo_source = _normalize_typo(_looks_like_query_plus_noise(q))
    normalized = _normalize(normalized_query)
    compact_query = _compact_normalize(normalized_query)

    menu_label = _extract_menu_navigation_label(q)
    if menu_label:
        canonical = MAIN_THEME_CANONICAL.get(menu_label, menu_label)
        return canonical, (typo_source or menu_label), 1.0

    if "นักศึกษา" in normalized_query and "วัคซีน" in normalized_query:
        return "สวัสดิการวัคซีนนักศึกษา", (typo_source or normalized_query), 0.99
    if "วัคซีนมะเร็งปากมดลูกฟรี" in normalized_query and not any(token in normalized_query for token in ("นักศึกษา", "นิสิต")):
        return "วัคซีน", (typo_source or normalized_query), 0.99
    if any(token in normalized_query for token in ("ใบรับรอง", "ใบขับขี่")):
        return "การขอเอกสารทางการแพทย์", (typo_source or normalized_query), 0.99
    if any(token in normalized_query for token in ("บริษัท", "หมู่คณะ", "พนักงาน", "หน่วยงาน", "เบิกตรง")) and "ตรวจสุขภาพ" in normalized_query:
        return "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย", (typo_source or normalized_query), 0.99
    if any(token in normalized_query for token in ("ฟอกไต", "ไตเทียม", "ล้างไต", "ศูนย์ไต")):
        return "ศูนย์ไตเทียม", (typo_source or normalized_query), 0.99
    if any(token in normalized_query for token in ("บริจาคเลือด", "ธนาคารเลือด", "ให้เลือด")):
        return "ธนาคารเลือดและบริจาคเลือด", (typo_source or normalized_query), 0.99
    if any(token in normalized_query for token in ("หมอฟัน", "ทันตกรรม", "ทำฟัน", "โรงพยาบาลทันตกรรม")) and not _is_schedule_query(normalized_query):
        return "คลินิกทันตกรรม", (typo_source or normalized_query), 0.99
    if any(token in normalized_query for token in ("สมัครงาน", "งานบุคคล", "รับสมัครงาน")):
        return "กลุ่มงานบุคคล", (typo_source or normalized_query), 0.99

    schedule_markers = [
        "ตารางแพทย์",
        "ตารางหมอ",
        "หมอออกวันไหน",
        "หมอกระดูก",
        "หมอผิวหนัง",
        "หมอตา",
        "สูตินรีเวช",
        "กุมารแพทย์",
        "หมอเด็ก",
        "ent",
        "อายุรกรรม",
        "opd 1",
        "opd 2",
        "opd 3",
        "opd 4",
    ]
    if any(_compact_normalize(marker) in compact_query for marker in schedule_markers) and (
        "วันไหน" in normalized_query
        or "วันนี้" in normalized_query
        or "มีไหม" in normalized_query
        or "เปิด" in normalized_query
        or "เวลา" in normalized_query
        or "ตาราง" in normalized_query
    ):
        return "ตารางแพทย์และเวลาทำการ", (typo_source or normalized_query), 0.98

    appointment_markers = ["เลื่อนนัด", "ลืมวันนัด", "เช็ควันนัด", "นัดหมอ", "นัดพบแพทย์"]
    if any(_compact_normalize(marker) in compact_query for marker in appointment_markers):
        return "การจัดการนัดหมาย", (typo_source or normalized_query), 0.98

    for override, (category, _) in TOPIC_ALIAS_OVERRIDES.items():
        ov = _compact_normalize(override)
        if ov == compact_query or (len(ov) >= 8 and ov in compact_query):
            return category, (typo_source or override), 1.0

    if normalized in AMBIGUOUS_QUERY_CATEGORIES:
        return None, normalized, 0.0

    exact_hits: list[tuple[str, str]] = []
    for category, aliases in CATEGORY_ALIASES.items():
        for option in [category, *aliases]:
            opt_norm = _normalize(option)
            opt_compact = _compact_normalize(option)
            if not opt_norm:
                continue
            if normalized == opt_norm or compact_query == opt_compact:
                exact_hits.append((category, option))
            elif len(opt_compact) >= 3 and opt_compact in compact_query:
                exact_hits.append((category, option))
            elif len(compact_query) >= 3 and compact_query in opt_compact and len(compact_query) >= max(3, len(opt_compact) - 2):
                exact_hits.append((category, option))
    if exact_hits:
        exact_hits.sort(key=lambda x: len(x[1]), reverse=True)
        category, option = exact_hits[0]
        return category, (typo_source or option), 1.0

    category, option, score = _best_alias_match(normalized_query)
    if category and score >= 0.80:
        return category, (typo_source or option), score

    if len(compact_query) <= 4:
        if category and score >= 0.72:
            return category, (typo_source or option), score
        return None, (typo_source or option if typo_source else None), 0.0

    q_tokens = set(_meaningful_tokens(normalized_query))
    best_pair = None
    best_score = 0.0
    for category_name, aliases in CATEGORY_ALIASES.items():
        for option_name in [category_name, *aliases]:
            opt_tokens = set(_meaningful_tokens(option_name))
            token_overlap = len(q_tokens & opt_tokens) / max(len(q_tokens), 1) if q_tokens else 0.0
            score_value = max(
                token_overlap,
                SequenceMatcher(None, normalized, _normalize(option_name)).ratio() * 0.60 + token_overlap * 0.40,
                SequenceMatcher(None, _thai_heavy_normalize(normalized_query), _thai_heavy_normalize(option_name)).ratio() * 0.60 + token_overlap * 0.40,
            )
            if score_value > best_score:
                best_score = score_value
                best_pair = (category_name, option_name)
    if best_pair and best_score >= 0.65:
        return best_pair[0], (typo_source or best_pair[1]), best_score
    return None, (typo_source or None), 0.0


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


# ── Day-aware schedule helpers ────────────────────────────────────────────────
THAI_DAY_MAP: dict[str, str] = {
    "จันทร์": "จันทร์", "วันจันทร์": "จันทร์",
    "อังคาร": "อังคาร", "วันอังคาร": "อังคาร",
    "พุธ": "พุธ", "วันพุธ": "พุธ",
    "พฤหัส": "พฤหัสบดี", "วันพฤหัสบดี": "พฤหัสบดี", "พฤหัสบดี": "พฤหัสบดี",
    "ศุกร์": "ศุกร์", "วันศุกร์": "ศุกร์",
    "เสาร์": "เสาร์", "วันเสาร์": "เสาร์",
    "อาทิตย์": "อาทิตย์", "วันอาทิตย์": "อาทิตย์",
}
THAI_WEEKDAY_NAMES = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]


def _detect_thai_day(query: str) -> str | None:
    """Detect Thai weekday from query. Returns canonical Thai day name or None."""
    import datetime, zoneinfo
    q = _normalize(query)
    if "วันนี้" in q:
        bkk = zoneinfo.ZoneInfo("Asia/Bangkok")
        return THAI_WEEKDAY_NAMES[datetime.datetime.now(bkk).weekday()]
    if "พรุ่งนี้" in q:
        bkk = zoneinfo.ZoneInfo("Asia/Bangkok")
        return THAI_WEEKDAY_NAMES[(datetime.datetime.now(bkk).weekday() + 1) % 7]
    for term, canonical in sorted(THAI_DAY_MAP.items(), key=lambda x: -len(x[0])):
        if term in query:
            return canonical
    return None


def _filter_answer_by_day(answer: str, day: str) -> str:
    """Filter answer lines keeping only rows that mention the given day."""
    lines = answer.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.lstrip("-• ")
        if not line.startswith("-") and not line.startswith("•"):
            result.append(line)
        elif day in line:
            result.append(line)
    text = "\n".join(result).strip()
    return text if text else answer


def _format_schedule_answer(topic: RetrievalCandidate, day_filter: str | None = None) -> str:
    """Normalize structured schedule answers and preserve blank-doctor rows safely."""
    specialty = str((topic.metadata or {}).get("topic") or topic.question or "").strip()
    department = str((topic.metadata or {}).get("clinic") or topic.department or "").strip()
    raw_answer = str(topic.answer or "").strip()
    if not raw_answer:
        return format_direct_answer(topic)

    lines = [line.rstrip() for line in raw_answer.splitlines() if line.strip()]
    if not lines:
        return format_direct_answer(topic)

    header = lines[0].strip()
    normalized_rows: list[str] = list(SCHEDULE_TOPIC_ROW_OVERRIDES.get(specialty, []))
    body_lines = lines[1:]
    if normalized_rows:
        body_lines = []
    if not normalized_rows and not body_lines:
        for item in _parse_list_field((topic.metadata or {}).get("followup_hours")):
            if item:
                normalized_rows.append(f"- {item} : ยังไม่ระบุชื่อแพทย์ในข้อมูล")
    for line in body_lines:
        stripped = line.strip()
        if not stripped.startswith("-"):
            if stripped.startswith("ไฟล์แนบ/รูปประกอบ:") or ":\\" in stripped:
                continue
            normalized_rows.append(stripped)
            continue
        body = stripped[1:].strip()
        if ":" in body:
            left, right = body.split(":", 1)
            doctor = right.strip() or "ยังไม่ระบุชื่อแพทย์ในข้อมูล"
            normalized_rows.append(f"- {left.strip()} : {doctor}")
        else:
            normalized_rows.append(f"- {body} : ยังไม่ระบุชื่อแพทย์ในข้อมูล")

    if day_filter:
        filtered_rows = [row for row in normalized_rows if day_filter in row]
        if not filtered_rows:
            specialty_label = specialty or header or "แพทย์เฉพาะทาง"
            return (
                f"ไม่พบตารางออกตรวจของ {specialty_label} ในวันดังกล่าวในระบบปัจจุบัน\n"
                f"หากต้องการดูตารางรายสัปดาห์ทั้งหมด กรุณาพิมพ์ชื่อเฉพาะทางอีกครั้งค่ะ"
            )
        normalized_rows = filtered_rows

    final_header = header
    if normalized_rows:
        section_title = "ตารางออกตรวจ:"
        if day_filter:
            section_title = f"ตารางออกตรวจวัน{day_filter}:"
        if specialty and department and department not in header:
            final_header = f"{specialty} — {department}"
        return clean_user_visible_answer(final_header + "\n\n" + section_title + "\n" + "\n".join(normalized_rows))
    if specialty and department and department not in header:
        final_header = f"{specialty} — {department}"
    if normalized_rows:
        return final_header + "\n\nตารางออกตรวจ:\n" + "\n".join(normalized_rows)
    return clean_user_visible_answer(final_header)


def _build_attachments_for_topic(topic: RetrievalCandidate, label_prefix: str = "รูปตารางแพทย์") -> list[Attachment]:
    """Build Attachment list from followup_image_paths, converting Windows paths to public URLs."""
    meta = topic.metadata or {}
    raw_paths = _parse_list_field(meta.get("followup_image_paths"))
    attachments: list[Attachment] = []
    for raw_path in raw_paths:
        url = _image_path_to_url(raw_path)
        if url:
            filename = Path(raw_path).name
            topic_label = str(meta.get("topic") or topic.question or "").strip()
            attachments.append(Attachment(
                type="image",
                label=f"{label_prefix} {topic_label}".strip(),
                url=url,
                filename=filename,
            ))
    # BUG 5 FIX: Dedupe attachments before returning
    return _dedupe_attachments(attachments)


def _build_health_check_attachments() -> list[Attachment]:
    """Build attachments from the health check image folder."""
    attachments: list[Attachment] = []
    if not HEALTH_CHECK_IMAGE_DIR.exists():
        return attachments
    for img_file in sorted(HEALTH_CHECK_IMAGE_DIR.iterdir()):
        if img_file.suffix.lower() in ALLOWED_ASSET_EXTENSIONS:
            attachments.append(Attachment(
                type="image",
                label=f"รูปโปรแกรมตรวจสุขภาพ {img_file.stem}",
                url=f"/assets/health-check/{img_file.name}",
                filename=img_file.name,
            ))
    # BUG 5 FIX: Dedupe attachments before returning
    return _dedupe_attachments(attachments)


def _attachments_for_answer_topic(topic: RetrievalCandidate) -> list[Attachment]:
    attachments = _build_attachments_for_topic(topic)
    raw_cat = str(topic.category or "").strip()
    canonical_cat = _canonical_category_for_candidate(topic, topic.question) or raw_cat
    if canonical_cat in {"ตรวจสุขภาพรายบุคคล", "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย", "การขอเอกสารทางการแพทย์"}:
        topic_text = _normalize(str(topic.question or "") + " " + str(topic.subcategory or ""))
        if any(marker in topic_text for marker in ("โปรแกรมตรวจสุขภาพ", "ตรวจสุขภาพ", "ใบรับรองแพทย์", "ใบรับรอง")):
            if not attachments:
                attachments = _build_health_check_attachments()
    # BUG 5 FIX: Dedupe attachments before returning (in case multiple sources were combined)
    return _dedupe_attachments(attachments)


def _health_check_shortcut_candidate(query: str) -> tuple[RetrievalCandidate, str] | None:
    query_text = _normalize(query)
    if query_text == _normalize("เวลาตรวจสุขภาพ"):
        topic_id, selected_category = "qa-0050", "ตรวจสุขภาพรายบุคคล"
    elif query_text == _normalize("โปรแกรมตรวจสุขภาพ"):
        topic_id, selected_category = "qa-0049", "ตรวจสุขภาพรายบุคคล"
    elif query_text == _normalize("ใบรับรองแพทย์"):
        topic_id, selected_category = "qa-0053", "การขอเอกสารทางการแพทย์"
    else:
        shortcut = HEALTH_CHECK_SHORTCUTS.get(str(query or "").strip())
        if shortcut is None:
            return None
        topic_id, selected_category = shortcut
    if not topic_id:
        return None
    topic = _find_candidate_by_id(topic_id)
    if topic is None:
        return None
    return topic, selected_category


def _chat_impl(req: ChatRequest) -> ChatResponse:
    t_start = time.time()
    query = req.question.strip()
    raw_query = query
    wrapper_stripped_query = _strip_runtime_wrappers(query)
    logger.info("📨 /chat session=%s query='%s'", req.session_id[:12], query[:80])

    # ── KB not ready — friendly fallback instead of 503 ──
    if not state.records and state.retriever is None:
        logger.warning("⚠️  KB not ready — returning friendly fallback for query: %s", query)
        return ChatResponse(
            route="fallback",
            answer=_official_fallback_answer(),
            confidence=0.0,
            reason="kb_not_ready",
            action_buttons=list(FALLBACK_ACTION_BUTTONS),
        )

    session = state.get_session(req.session_id)
    normalized_query, typo_source = _normalize_typo(_looks_like_query_plus_noise(wrapper_stripped_query))
    original_normalized_query = normalized_query

    menu_label = _extract_menu_navigation_label(raw_query) or _extract_menu_navigation_label(original_normalized_query)
    if menu_label:
        canonical = MAIN_THEME_CANONICAL.get(menu_label, menu_label)
        category_candidates = _category_browse_candidates(canonical)
        buttons = _category_action_buttons(canonical, category_candidates)
        _remember(session, category=canonical, buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer=build_category_overview(canonical, buttons),
            confidence=1.0,
            reason="main_menu_navigation",
            selected_category=canonical,
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[_to_candidate_response(c) for c in category_candidates[:5]],
        )
        return _finalize_chat_response(req, session, raw_query, response)

    for label in MAIN_THEME_BUTTONS:
        canonical = MAIN_THEME_CANONICAL.get(label, label)
        if _looks_like_menu_label(raw_query, label) or _looks_like_menu_label(wrapper_stripped_query, label) or _looks_like_menu_label(original_normalized_query, label):
            category_candidates = _category_browse_candidates(canonical)
            buttons = _category_action_buttons(canonical, category_candidates)
            _remember(session, category=canonical, buttons=buttons)
            response = ChatResponse(
                route="clarify",
                answer=build_category_overview(canonical, buttons),
                confidence=1.0,
                reason="main_menu_navigation",
                selected_category=canonical,
                clarification_options=buttons,
                action_buttons=buttons,
                candidates=[_to_candidate_response(c) for c in category_candidates[:5]],
            )
            return _finalize_chat_response(req, session, raw_query, response)

    if _normalize(raw_query) == _normalize("ตรวจสุขภาพ") or _normalize(wrapper_stripped_query) == _normalize("ตรวจสุขภาพ"):
        buttons = ["ค้นหาตามเฉพาะทาง", "ดูตารางสาขาอื่น", "เวลาทำการแผนกผู้ป่วยนอก", "กลับไปหมวดนัดหมายและตารางแพทย์"]
        answer = (
            "ตรวจสุขภาพ (ผู้ป่วยนอก 2/OPD 2)\n"
            "- วันจันทร์และวันอังคาร 08.00-16.00 น. : แพทย์หญิงชนกนันท์ เนติศุภลักษณ์\n"
            "- วันพฤหัสบดี 08.00-16.00 น. : แพทย์หญิงอชิรญา ชนะพาล\n"
            "- วันศุกร์ 08.00-12.00 น. : แพทย์หญิงอชิรญา ชนะพาล"
        )
        attachments = _dedupe_attachments([
            Attachment(
                type="image",
                label="รูปตารางแพทย์ ตรวจสุขภาพ",
                url="/assets/schedule/เวชศาสตร์.png",
                filename="เวชศาสตร์.png",
            )
        ])
        _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=buttons)
        response = ChatResponse(
            route="answer",
            answer=answer,
            confidence=1.0,
            reason="schedule_checkup_pre_rewrite",
            selected_category="ตารางแพทย์และเวลาทำการ",
            action_buttons=buttons,
            attachments=attachments,
            candidates=[],
        )
        return _finalize_chat_response(req, session, raw_query, response)

    query = _strip_runtime_wrappers(_rewrite_runtime_query(original_normalized_query))

    broad_vaccine_terms = {"วัคซีน", "วักซีน", "วัปซีน", "วคซีน"}
    if _normalize(raw_query) in broad_vaccine_terms or _normalize(original_normalized_query) in broad_vaccine_terms:
        category_candidates = _category_browse_candidates("วัคซีน")
        buttons = _category_action_buttons("วัคซีน", category_candidates)
        _remember(session, category="วัคซีน", buttons=buttons)
        corrected_from = None if _normalize(raw_query) == "วัคซีน" else raw_query
        response = ChatResponse(
            route="clarify" if _normalize(raw_query) == "วัคซีน" else "answer",
            answer=build_category_overview("วัคซีน", buttons, corrected_from=corrected_from),
            confidence=0.98,
            reason="broad_vaccine_navigation",
            selected_category="วัคซีน",
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[_to_candidate_response(c) for c in category_candidates[:5]],
        )
        return _finalize_chat_response(req, session, raw_query, response)

    if "สมัครงาน" in _normalize(raw_query) and "ใบรับรอง" in _normalize(raw_query):
        doc_candidates = _catalog_search("ขอใบรับรองแพทย์", category="การขอเอกสารทางการแพทย์", limit=3)
        if doc_candidates:
            doc_topic = doc_candidates[0]
            buttons = _topic_follow_up_buttons(doc_topic)
            _remember(session, category="การขอเอกสารทางการแพทย์", topic=doc_topic, buttons=buttons)
            response = ChatResponse(
                route="answer",
                answer=format_direct_answer(doc_topic),
                confidence=max(round(doc_topic.final_score, 4), 0.9),
                reason="job_medical_certificate_match",
                source_id=doc_topic.id,
                selected_category="การขอเอกสารทางการแพทย์",
                action_buttons=buttons,
                candidates=[_to_candidate_response(doc_topic)],
            )
            return _finalize_chat_response(req, session, raw_query, response)

    for label in MAIN_THEME_BUTTONS:
        canonical = MAIN_THEME_CANONICAL.get(label, label)
        if _looks_like_menu_label(query, label) or _looks_like_menu_label(_strip_runtime_wrappers(query), label):
            category_candidates = _category_browse_candidates(canonical)
            buttons = _category_action_buttons(canonical, category_candidates)
            _remember(session, category=canonical, buttons=buttons)
            response = ChatResponse(
                route="clarify",
                answer=build_category_overview(canonical, buttons),
                confidence=1.0,
                reason="main_menu_navigation",
                selected_category=canonical,
                clarification_options=buttons,
                action_buttons=buttons,
                candidates=[_to_candidate_response(c) for c in category_candidates[:5]],
            )
            return _finalize_chat_response(req, session, query, response)

    # Special case: Explicitly handle "นัดหมายและตารางแพทย์" to ensure both child branches are exposed
    if _normalize(query) == "นัดหมายและตารางแพทย์":
        canonical = "นัดหมายและตารางแพทย์"
        buttons = MAIN_THEME_CHILDREN.get(canonical, ["การจัดการนัดหมาย", "ตารางแพทย์และเวลาทำการ", "กลับหน้าหลัก"])
        _remember(session, category=canonical, buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer="หมวด" + canonical + " มีหัวข้อย่อยที่เลือกได้ดังนี้\n" + "\n".join(f"- {b}" for b in buttons if b != "กลับหน้าหลัก") + "\nกรุณาเลือกหัวข้อที่ต้องการ หรือพิมพ์รายละเอียดเพิ่มได้เลยค่ะ",
            confidence=1.0,
            reason="main_menu_appointment_schedule_both_branches",
            selected_category=canonical,
            clarification_options=buttons,
            action_buttons=buttons,
        )
        return _finalize_chat_response(req, session, raw_query, response)

    # ── Strong new intent detection: override stale category context ──
    # Guard: Only allow cross-category switching if NOT a follow-up query
    # AND if we don't have an active topic that could answer the follow-up
    new_cat, new_alias, new_score = _detect_preferred_category(query)
    
    # Check if this is a follow-up query that should bind to current topic
    is_followup = _is_follow_up_query(query)
    has_active_topic = session.last_topic_id is not None
    
    # If it's a follow-up and we have an active topic, suppress category switching
    # to ensure follow-up binds to current topic first
    if is_followup and has_active_topic:
        logger.info("🔗 Follow-up query detected with active topic, suppressing category switch: %s", query[:50])
        # Skip the category switch below
    elif new_cat and new_score >= 0.85 and session.last_category and new_cat != session.last_category and not is_followup:
        logger.info("🔄 Cross-category switch: %s → %s (score=%.2f)", session.last_category, new_cat, new_score)
        session.last_category = new_cat
        session.last_topic_id = None
        session.last_topic_question = None
    
    # Special case: Image follow-up should NOT trigger category switch
    # If current topic is a schedule topic and user asks for image, stay in that topic
    if _is_image_follow_up(query) and session.last_topic_id and session.last_category:
        # Check if current topic is schedule-related
        current_topic = _find_candidate_by_id(session.last_topic_id)
        if current_topic and "ตารางแพทย์" in session.last_category:
            # Suppress category switching for image follow-ups in schedule topics
            logger.info("🖼️  Image follow-up detected in schedule topic, preserving context: %s", session.last_category)

    # ── Manual Reset / Back to Home ──
    if re.search(r"เริ่มใหม่|หน้าแรก|หน้าหลัก|reset|เมนูหลัก", query, re.IGNORECASE):
        session.reset_context()
        return ChatResponse(
            route="clarify",
            answer=WELCOME_MESSAGE,
            confidence=1.0,
            reason="manual_reset",
            action_buttons=list(MAIN_THEME_BUTTONS)
        )

    if BACK_RE.search(query):
        # Check if query is "กลับไปหมวด..."
        back_match = re.search(r"\u0e01\u0e25\u0e31\u0e1a\u0e44\u0e1b\u0e2b\u0e21\u0e27\u0e14(.+)", query)
        back_theme = None
        if back_match:
            back_label = back_match.group(1).strip()
            # Find parent theme from MAIN_THEME_CHILDREN
            for theme, children in MAIN_THEME_CHILDREN.items():
                if any(_compact_normalize(c) == _compact_normalize(back_label) or _compact_normalize(theme) == _compact_normalize(back_label) for c in [theme]):
                    back_theme = theme
                    break
            if not back_theme:
                for theme in MAIN_THEME_BUTTONS:
                    if _compact_normalize(back_label) in _compact_normalize(theme) or _compact_normalize(theme) in _compact_normalize(back_label):
                        back_theme = theme
                        break
        if back_theme and back_theme in MAIN_THEME_CHILDREN:
            buttons = list(MAIN_THEME_CHILDREN[back_theme])
            _remember(session, category=back_theme, buttons=buttons)
            return ChatResponse(
                route="clarify",
                answer="\u0e2b\u0e21\u0e27\u0e14" + back_theme + " \u0e21\u0e35\u0e2b\u0e31\u0e27\u0e02\u0e49\u0e2d\u0e22\u0e48\u0e2d\u0e22\u0e17\u0e35\u0e48\u0e40\u0e25\u0e37\u0e2d\u0e01\u0e44\u0e14\u0e49\u0e14\u0e31\u0e07\u0e19\u0e35\u0e49\n" + "\n".join(f"- {b}" for b in buttons if b != "\u0e01\u0e25\u0e31\u0e1a\u0e2b\u0e19\u0e49\u0e32\u0e2b\u0e25\u0e31\u0e01") + "\n\u0e01\u0e23\u0e38\u0e13\u0e32\u0e40\u0e25\u0e37\u0e2d\u0e01\u0e2b\u0e31\u0e27\u0e02\u0e49\u0e2d\u0e17\u0e35\u0e48\u0e15\u0e49\u0e2d\u0e07\u0e01\u0e32\u0e23 \u0e2b\u0e23\u0e37\u0e2d\u0e1e\u0e34\u0e21\u0e1e\u0e4c\u0e23\u0e32\u0e22\u0e25\u0e30\u0e40\u0e2d\u0e35\u0e22\u0e14\u0e40\u0e1e\u0e34\u0e48\u0e21\u0e44\u0e14\u0e49\u0e40\u0e25\u0e22\u0e04\u0e48\u0e30",
                confidence=0.95,
                reason="back_to_main_theme",
                selected_category=back_theme,
                clarification_options=buttons,
                action_buttons=buttons,
            )
        elif session.last_category:
            category_candidates = _category_browse_candidates(session.last_category)
            buttons = _category_action_buttons(session.last_category, category_candidates)
            _remember(session, category=session.last_category, buttons=buttons)
            return ChatResponse(
                route="clarify",
                answer=build_category_overview(session.last_category, buttons),
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

    shortcut_query = wrapper_stripped_query or raw_query

    if _normalize(query) == "ติดต่อโรงพยาบาล":
        response = ChatResponse(
            route="answer",
            answer=_official_contact_answer(),
            confidence=1.0,
            reason="official_contact",
            action_buttons=list(FALLBACK_ACTION_BUTTONS),
        )
        return _finalize_chat_response(req, session, query, response)

    if _normalize(shortcut_query) == _normalize("เวลาตรวจสุขภาพ"):
        logger.info("Using exact health-check hours shortcut for query='%s'", shortcut_query)
        topic = _find_candidate_by_id("qa-0050")
        buttons = _topic_follow_up_buttons(topic) if topic is not None else ["เวลาตรวจสุขภาพ", "โปรแกรมตรวจสุขภาพ", "ใบรับรองแพทย์", "กลับไปหมวดตรวจสุขภาพและใบรับรองแพทย์"]
        answer = HEALTH_CHECK_HOURS_ANSWER
        if topic is not None:
            _remember(session, category="ตรวจสุขภาพรายบุคคล", topic=topic, buttons=buttons)
        else:
            _remember(session, category="ตรวจสุขภาพรายบุคคล", buttons=buttons)
        response = ChatResponse(
            route="answer",
            answer=answer,
            confidence=1.0,
            reason="health_check_hours_shortcut",
            source_id=topic.id if topic is not None else None,
            selected_category="ตรวจสุขภาพรายบุคคล",
            action_buttons=buttons,
            attachments=[],
            candidates=[_to_candidate_response(topic)] if topic is not None else [],
        )
        return _finalize_chat_response(req, session, shortcut_query, response)

    health_shortcut = _health_check_shortcut_candidate(shortcut_query)
    if health_shortcut is not None:
        logger.info("Using generic health-check shortcut for query='%s'", shortcut_query)
        topic, selected_category = health_shortcut
        buttons = _topic_follow_up_buttons(topic)
        shortcut_answer = format_direct_answer(topic)
        if _normalize(shortcut_query) == _normalize("โปรแกรมตรวจสุขภาพ"):
            shortcut_answer = HEALTH_CHECK_PROGRAM_ANSWER
        elif _normalize(shortcut_query) == _normalize("ใบรับรองแพทย์"):
            shortcut_answer = HEALTH_CHECK_CERTIFICATE_ANSWER
        _remember(session, category=selected_category, topic=topic, buttons=buttons)
        response = ChatResponse(
            route="answer",
            answer=shortcut_answer,
            confidence=1.0,
            reason="health_check_shortcut",
            source_id=topic.id,
            selected_category=selected_category,
            action_buttons=buttons,
            attachments=_attachments_for_answer_topic(topic),
            candidates=[_to_candidate_response(topic)],
        )
        return _finalize_chat_response(req, session, shortcut_query, response)

    query_normalized = _normalize(query)
    query_compact = _compact_normalize(query)

    appointment_buttons = ["การจัดการนัดหมาย", "ตารางแพทย์และเวลาทำการ", "กลับหน้าหลัก"]
    reschedule_markers = ("ขอเลื่อนนัดพบแพทย์", "เลื่อนนัดพบแพทย์", "ขอเลื่อนนัด", "เลื่อนนัด", "ขอเปลี่ยนนัด", "เปลี่ยนนัด")
    if any(_compact_normalize(marker) in query_compact for marker in reschedule_markers):
        topic = _find_candidate_by_id("qa-0002") or _find_candidate_by_id("qa-0039")
        answer = format_direct_answer(topic) if topic is not None else (
            "แผนกผู้ป่วยนอก 1 โทร 054 466 666 ต่อ 7304\n"
            "แผนกผู้ป่วยนอก 2 โทร 054 466 666 ต่อ 7173\n"
            "แผนกผู้ป่วยนอก 3 (หู คอ จมูก ตา) โทร 054 466 666 ต่อ 7210\n"
            "แผนกผู้ป่วยนอก 3 (สูติ-นรีเวช) โทร 054 466 666 ต่อ 7152\n"
            "แผนกผู้ป่วยนอก 4 (ความดัน/ระบบประสาทและสมอง/ทางเดินอาหาร) โทร 054 466 666 ต่อ 7182\n"
            "แผนกผู้ป่วยนอก 4 (หัวใจ) โทร 054 466 666 ต่อ 7171\n"
            "แผนกกระดูกและข้อ โทร 054 466 666 ต่อ 7406/7409\n"
            "ห้อง X-Ray/CT-Scan โทร 054 466 666 ต่อ 7291\n"
            "แผนกกายภาพบำบัด โทร 054 46 666 ต่อ 7190\n"
            "แผนกแพทย์แผนไทย&จีน โทร 054 466 666 ต่อ 7113, 7114"
        )
        if topic is not None:
            _remember(session, category="การจัดการนัดหมาย", topic=topic, buttons=appointment_buttons)
        else:
            _remember(session, category="การจัดการนัดหมาย", buttons=appointment_buttons)
        response = ChatResponse(
            route="answer",
            answer=answer,
            confidence=1.0,
            reason="appointment_reschedule_shortcut",
            source_id=topic.id if topic is not None else None,
            selected_category="การจัดการนัดหมาย",
            action_buttons=appointment_buttons,
            attachments=[],
            candidates=[_to_candidate_response(topic)] if topic is not None else [],
        )
        return _finalize_chat_response(req, session, query, response)

    if query_normalized == _normalize("เวลาทำการแผนกผู้ป่วยนอก"):
        topic = _find_candidate_by_id("qa-0011") or _find_candidate_by_id("qa-0048")
        buttons = ["ตารางแพทย์ออกตรวจ", "เวลาทำการแผนกผู้ป่วยนอก", "กลับไปหมวดนัดหมายและตารางแพทย์"]
        answer = format_direct_answer(topic) if topic is not None else (
            "แผนกผู้ป่วยนอก เปิดในเวลา 08.00-16.00 น. ทุกวันทำการ นอกเวลาทำการ 16.00-20.00 น. "
            "หยุดทุกวันเสาร์-อาทิตย์ และวันหยุดนักขัตฤกษ์ค่ะ\n*แผนกฉุกเฉินเปิดบริการ 24 ชั่วโมง*"
        )
        if topic is not None:
            _remember(session, category="ตารางแพทย์และเวลาทำการ", topic=topic, buttons=buttons)
        else:
            _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=buttons)
        response = ChatResponse(
            route="answer",
            answer=answer,
            confidence=1.0,
            reason="opd_hours_shortcut",
            source_id=topic.id if topic is not None else None,
            selected_category="ตารางแพทย์และเวลาทำการ",
            action_buttons=buttons,
            attachments=[],
            candidates=[_to_candidate_response(topic)] if topic is not None else [],
        )
        return _finalize_chat_response(req, session, query, response)

    if query_normalized == _normalize("ตรวจสุขภาพ"):
        buttons = ["ค้นหาตามเฉพาะทาง", "ดูตารางสาขาอื่น", "เวลาทำการแผนกผู้ป่วยนอก", "กลับไปหมวดนัดหมายและตารางแพทย์"]
        answer = (
            "ตรวจสุขภาพ (ผู้ป่วยนอก 2/OPD 2)\n"
            "- วันจันทร์และวันอังคาร 08.00-16.00 น. : แพทย์หญิงชนกนันท์ เนติศุภลักษณ์\n"
            "- วันพฤหัสบดี 08.00-16.00 น. : แพทย์หญิงอชิรญา ชนะพาล\n"
            "- วันศุกร์ 08.00-12.00 น. : แพทย์หญิงอชิรญา ชนะพาล"
        )
        attachments = _dedupe_attachments([
            Attachment(
                type="image",
                label="รูปตารางแพทย์ ตรวจสุขภาพ",
                url="/assets/schedule/เวชศาสตร์.png",
                filename="เวชศาสตร์.png",
            )
        ])
        _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=buttons)
        response = ChatResponse(
            route="answer",
            answer=answer,
            confidence=1.0,
            reason="schedule_checkup_exact_shortcut",
            selected_category="ตารางแพทย์และเวลาทำการ",
            action_buttons=buttons,
            attachments=attachments,
            candidates=[],
        )
        return _finalize_chat_response(req, session, query, response)

    # BUG 1 FIX: Early detection for "ตรวจสุขภาพ" queries to prevent routing to schedule
    # This must come before schedule matching logic
    health_check_keywords = {"โปรแกรมตรวจสุขภาพ", "เวลาตรวจสุขภาพ", "ใบรับรองแพทย์"}
    if any(keyword in query_normalized for keyword in health_check_keywords):
        # Check if this is NOT in a schedule context
        schedule_context_active = session.last_category in {"ตารางแพทย์และเวลาทำการ", "นัดหมายและตารางแพทย์"}
        # Only route to health-check if NOT in schedule context AND query is health-check related
        if not schedule_context_active and not _is_schedule_query(query):
            logger.info("Health-check query detected, routing to health-check category: '%s'", query[:50])
            # Route to health-check category overview
            category_candidates = _category_browse_candidates("ตรวจสุขภาพและใบรับรองแพทย์")
            buttons = ["เวลาตรวจสุขภาพ", "โปรแกรมตรวจสุขภาพ", "ใบรับรองแพทย์", "กลับหน้าหลัก"]
            _remember(session, category="ตรวจสุขภาพรายบุคคล", buttons=buttons)
            response = ChatResponse(
                route="clarify",
                answer="หมวดตรวจสุขภาพและใบรับรองแพทย์ มีหัวข้อที่เลือกได้ดังนี้\n" + "\n".join(f"- {b}" for b in buttons if b != "กลับหน้าหลัก"),
                confidence=0.98,
                reason="health_check_category_routing",
                selected_category="ตรวจสุขภาพรายบุคคล",
                clarification_options=buttons,
                action_buttons=buttons,
                candidates=[_to_candidate_response(c) for c in category_candidates[:5]],
            )
            return _finalize_chat_response(req, session, query, response)

    category_hint, matched_alias, alias_score = _detect_preferred_category(req.preferred_category or query)
    # If the session was just reset very recently, and the current query is a small follow-up
    # (price/contact/hours), do not apply category routing — ask the user to pick a topic again.
    if session.last_reset_at and (time.time() - session.last_reset_at) < 5 and _is_follow_up_query(query) and not _is_schedule_query(query):
        logger.info("🔴 Post-reset follow-up ignored: session_id=%s, last_reset_at=%.2f, query=%s", session.session_id[:12], session.last_reset_at, query[:50])
        return ChatResponse(
            route="clarify",
            answer=WELCOME_MESSAGE,
            confidence=0.9,
            reason="post_reset_followup_ignored",
            action_buttons=list(MAIN_THEME_BUTTONS),
        )
    no_context_slot_queries = {
        "ราคาเท่าไหร่",
        "ราคาเท่าไร",
        "ติดต่อที่ไหน",
        "เปิดวันไหน",
        "เปิดกี่โมง",
        "เข้าได้เลยไหม",
        "โทรอะไร",
        "มีรูปไหม",
        "มีภาพไหม",
        "ขอดูรูป",
        "มีไฟล์ไหม",
        "มีลิงก์ไหม",
    }
    if _normalize(query) in no_context_slot_queries and not session.last_topic_id and not session.last_category and not category_hint:
        return ChatResponse(
            route="clarify",
            answer=WELCOME_MESSAGE,
            confidence=0.9,
            reason="no_context_short_slot_query",
            action_buttons=list(MAIN_THEME_BUTTONS),
        )
    if _normalize(query) == "มีไหม" and not session.last_topic_id and not session.last_category and not category_hint:
        return ChatResponse(
            route="fallback",
            answer=unclear_input_text(),
            confidence=0.92,
            reason="naked_yesno_without_context",
            action_buttons=GUIDE_ITEMS[:8],
        )
    if _is_follow_up_query(query) and not _is_schedule_query(query) and not session.last_topic_id and not session.last_category and not category_hint:
        return ChatResponse(
            route="clarify",
            answer=WELCOME_MESSAGE,
            confidence=0.9,
            reason="followup_without_context",
            action_buttons=list(MAIN_THEME_BUTTONS),
        )
    # Only apply session category as follow-up hint when we have a concrete last topic
    if category_hint is None and session.last_category and session.last_topic_id and _is_follow_up_query(query) and not _is_schedule_query(query):
        category_hint = session.last_category
        matched_alias = session.last_category
        alias_score = 0.50  # Reduced from 0.7 to make category switching easier

    if _is_follow_up_query(query) and not _is_schedule_query(query) and not session.last_topic_id:
        followup_category = session.last_category or category_hint
        if followup_category:
            category_candidates = _category_browse_candidates(followup_category)
            buttons = _category_action_buttons(followup_category, category_candidates)
            _remember(session, category=followup_category, buttons=buttons)
            response = ChatResponse(
                route="clarify",
                answer=build_category_overview(_canonical_category_from_values(followup_category, None, query) or followup_category, buttons),
                confidence=0.88,
                reason="followup_requires_topic_context",
                selected_category=followup_category,
                clarification_options=buttons,
                action_buttons=buttons,
                candidates=[_to_candidate_response(c) for c in category_candidates[:5]],
            )
            return _finalize_chat_response(req, session, query, response)

    schedule_query_norm = _normalize(query)
    if schedule_query_norm == "ตารางแพทย์และเวลาทำการ":
        buttons = ["ตารางแพทย์ออกตรวจ", "เวลาทำการแผนกผู้ป่วยนอก", "กลับไปหมวดนัดหมายและตารางแพทย์"]
        _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer="หมวด ตารางแพทย์และเวลาทำการ มีหัวข้อย่อยที่เลือกได้ดังนี้",
            confidence=1.0,
            reason="schedule_category_menu",
            selected_category="ตารางแพทย์และเวลาทำการ",
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[],
        )
        return _finalize_chat_response(req, session, query, response)

    if schedule_query_norm in {"ตารางแพทย์ออกตรวจ", "ดูตารางสาขาอื่น", "เลือกแผนกตารางแพทย์", "กลับไปเลือกแผนกตารางแพทย์"}:
        buttons = list(SCHEDULE_DEPARTMENT_MENU)
        _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer="ต้องการดูตารางแพทย์ของแผนกใดคะ",
            confidence=0.99,
            reason="schedule_department_menu",
            selected_category="ตารางแพทย์และเวลาทำการ",
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[],
        )
        return _finalize_chat_response(req, session, query, response)

    if schedule_query_norm == "ค้นหาตามเฉพาะทาง":
        buttons = list(SCHEDULE_SPECIALTY_MENU)
        _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer="ต้องการทราบตารางแพทย์ของเฉพาะทางใดคะ",
            confidence=0.99,
            reason="schedule_specialty_menu",
            selected_category="ตารางแพทย์และเวลาทำการ",
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[],
        )
        return _finalize_chat_response(req, session, query, response)

    schedule_department = _normalize_schedule_department(query)
    if schedule_department:
        buttons = list(SCHEDULE_DEPARTMENT_SPECIALTIES.get(schedule_department, []))
        _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer=f"แผนก {schedule_department} มีเฉพาะทางดังนี้",
            confidence=0.99,
            reason="schedule_department_specialty_menu",
            selected_category="ตารางแพทย์และเวลาทำการ",
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[],
        )
        return _finalize_chat_response(req, session, query, response)

    schedule_context_active = session.last_category in {"ตารางแพทย์และเวลาทำการ", "นัดหมายและตารางแพทย์"}
    doctor_schedule_match = _match_schedule_master_doctor(query) or _match_schedule_doctor(query)
    if doctor_schedule_match:
        ambiguous_doctors = doctor_schedule_match.get("ambiguous_doctors")
        if ambiguous_doctors:
            response = ChatResponse(
                route="clarify",
                answer="พบชื่อแพทย์ใกล้เคียงมากกว่าหนึ่งท่าน กรุณาเลือกชื่อแพทย์ที่ต้องการ",
                confidence=0.75,
                reason="schedule_doctor_ambiguous",
                selected_category="ตารางแพทย์และเวลาทำการ",
                clarification_options=ambiguous_doctors,
                action_buttons=ambiguous_doctors,
                candidates=[],
            )
            return _finalize_chat_response(req, session, query, response)

        if doctor_schedule_match.get("topic") is not None:
            schedule_topic = doctor_schedule_match["topic"]
            answer_text = _format_schedule_doctor_answer(doctor_schedule_match)
            attachments = _build_attachments_for_topic(schedule_topic)
            buttons = _topic_follow_up_buttons(schedule_topic)
            source_id = schedule_topic.id
            candidates = [_to_candidate_response(schedule_topic)]
            _remember(session, category="ตารางแพทย์และเวลาทำการ", topic=schedule_topic, buttons=buttons)
        else:
            source_topic = None
            source_id = None
            doctor_rows = list(doctor_schedule_match.get("rows") or [])
            if doctor_rows:
                source_id = doctor_rows[0]["entry"].source_id
                source_topic = _find_candidate_by_id(source_id)
            answer_text = _format_schedule_master_doctor_answer(doctor_schedule_match)
            attachments = _schedule_master_attachments_for_doctor(doctor_schedule_match)
            buttons = _topic_follow_up_buttons(source_topic) if source_topic is not None else ["ค้นหาตามเฉพาะทาง", "ดูตารางสาขาอื่น", "เวลาทำการแผนกผู้ป่วยนอก", "กลับไปหมวดนัดหมายและตารางแพทย์"]
            candidates = [_to_candidate_response(source_topic)] if source_topic is not None else []
            if source_topic is not None:
                _remember(session, category="ตารางแพทย์และเวลาทำการ", topic=source_topic, buttons=buttons)
            else:
                _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=buttons)
        response = ChatResponse(
            route="answer",
            answer=answer_text,
            confidence=0.98,
            reason="schedule_doctor_match",
            source_id=source_id,
            selected_category="ตารางแพทย์และเวลาทำการ",
            action_buttons=buttons,
            attachments=attachments,
            candidates=candidates,
        )
        return _finalize_chat_response(req, session, query, response)

    schedule_master_entry = _find_schedule_master_entry(query)
    if _is_schedule_query(query) or schedule_context_active or schedule_master_entry is not None:
        schedule_match = _match_schedule_record(query)
        broad_schedule = bool(re.fullmatch(r"(ตารางแพทย์|ตารางหมอ|หมอออกตรวจ|หมอเข้า|หมอวันนี้|แพทย์ออกตรวจ)", query.strip()))
        schedule_q = _normalize(query)
        if schedule_q in {"ตารางแพทย์ออกตรวจ", "เวลาทำการแผนกผู้ป่วยนอก"}:
            broad_schedule = True
        schedule_compact = _compact_normalize(query)
        has_specialty_marker = any(
            _compact_normalize(alias) in schedule_compact
            for aliases in SCHEDULE_SPECIALTY_ALIASES.values()
            for alias in aliases
        )
        generic_schedule_terms = ("วันไหน" in query or "วันนี้" in query or "มีไหม" in query)
        broad_schedule = broad_schedule or (
            not has_specialty_marker
            and ("หมอ" in query or "แพทย์" in query)
            and generic_schedule_terms
        )
        if schedule_master_entry is not None and not broad_schedule:
            day_filter = _detect_thai_day(query)
            source_topic = _find_candidate_by_id(schedule_master_entry.source_id)
            answer_text = _format_schedule_master_answer(schedule_master_entry, day_filter=day_filter)
            attachments = _build_schedule_master_attachments(schedule_master_entry)
            buttons = _topic_follow_up_buttons(source_topic) if source_topic is not None else ["ค้นหาตามเฉพาะทาง", "ดูตารางสาขาอื่น", "เวลาทำการแผนกผู้ป่วยนอก", "กลับไปหมวดนัดหมายและตารางแพทย์"]
            if source_topic is not None:
                _remember(session, category="ตารางแพทย์และเวลาทำการ", topic=source_topic, buttons=buttons)
            else:
                _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=buttons)
            response = ChatResponse(
                route="answer",
                answer=answer_text,
                confidence=0.98,
                reason="schedule_master_match",
                source_id=schedule_master_entry.source_id,
                selected_category="ตารางแพทย์และเวลาทำการ",
                action_buttons=buttons,
                attachments=attachments,
                candidates=[_to_candidate_response(source_topic)] if source_topic is not None else [],
            )
            return _finalize_chat_response(req, session, query, response)
        if schedule_match is not None and not broad_schedule:
            answer_text = format_direct_answer(schedule_match)
            # Day-aware filtering
            day_filter = _detect_thai_day(query)
            if day_filter:
                filtered = _filter_answer_by_day(answer_text, day_filter)
                if filtered and any("-" in line for line in filtered.split("\n")):
                    answer_text = filtered
                else:
                    specialty = str((schedule_match.metadata or {}).get("topic") or schedule_match.question or "").strip()
                    answer_text = f"ไม่พบตารางออกตรวจของ {specialty} ในวัน{day_filter}ในระบบปัจจุบัน หากต้องการดูตารางทั้งสัปดาห์ กรุณาพิมพ์ ຈักษุแพทย์ (ตา) หรือชื่อเฉพาะทางที่ต้องการค่ะ"
            answer_text = _format_schedule_answer(schedule_match, day_filter=day_filter)
            attachments = _build_attachments_for_topic(schedule_match)
            buttons = _topic_follow_up_buttons(schedule_match)
            _remember(session, category="ตารางแพทย์และเวลาทำการ", topic=schedule_match, buttons=buttons)
            response = ChatResponse(
                route="answer",
                answer=answer_text,
                confidence=max(round(schedule_match.final_score, 4), 0.9),
                reason="schedule_specific_match",
                source_id=schedule_match.id,
                selected_category="ตารางแพทย์และเวลาทำการ",
                action_buttons=buttons,
                attachments=attachments,
                candidates=[_to_candidate_response(schedule_match)],
            )
            return _finalize_chat_response(req, session, query, response)

        schedule_q_norm = _normalize(query)
        if any(token in schedule_q_norm for token in ("หมอฟัน", "ทันตกรรม", "หมอทันตกรรม")):
            dental_candidates = _catalog_search("ทันตกรรม", category="คลินิกทันตกรรม", limit=3)
            if dental_candidates:
                dental_topic = dental_candidates[0]
                slot_answer = _build_followup_slot_answer(dental_topic, query) if FOLLOWUP_MODE == "slot_first" else None
                answer = slot_answer or format_direct_answer(dental_topic)
                buttons = _topic_follow_up_buttons(dental_topic)
                _remember(session, category="ตารางแพทย์และเวลาทำการ", topic=dental_topic, buttons=buttons)
                session.last_category = "ตารางแพทย์และเวลาทำการ"
                response = ChatResponse(
                    route="answer",
                    answer=answer,
                    confidence=max(round(dental_topic.final_score, 4), 0.88),
                    reason="schedule_alias_fallback_to_dental",
                    source_id=dental_topic.id,
                    selected_category="ตารางแพทย์และเวลาทำการ",
                    action_buttons=buttons,
                    candidates=[_to_candidate_response(dental_topic)],
                )
                return _finalize_chat_response(req, session, query, response)

        clarify_buttons = _child_topic_action_buttons("นัดหมายและตารางแพทย์", "ตารางแพทย์ออกตรวจ")
        _remember(session, category="ตารางแพทย์และเวลาทำการ", buttons=clarify_buttons)
        response = ChatResponse(
            route="clarify",
            answer="ต้องการทราบตารางแพทย์ของแผนกหรือเฉพาะทางใดคะ",
            confidence=0.96,
            reason="schedule_clarification",
            selected_category="ตารางแพทย์และเวลาทำการ",
            clarification_options=clarify_buttons,
            action_buttons=clarify_buttons,
            candidates=[],
        )
        return _finalize_chat_response(req, session, query, response)

    if session.last_topic_id and _is_follow_up_query(query):
        follow_topic = _answer_from_topic_follow_up(query, session)
        if follow_topic is not None:
            # Image follow-up: return attachments
            is_image_req = _is_image_follow_up(query)
            follow_attachments: list[Attachment] = []
            if is_image_req:
                follow_attachments = _build_attachments_for_topic(follow_topic)
                # Also check health-check topic
                raw_cat = str(follow_topic.category or "").strip()
                canonical_cat = _canonical_category_for_candidate(follow_topic, follow_topic.question) or raw_cat
                if canonical_cat in {"ตรวจสุขภาพรายบุคคล", "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย"} and not follow_attachments:
                    follow_attachments = _build_health_check_attachments()
                if follow_attachments:
                    img_answer = "มีรูปประกอบค่ะ กดดูรูปด้านล่างได้เลย"
                    buttons = _topic_follow_up_buttons(follow_topic)
                    follow_category = _resolved_response_category(follow_topic, query, session.last_category) or follow_topic.category
                    _remember(session, category=follow_category, topic=follow_topic, buttons=buttons)
                    response = ChatResponse(
                        route="answer",
                        answer=img_answer,
                        confidence=0.95,
                        reason="image_followup_with_attachment",
                        source_id=follow_topic.id,
                        selected_category=follow_category,
                        action_buttons=buttons,
                        attachments=follow_attachments,
                        candidates=[_to_candidate_response(follow_topic)],
                    )
                    return _finalize_chat_response(req, session, query, response)

            # KB-FIRST: If we have a direct match and mode is kb_exact, use direct answer
            slot_answer = _build_followup_slot_answer(follow_topic, query) if FOLLOWUP_MODE == "slot_first" else None
            if slot_answer:
                answer = slot_answer
                logger.info("Slot follow-up answer returned for ID: %s", follow_topic.id)
            elif ANSWER_MODE == "kb_exact":
                answer = format_direct_answer(follow_topic)
                logger.info("🎯 Session follow-up (kb_exact) → Returning direct answer for ID: %s", follow_topic.id)
            else:
                answer = _generate_answer(f"{session.last_topic_question} {query}", follow_topic, [follow_topic], use_llm=req.use_llm)

            buttons = _topic_follow_up_buttons(follow_topic)
            buttons.insert(0, session.last_topic_question or follow_topic.question)
            follow_category = _resolved_response_category(follow_topic, query, session.last_category) or follow_topic.category
            _remember(session, category=follow_category, topic=follow_topic, buttons=buttons)
            response = ChatResponse(
                route="answer",
                answer=answer,
                confidence=0.9,
                reason="session_follow_up_answer",
                source_id=follow_topic.id,
                selected_category=follow_category,
                action_buttons=buttons[:6],
                candidates=[_to_candidate_response(follow_topic)],
            )
            return _finalize_chat_response(req, session, query, response)

    category_browse = _category_browse_candidates(category_hint) if category_hint else []
    catalog_in_category = _catalog_search(query, category=category_hint, limit=req.top_k) if category_hint else []
    catalog_global = _catalog_search(query, category=None, limit=req.top_k)

    if catalog_in_category and catalog_global:
        if catalog_global[0].final_score > catalog_in_category[0].final_score + 0.15:
            # Overrule forced category if global search has a significantly better match
            best_catalog = catalog_global[0]
            category_hint = best_catalog.category
            catalog_in_category = []
        else:
            best_catalog = catalog_in_category[0]
    else:
        best_catalog = catalog_in_category[0] if catalog_in_category else (catalog_global[0] if catalog_global else None)

    if best_catalog is not None and _record_type(best_catalog) == "menu_node":
        canonical_menu_category = _resolved_response_category(best_catalog, query, category_hint) or best_catalog.category
        if typo_source:
            buttons = _category_action_buttons(canonical_menu_category, _category_browse_candidates(canonical_menu_category))
            _remember(session, category=canonical_menu_category, buttons=buttons)
            response = ChatResponse(
                route="answer",
                answer=build_category_overview(canonical_menu_category, buttons, corrected_from=typo_source),
                confidence=max(round(best_catalog.final_score, 4), 0.9),
                reason="typo_recovered_category_answer",
                source_id=best_catalog.id,
                selected_category=canonical_menu_category,
                action_buttons=buttons,
                candidates=[_to_candidate_response(best_catalog)],
            )
            return _finalize_chat_response(req, session, query, response)
        buttons = _category_action_buttons(canonical_menu_category, _category_browse_candidates(canonical_menu_category))
        _remember(session, category=canonical_menu_category, buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer=build_category_overview(canonical_menu_category, buttons, corrected_from=matched_alias if matched_alias and matched_alias != canonical_menu_category else None),
            confidence=max(round(best_catalog.final_score, 4), 0.9),
            reason="menu_tree_navigation",
            selected_category=canonical_menu_category,
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[_to_candidate_response(best_catalog)],
        )
        return _finalize_chat_response(req, session, query, response)

    if best_catalog is not None and _record_type(best_catalog) == "child_topic":
        if (
            typo_source
            and category_hint
            and _is_broad_category_query(query, category_hint)
            and not _looks_like_exact(query, best_catalog.question)
            and not _looks_like_exact(query, best_catalog.subcategory or "")
        ):
            buttons = _category_action_buttons(category_hint, category_browse)
            _remember(session, category=category_hint, buttons=buttons)
            response = ChatResponse(
                route="answer",
                answer=build_category_overview(category_hint, buttons, corrected_from=typo_source),
                confidence=max(round(best_catalog.final_score, 4), 0.9),
                reason="typo_recovered_category_answer",
                selected_category=category_hint,
                clarification_options=buttons,
                action_buttons=buttons,
                candidates=[_to_candidate_response(best_catalog)],
            )
            return _finalize_chat_response(req, session, query, response)
        canonical_child_category = _resolved_response_category(best_catalog, query, category_hint) or best_catalog.category
        child_topic_name = best_catalog.subcategory or best_catalog.question
        child_rows = _child_topic_leaf_rows(canonical_child_category, child_topic_name)
        scoped_leaf_candidates = []

        if canonical_child_category == "ตารางแพทย์และเวลาทำการ" and child_topic_name == "ตารางแพทย์ออกตรวจ":
            buttons = list(SCHEDULE_DEPARTMENT_MENU)
            _remember(session, category=canonical_child_category, buttons=buttons)
            response = ChatResponse(
                route="clarify",
                answer="ต้องการดูตารางแพทย์ของแผนกใดคะ",
                confidence=max(round(best_catalog.final_score, 4), 0.9),
                reason="schedule_department_menu_from_child_topic",
                selected_category=canonical_child_category,
                clarification_options=buttons,
                action_buttons=buttons,
                candidates=[_to_candidate_response(best_catalog)],
            )
            return _finalize_chat_response(req, session, query, response)
        
        leaf_query = query
        exact_child_query = _looks_like_exact(query, best_catalog.question) or _looks_like_exact(query, best_catalog.subcategory or "")
        
        # Vaccine child topic exact mapping - preserve exact KB child topics
        # Only apply inside the vaccine branch (วัคซีนและบริการผู้ป่วยนอก)
        if exact_child_query and canonical_child_category == "วัคซีนและบริการผู้ป่วยนอก":
            # Map exact child topics to preserve KB structure
            if child_topic_name == "วัคซีน HPV":
                leaf_query = "วัคซีนมะเร็งปากมดลูก"
            elif child_topic_name == "วัคซีนไข้หวัดใหญ่":
                leaf_query = "วัคซีนไข้หวัดใหญ่"
            elif child_topic_name == "วัคซีนไวรัสตับอักเสบบี":
                leaf_query = "วัคซีนไวรัสตับอักเสบบี"
            elif child_topic_name == "วัคซีนบาดทะยัก/พิษสุนัขบ้า":
                leaf_query = "วัคซีนบาดทะยัก/พิษสุนัขบ้า"
            
        if child_rows:
            if exact_child_query and len(child_rows) == 1:
                scoped_leaf_candidates = [_record_to_candidate(child_rows[0], 1.0)]
            else:
                for r in child_rows:
                    score = _catalog_match_score(leaf_query, r, canonical_child_category)
                    if score >= 0.22:
                        scoped_leaf_candidates.append(_record_to_candidate(r, score))
                scoped_leaf_candidates.sort(key=lambda c: c.final_score, reverse=True)
                scoped_leaf_candidates = scoped_leaf_candidates[:5]
        else:
            scoped_leaf_candidates = [
                candidate
                for candidate in _catalog_search(leaf_query, category=canonical_child_category, limit=5)
                if _record_type(candidate) in {"faq_leaf", "guidance", "schedule_specific"}
            ]
        
        if scoped_leaf_candidates and (exact_child_query or scoped_leaf_candidates[0].final_score >= 0.45):
            top_leaf = scoped_leaf_candidates[0]
            if _record_type(top_leaf) == "schedule_specific":
                answer = _format_schedule_answer(top_leaf, day_filter=_detect_thai_day(query))
                attachments = _attachments_for_answer_topic(top_leaf)
            elif ANSWER_MODE == "kb_exact":
                answer = format_direct_answer(top_leaf)
                attachments = _attachments_for_answer_topic(top_leaf)
            else:
                answer = _generate_answer(query, top_leaf, scoped_leaf_candidates[:4], use_llm=req.use_llm)
                attachments = _attachments_for_answer_topic(top_leaf)
            buttons = _topic_follow_up_buttons(top_leaf)
            _remember(session, category=canonical_child_category, topic=top_leaf, buttons=buttons)
            response = ChatResponse(
                route="answer",
                answer=answer,
                confidence=max(round(top_leaf.final_score, 4), 0.88),
                reason="child_topic_leaf_resolution",
                source_id=top_leaf.id,
                selected_category=canonical_child_category,
                action_buttons=buttons,
                attachments=attachments,
                candidates=[_to_candidate_response(c) for c in scoped_leaf_candidates[:3]],
            )
            return _finalize_chat_response(req, session, query, response)
        child_topic = best_catalog.subcategory or best_catalog.question
        buttons = _child_topic_action_buttons(best_catalog.category, child_topic)
        child_category = _resolved_response_category(best_catalog, query, category_hint) or best_catalog.category
        # FIX: Set last_topic_id to child topic ID so follow-up queries can bind to it
        _remember(session, category=child_category, topic=best_catalog, buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer=f"หัวข้อ {child_topic} มีรายการที่เกี่ยวข้องดังนี้\n" + "\n".join(f"- {item}" for item in buttons),
            confidence=max(round(best_catalog.final_score, 4), 0.88),
            reason="child_topic_navigation",
            selected_category=child_category,
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[_to_candidate_response(best_catalog)],
        )
        return _finalize_chat_response(req, session, query, response)

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

    if not category_hint and best_catalog is None and _looks_like_specific_unknown_query(query):
        response = ChatResponse(
            route="fallback",
            answer=GROUNDED_LLM_FALLBACK_TEXT,
            confidence=0.9,
            reason="unsupported_specific_query",
            action_buttons=list(MAIN_THEME_BUTTONS),
            candidates=[],
        )
        return _finalize_chat_response(req, session, query, response)

    if _is_probably_gibberish(query, matched=bool(category_hint), best_candidate=best_catalog):
        gibberish_answer = typo_recovery_text(typo_source) if typo_source else GROUNDED_LLM_FALLBACK_TEXT
        gibberish_reason = "unclear_input" if typo_source else "safe_unsupported_fallback"
        response = ChatResponse(
            route="fallback",
            answer=gibberish_answer,
            confidence=0.92,
            reason=gibberish_reason,
            action_buttons=GUIDE_ITEMS[:8],
            candidates=[],
        )
        return _finalize_chat_response(req, session, query, response)

    if _should_category_overview(query, category_hint, category_browse, matched_alias, best_catalog):
        buttons = _category_action_buttons(category_hint or "", category_browse)
        _remember(session, category=category_hint, buttons=buttons)
        route_value = "clarify" if _normalize(query) == "วัคซีน" else ("answer" if typo_source else "clarify")
        reason_value = "typo_recovered_category_answer" if typo_source else "category_overview"
        response = ChatResponse(
            route=route_value,
            answer=build_category_overview(category_hint or "", buttons, corrected_from=matched_alias if matched_alias and matched_alias != category_hint else None),
            confidence=round(max(alias_score, 0.76), 4),
            reason=reason_value,
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
        answer_category = _resolved_response_category(best_catalog, query, category_hint) or best_catalog.category
        # KB-FIRST: If we have a direct match and mode is kb_exact, use direct answer
        if _record_type(best_catalog) == "schedule_specific":
            answer = _format_schedule_answer(best_catalog, day_filter=_detect_thai_day(query))
        elif ANSWER_MODE == "kb_exact" and best_catalog:
            answer = format_direct_answer(best_catalog)
            logger.info("🎯 Direct catalog match (kb_exact) → Returning direct answer for ID: %s", best_catalog.id)
        else:
            answer = _generate_answer(query, best_catalog, [best_catalog], use_llm=req.use_llm)
        
        buttons = _topic_follow_up_buttons(best_catalog)
        _remember(session, category=answer_category, topic=best_catalog, buttons=buttons)
        response = ChatResponse(
            route="answer",
            answer=answer,
            confidence=round(best_catalog.final_score, 4),
            reason="direct_catalog_match",
            source_id=best_catalog.id,
            selected_category=answer_category,
            action_buttons=buttons,
            attachments=_attachments_for_answer_topic(best_catalog),
            candidates=[_to_candidate_response(best_catalog)],
        )
        append_audit_event(AUDIT_LOG_PATH, {"event_type": "chat", "question": query, "route": response.route, "reason": response.reason, "source_id": response.source_id})
        latency = round(time.time() - t_start, 3)
        logger.info("✅ /chat done route=%s reason=%s latency=%.3fs", response.route, response.reason, latency)
        return _finalize_chat_response(req, session, query, response)

    retrieved: list[RetrievalCandidate] = []
    if state.retriever is not None:
        try:
            retrieved = state.retriever.search(query=query, top_k=req.top_k, category=category_hint)
            if not retrieved and category_hint:
                retrieved = state.retriever.search(query=query, top_k=req.top_k, category=None)
        except Exception as exc:
            logger.warning("Retriever search failed for query '%s': %s", query[:80], exc)
            retrieved = []

    merged = _merge_candidates(catalog_in_category, catalog_global, retrieved, limit=req.top_k)
    reranked = state.reranker.rerank(query, merged)
    decision = decide(query, reranked)

    if decision.action == "fallback" and category_hint:
        buttons = _category_action_buttons(category_hint, category_browse)
        _remember(session, category=category_hint, buttons=buttons)
        response = ChatResponse(
            route="clarify",
            answer=build_category_overview(category_hint, buttons, corrected_from=matched_alias if matched_alias and matched_alias != category_hint else None),
            confidence=round(max(alias_score, 0.60), 4),
            reason="fallback_to_category_overview",
            selected_category=category_hint,
            clarification_options=buttons,
            action_buttons=buttons,
            candidates=[_to_candidate_response(c) for c in category_browse[:5]],
        )
        return _finalize_chat_response(req, session, query, response)

    if decision.action == "fallback":
        fallback_answer = GROUNDED_LLM_FALLBACK_TEXT if not reranked and not category_hint else fallback_text()
        response = ChatResponse(
            route="fallback",
            answer=fallback_answer,
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
        answer=answer,
        confidence=decision.confidence,
        reason=decision.reason,
        warnings=decision.warnings,
        source_id=top.id,
        selected_category=top.category,
        action_buttons=buttons,
        attachments=_attachments_for_answer_topic(top),
        candidates=[_to_candidate_response(c) for c in reranked[:5]],
    )
    latency = round(time.time() - t_start, 3)
    logger.info("✅ /chat done route=%s reason=%s latency=%.3fs", response.route, response.reason, latency)
    return _finalize_chat_response(req, session, query, response)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        return _chat_impl(req)
    except Exception as exc:
        logger.exception("Unhandled /chat error for session=%s: %s", req.session_id[:12], exc)
        session = state.get_session(req.session_id)
        response = ChatResponse(
            route="fallback",
            answer=GROUNDED_LLM_FALLBACK_TEXT,
            confidence=0.0,
            reason="chat_unhandled_exception",
            action_buttons=list(MAIN_THEME_BUTTONS),
        )
        return _finalize_chat_response(req, session, req.question or req.message or "", response)


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


@app.post("/chat/reset-session")
def reset_session(body: dict) -> dict[str, Any]:
    """Explicit session reset endpoint for frontend goHome actions.

    Accepts JSON body: {"session_id": "session-..."}
    """
    session_id = str(body.get("session_id") or "")
    if not session_id:
        return {"ok": False, "error": "missing session_id"}
    session = state.get_session(session_id)
    session.reset_context()
    return {"ok": True, "message": "session reset", "action_buttons": list(MAIN_THEME_BUTTONS), "welcome": WELCOME_MESSAGE}
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


# ── Static Asset Endpoints (safe file serving) ───────────────────────────
@app.get("/assets/schedule/{filename}")
def serve_schedule_asset(filename: str) -> FileResponse:
    """Serve schedule images from the schedule image directory."""
    root = SCHEDULE_IMAGE_DIR
    if not root.exists():
        raise HTTPException(status_code=404, detail="Schedule image directory not found")
    file_path = (root / filename).resolve()
    # Security: must stay inside root
    try:
        file_path.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if file_path.suffix.lower() not in ALLOWED_ASSET_EXTENSIONS:
        raise HTTPException(status_code=403, detail="File type not allowed")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return FileResponse(str(file_path))


@app.get("/assets/health-check/{filename}")
def serve_health_check_asset(filename: str) -> FileResponse:
    """Serve health check images from the health check image directory."""
    root = HEALTH_CHECK_IMAGE_DIR
    if not root.exists():
        raise HTTPException(status_code=404, detail="Health check image directory not found")
    file_path = (root / filename).resolve()
    try:
        file_path.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if file_path.suffix.lower() not in ALLOWED_ASSET_EXTENSIONS:
        raise HTTPException(status_code=403, detail="File type not allowed")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return FileResponse(str(file_path))
