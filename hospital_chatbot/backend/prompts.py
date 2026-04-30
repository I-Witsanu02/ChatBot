"""Prompt and response-text helpers for the hospital chatbot."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from typing import Iterable

from .retrieval import RetrievalCandidate

GUIDE_ITEMS = [
    "นัดหมายและตารางแพทย์",
    "วัคซีนและบริการผู้ป่วยนอก",
    "เวชระเบียน สิทธิ และค่าใช้จ่าย",
    "ตรวจสุขภาพและใบรับรองแพทย์",
    "ติดต่อหน่วยงานเฉพาะและสมัครงาน",
]

CATEGORY_LABELS = {item: item for item in GUIDE_ITEMS}

WELCOME_MESSAGE = (
    "สวัสดีค่ะ ดิฉันน้องฟ้ามุ่ย AI ผู้ช่วยข้อมูลบริการของโรงพยาบาลมหาวิทยาลัยพะเยาค่ะ\n\n"
    "สามารถเลือกจากเมนูหลักด้านล่าง หรือพิมพ์คำถามสั้น ๆ ได้เลย เช่น ตารางแพทย์ วัคซีน "
    "สิทธิการรักษา ตรวจสุขภาพ หรือใบรับรองแพทย์ค่ะ"
)

SYSTEM_PROMPT = (
    "คุณคือน้องฟ้ามุ่ย AI ผู้ช่วยข้อมูลบริการของโรงพยาบาลมหาวิทยาลัยพะเยา\n"
    "ตอบจากข้อมูลที่ระบบให้มาเท่านั้น ห้ามแต่งข้อมูลใหม่ ห้ามสรุปเกินจากหลักฐาน\n"
    "ถ้าพบคำตอบจาก KB อย่างมั่นใจ ให้ใช้ข้อความข้อเท็จจริงจาก KB เป็นหลัก\n"
    "โมเดลช่วยได้เฉพาะการทำความเข้าใจคำถาม การจัดหมวด การถามกลับ และการตอบอย่างสุภาพ\n"
    "ถ้าคำถามกว้างเกินไป โดยเฉพาะเรื่องตารางแพทย์ ให้ถามกลับเพื่อระบุแผนกหรือเฉพาะทางก่อน"
)


def fallback_text() -> str:
    return (
        "ขออภัยค่ะ ขณะนี้ระบบยังไม่พบข้อมูลที่ตรงกับคำถามนี้ในฐานความรู้ที่ยืนยันแล้ว "
        "แนะนำให้ติดต่อประชาสัมพันธ์โรงพยาบาล โทร 054-466666 ต่อ 7221 หรือ 7222 ค่ะ"
    )


def unclear_input_text() -> str:
    return "ขออภัยค่ะ ระบบยังไม่เข้าใจคำถามชัดเจน ลองเลือกหัวข้อจากเมนูหลักหรือพิมพ์คำสำคัญอีกครั้งได้ค่ะ"


def typo_recovery_text(normalized_guess: str | None = None) -> str:
    if normalized_guess:
        return f"ระบบเข้าใจว่าคุณอาจหมายถึง '{normalized_guess}' ค่ะ ลองเลือกหัวข้อที่ใกล้เคียงจากเมนูด้านล่างได้เลย"
    return "ระบบพบว่าคำถามอาจมีการพิมพ์คลาดเคลื่อนค่ะ ลองเลือกหัวข้อจากเมนูด้านล่างหรือพิมพ์ใหม่อีกครั้งได้ค่ะ"


def ambiguous_term_text(query: str, categories: list[str]) -> str:
    lines = [f"คำว่า '{query}' อาจหมายถึงได้หลายหัวข้อค่ะ กรุณาเลือกหมวดที่ต้องการต่อไปนี้"]
    for category in categories[:6]:
        lines.append(f"- {display_category_name(category)}")
    return "\n".join(lines)


def emergency_text() -> str:
    return "หากมีอาการฉุกเฉิน โปรดติดต่อ 1669 หรือแผนกฉุกเฉินของโรงพยาบาลทันทีค่ะ"


def handoff_waiting_text(ticket_id: int | None) -> str:
    suffix = f" (เลขเคส {ticket_id})" if ticket_id else ""
    return f"ระบบได้ส่งเรื่องให้เจ้าหน้าที่ตรวจสอบเพิ่มเติมแล้วค่ะ{suffix} เมื่อมีการตอบกลับ ข้อความจะแสดงในแชตนี้ทันทีค่ะ"


def _is_placeholder_subcategory(value: str | None) -> bool:
    text = str(value or "").strip()
    return (not text) or text.isdigit()


def _shorten(text: str, max_len: int = 72) -> str:
    text = str(text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _format_last_updated(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    for fmt in (None, "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.fromisoformat(raw) if fmt is None else datetime.strptime(raw, fmt)
            return dt.strftime("%d/%m/%Y %H:%M") + " น."
        except Exception:
            continue
    return raw


def _listify(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1]
        items = [part.strip().strip("'\"") for part in inner.split(",")]
        return [item for item in items if item]
    return [item.strip() for item in text.split("|") if item.strip()]


def display_category_name(category: str | None) -> str:
    return CATEGORY_LABELS.get(str(category or "").strip(), str(category or "").strip())


def build_clarification_options(candidates: Iterable[RetrievalCandidate]) -> list[str]:
    ordered: OrderedDict[str, None] = OrderedDict()
    for cand in candidates:
        label = _shorten(cand.question or cand.subcategory or cand.category, 64)
        if label:
            ordered[label] = None
        if len(ordered) >= 8:
            break
    return list(ordered.keys())


def build_category_overview(category: str, items: list[str], corrected_from: str | None = None) -> str:
    title = display_category_name(category)
    lines: list[str] = []
    if corrected_from and corrected_from.strip() and corrected_from.strip() != title:
        lines.append(f"ระบบตีความคำถามนี้อยู่ในหมวด: {title}")
    lines.append(f"หมวด {title} มีหัวข้อย่อยที่เลือกได้ดังนี้")
    for item in items[:8]:
        lines.append(f"- {item}")
    lines.append("กรุณาเลือกหัวข้อที่ต้องการ หรือพิมพ์รายละเอียดเพิ่มได้เลยค่ะ")
    return "\n".join(lines)


def build_clarification_text(query: str, candidates: Iterable[RetrievalCandidate]) -> str:
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    for cand in candidates:
        category = display_category_name((cand.category or "").strip() or "หมวดอื่น ๆ")
        grouped.setdefault(category, [])
        label = _shorten(cand.question or cand.subcategory or category, 72)
        if label and label not in grouped[category]:
            grouped[category].append(label)
        if len(grouped) >= 4 and all(len(v) >= 2 for v in grouped.values()):
            break
    if not grouped:
        return "รบกวนระบุรายละเอียดเพิ่มอีกนิด เช่น ชื่อแผนก บริการ หรือหัวข้อที่ต้องการสอบถามค่ะ"
    lines = [
        f"เพื่อให้ตอบได้ตรงขึ้นสำหรับคำถาม '{query}' กรุณาเลือกหัวข้อที่ใกล้เคียงดังนี้",
    ]
    for category, questions in list(grouped.items())[:4]:
        lines.append(f"- {category}")
        for question in questions[:3]:
            lines.append(f"  • {question}")
    return "\n".join(lines)


def format_direct_answer(top: RetrievalCandidate) -> str:
    meta = dict(top.metadata or {})
    parts = [str(top.answer or "").strip()]

    note = str(meta.get("note") or meta.get("notes") or top.notes or "").strip()
    if note:
        parts.append(f"หมายเหตุ: {note}")

    if top.department:
        parts.append(f"หน่วยงาน: {top.department}")

    contact = str(meta.get("followup_contact") or top.contact or "").strip()
    if contact:
        parts.append(f"ติดต่อ: {contact}")

    hours = str(meta.get("followup_hours") or "").strip()
    if hours:
        parts.append(f"เวลาให้บริการ: {hours}")

    price = str(meta.get("followup_price") or "").strip()
    if price:
        parts.append(f"ค่าใช้จ่าย: {price}")

    walkin = str(meta.get("followup_walkin") or "").strip()
    if walkin:
        parts.append(f"การเข้ารับบริการ: {walkin}")

    links = _listify(meta.get("followup_link"))
    if links:
        parts.append("ลิงก์ที่เกี่ยวข้อง: " + ", ".join(links[:3]))

    images: list[str] = []
    if images:
        parts.append("ไฟล์แนบ/รูปประกอบ: " + ", ".join(images[:3]))

    formatted_updated = _format_last_updated(top.last_updated_at)
    if formatted_updated:
        parts.append(f"อัปเดตล่าสุด: {formatted_updated}")
    if top.stale:
        parts.append("หมายเหตุเพิ่มเติม: ข้อมูลนี้อาจมีการเปลี่ยนแปลง ควรยืนยันกับเจ้าหน้าที่อีกครั้งค่ะ")
    return "\n".join(part for part in parts if part)


def build_category_not_found_text(query: str, category: str, items: list[str]) -> str:
    title = display_category_name(category)
    lines = [f"ขออภัยค่ะ ยังไม่พบหัวข้อ '{query}' ในหมวด {title} จากฐานความรู้ปัจจุบัน"]
    if items:
        lines.append(f"หมวด {title} มีหัวข้อที่เกี่ยวข้องดังนี้")
        for item in items[:8]:
            lines.append(f"- {item}")
        lines.append("กรุณาเลือกหัวข้อที่ใกล้เคียง หรือพิมพ์รายละเอียดเพิ่มได้ค่ะ")
    else:
        lines.append("หากต้องการยืนยันข้อมูลเพิ่มเติม แนะนำให้ติดต่อเจ้าหน้าที่ของโรงพยาบาลค่ะ")
    return "\n".join(lines)


def build_followup_hint_text(category: str | None, topic: str | None) -> str:
    title = display_category_name(category)
    if topic and title:
        return f"หากต้องการถามต่อเกี่ยวกับ {topic} สามารถถามต่อได้ เช่น ราคาเท่าไหร่ ติดต่อที่ไหน เปิดวันไหน เข้าได้เลยไหม มีรูปไหม หรือมีลิงก์ไหมค่ะ"
    if title:
        return f"สามารถถามต่อในหมวด {title} ได้ หรือกดเลือกหัวข้อจากปุ่มด้านล่างได้เลยค่ะ"
    return "สามารถพิมพ์รายละเอียดเพิ่ม หรือเลือกหัวข้อจากปุ่มด้านล่างได้เลยค่ะ"


def build_llm_messages(question: str, top: RetrievalCandidate, candidates: list[RetrievalCandidate]) -> list[dict[str, str]]:
    context_lines = []
    for idx, cand in enumerate(candidates, start=1):
        context_lines.append(
            f"[{idx}] หมวด: {cand.category} | หัวข้อ: {cand.subcategory or '-'} | คำถาม: {cand.question} | คำตอบ: {cand.answer}"
        )
    context = "\n".join(context_lines)
    user = f"คำถามผู้ใช้: {question}\n\nบริบทอ้างอิง:\n{context}\n\nให้ตอบจากบริบทนี้เท่านั้น"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
def build_grounded_llm_messages(question: str, top: RetrievalCandidate, candidates: list[RetrievalCandidate]) -> list[dict[str, str]]:
    context_lines: list[str] = []
    for idx, cand in enumerate(candidates[:3], start=1):
        context_lines.append(f"[{idx}] source_id: {cand.id}")
        context_lines.append(f"[{idx}] category: {cand.category}")
        context_lines.append(f"[{idx}] title: {cand.question or cand.subcategory or '-'}")
        context_lines.append(f"[{idx}] answer: {cand.answer}")
        if cand.notes:
            context_lines.append(f"[{idx}] notes: {cand.notes}")
        if cand.department:
            context_lines.append(f"[{idx}] department: {cand.department}")
        if cand.contact:
            context_lines.append(f"[{idx}] contact: {cand.contact}")
    context = "\n".join(context_lines).strip()
    grounded_system = (
        "คุณคือชั้นช่วยเรียบเรียงคำตอบของ UPH Hospital Chatbot\n"
        "ให้ใช้เฉพาะข้อมูลใน KB_CONTEXT เท่านั้น\n"
        "ห้ามใช้ความรู้ทั่วไป\n"
        "ห้ามแต่งข้อมูลโรงพยาบาลเพิ่ม\n"
        "ห้ามเพิ่มเบอร์โทร ราคา วันที่ เวลา URL หน่วยงาน หรือบริการ ที่ไม่มีอยู่ใน KB_CONTEXT\n"
        "ห้ามวินิจฉัยโรค\n"
        "ห้ามแนะนำยา หรือการรักษา\n"
        "ถ้า KB_CONTEXT ว่างหรือข้อมูลไม่พอ ให้ตอบ exactly ว่า: ไม่พบข้อมูลนี้ในระบบปัจจุบัน กรุณาติดต่อโรงพยาบาลมหาวิทยาลัยพะเยาเพื่อสอบถามเพิ่มเติม\n"
        "ตอบสั้น กระชับ ภาษาไทย และยึดตาม KB_CONTEXT เท่านั้น"
    )
    user = (
        f"USER_QUESTION:\n{question}\n\n"
        f"PRIMARY_SELECTED_TITLE:\n{top.question or top.subcategory or '-'}\n\n"
        f"KB_CONTEXT:\n{context if context else '(empty)'}\n\n"
        "ให้ตอบเป็นข้อความภาษาไทยสั้น ๆ เพียงคำตอบเดียว"
    )
    return [{"role": "system", "content": grounded_system}, {"role": "user", "content": user}]
