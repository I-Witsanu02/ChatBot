"""Prompt and response-text helpers for the hospital chatbot."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from typing import Iterable

from .retrieval import RetrievalCandidate

GUIDE_ITEMS = [
    "การจัดการนัดหมาย",
    "คลินิกทันตกรรม",
    "ศูนย์ไตเทียม",
    "สูตินรีเวช",
    "ประเมินค่าใช้จ่ายทั่วไป",
    "วัคซีน",
    "สวัสดิการวัคซีนนักศึกษา",
    "ค่าใช้จ่าย",
    "กลุ่มงานบุคคล",
    "ตารางแพทย์และเวลาทำการ",
    "ตรวจสุขภาพรายบุคคล",
    "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย",
    "การขอเอกสารทางการแพทย์",
]

CATEGORY_LABELS = {
    "การจัดการนัดหมาย": "การจัดการนัดหมาย",
    "คลินิกทันตกรรม": "คลินิกทันตกรรม",
    "ศูนย์ไตเทียม": "ศูนย์ไตเทียม",
    "สูตินรีเวช": "สูตินรีเวช",
    "ประเมินค่าใช้จ่ายทั่วไป": "ประเมินค่าใช้จ่ายทั่วไป",
    "วัคซีน": "วัคซีน",
    "สวัสดิการวัคซีนนักศึกษา": "สวัสดิการวัคซีนนักศึกษา",
    "ค่าใช้จ่าย": "ค่าใช้จ่าย",
    "ธนาคารเลือดและบริจาคเลือด": "ธนาคารเลือดและบริจาคเลือด",
    "กลุ่มงานบุคคล": "กลุ่มงานบุคคล",
    "ตารางแพทย์และเวลาทำการ": "ตารางแพทย์และเวลาทำการ",
    "ตรวจสุขภาพรายบุคคล": "ตรวจสุขภาพรายบุคคล",
    "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่า": "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย",
    "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย": "ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย",
    "การขอเอกสารทางการแพทย์": "การขอเอกสารทางการแพทย์",
}

WELCOME_MESSAGE = (
    "สวัสดีครับ/ค่ะ ระบบนี้ให้ข้อมูลบริการเบื้องต้นของโรงพยาบาลมหาวิทยาลัยพะเยา\n"
    "คุณสามารถสอบถามได้ เช่น นัดหมาย, ตารางแพทย์, ค่าใช้จ่าย, วัคซีน, ตรวจสุขภาพ, เอกสารทางการแพทย์ และการติดต่อแผนกครับ/ค่ะ\n"
    "ตัวอย่างที่ถามได้: เลื่อนนัด, ตารางออกตรวจ, ราคาวัคซีน, ตรวจสุขภาพรายบุคคล, ขอเอกสารแพทย์\n\n"
    "หมวดบริการที่ระบบตอบได้เบื้องต้น:\n"
    "- การจัดการนัดหมาย\n"
    "- คลินิกทันตกรรม\n"
    "- ศูนย์ไตเทียม\n"
    "- สูตินรีเวช\n"
    "- ประเมินค่าใช้จ่ายทั่วไป\n"
    "- วัคซีน\n"
    "- สวัสดิการวัคซีนนักศึกษา\n"
    "- ธนาคารเลือดและบริจาคเลือด\n"
    "- กลุ่มงานบุคคล\n"
    "- ตารางแพทย์และเวลาทำการ\n"
    "- ตรวจสุขภาพรายบุคคล\n"
    "- ตรวจสุขภาพองค์กรและสิทธิเบิกจ่าย\n"
    "- การขอเอกสารทางการแพทย์\n\n"
    "คุณสามารถกดปุ่มหมวดด้านบน หรือพิมพ์คำสั้น ๆ เช่น เลื่อนนัด, ตารางแพทย์, วัคซีน, สิทธิการรักษา, บริจาคเลือด, ทันตกรรม ได้เลยครับ/ค่ะ"
)

SYSTEM_PROMPT = (
    "คุณคือผู้ช่วยข้อมูลบริการของโรงพยาบาลมหาวิทยาลัยพะเยา\n"
    "ตอบเฉพาะจากบริบทที่ระบบให้เท่านั้น\n"
    "ห้ามแต่งข้อมูล ห้ามวินิจฉัยโรค ห้ามสั่งยา\n"
    "ถ้าถามกว้าง ให้ช่วยไกด์หมวดและหัวข้อย่อยก่อน\n"
    "ถ้าถามตรงหัวข้อ ให้สรุปคำตอบให้อ่านง่าย แต่ต้องยึดบริบทเดิม\n"
    "ถ้าไม่พบหัวข้อในฐานข้อมูล ให้บอกตรง ๆ ว่ายังไม่พบในฐานข้อมูลปัจจุบันและเสนอหัวข้อใกล้เคียง\n"
    "ถ้าข้อมูลไม่พอ ให้แนะนำติดต่อเจ้าหน้าที่อย่างสุภาพ"
)


def fallback_text() -> str:
    return (
        "ขออภัยครับ/ค่ะ ขณะนี้ยังไม่พบข้อมูลที่ชัดเจนในระบบเบื้องต้น "
        "แนะนำติดต่อประชาสัมพันธ์โรงพยาบาล โทร 054-466666 ต่อ 7221 หรือ 7222 ครับ/ค่ะ"
    )


def unclear_input_text() -> str:
    return (
        "ขออภัยครับ/ค่ะ ระบบอ่านคำถามได้ไม่ชัดเจนหรืออาจสะกดผิด กรุณาพิมพ์ใหม่อีกครั้ง หรือเลือกหมวดบริการด้านบน เช่น "
        "การจัดการนัดหมาย, ตารางแพทย์และเวลาทำการ, วัคซีน, ศูนย์ไตเทียม, คลินิกทันตกรรม, สิทธิการรักษา หรือธนาคารเลือดและบริจาคเลือด ครับ/ค่ะ"
    )




def typo_recovery_text(normalized_guess: str | None = None) -> str:
    if normalized_guess:
        return f"ระบบพยายามตีความคำถามที่สะกดคลาดเคลื่อนเป็น '{normalized_guess}' แล้ว แต่ยังต้องการรายละเอียดเพิ่ม กรุณาเลือกหมวดหรือพิมพ์คำถามใหม่ให้ชัดขึ้นครับ/ค่ะ"
    return "ระบบพบว่าคำถามอาจสะกดคลาดเคลื่อน กรุณาพิมพ์ใหม่ให้ชัดขึ้น หรือเลือกหมวดบริการด้านบนครับ/ค่ะ"


def ambiguous_term_text(query: str, categories: list[str]) -> str:
    lines = [f"คำว่า '{query}' ยังไม่ชัดพอ กรุณาเลือกหัวข้อที่ใกล้เคียงที่สุดครับ/ค่ะ"]
    for category in categories[:6]:
        lines.append(f"- {display_category_name(category)}")
    return "\n".join(lines)

def emergency_text() -> str:
    return "หากมีอาการฉุกเฉิน โปรดติดต่อ 1669 หรือแผนกฉุกเฉินของโรงพยาบาลทันทีครับ/ค่ะ"


def handoff_waiting_text(ticket_id: int | None) -> str:
    suffix = f" (หมายเลขเคส {ticket_id})" if ticket_id else ""
    return f"ระบบได้บันทึกคำถามนี้เพื่อให้เจ้าหน้าที่ตรวจสอบเพิ่มเติมแล้ว{suffix} หากมีการตอบกลับจากเจ้าหน้าที่ จะแสดงในแชทนี้เมื่อพร้อมครับ/ค่ะ"


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


def display_category_name(category: str | None) -> str:
    return CATEGORY_LABELS.get(str(category or "").strip(), str(category or "").strip())


def build_clarification_options(candidates: Iterable[RetrievalCandidate]) -> list[str]:
    ordered: OrderedDict[str, None] = OrderedDict()
    for cand in candidates:
        q = _shorten(cand.question or cand.subcategory or cand.category, 64)
        if q:
            ordered[q] = None
        if len(ordered) >= 8:
            break
    return list(ordered.keys())


def build_category_overview(category: str, items: list[str], corrected_from: str | None = None) -> str:
    title = display_category_name(category)
    lines: list[str] = []
    if corrected_from and corrected_from.strip() and corrected_from.strip() != title:
        lines.append(f"ระบบตีความคำถามของคุณเป็นหมวด: {title}")
    lines.append(f"หมวด {title} มีหัวข้อที่สอบถามได้ เช่น")
    for item in items[:8]:
        lines.append(f"- {item}")
    lines.append("กรุณาเลือกหัวข้อที่ใกล้ที่สุด หรือพิมพ์รายละเอียดเพิ่มได้เลยครับ/ค่ะ")
    return "\n".join(lines)


def build_clarification_text(query: str, candidates: Iterable[RetrievalCandidate]) -> str:
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    for cand in candidates:
        cat = display_category_name((cand.category or "").strip() or "หมวดอื่น ๆ")
        grouped.setdefault(cat, [])
        q = _shorten(cand.question or cand.subcategory or cat, 72)
        if q and q not in grouped[cat]:
            grouped[cat].append(q)
        if len(grouped) >= 4 and all(len(v) >= 2 for v in grouped.values()):
            break
    if not grouped:
        return "รบกวนระบุรายละเอียดเพิ่มเติม เช่น ชื่อแผนก บริการ หรือหัวข้อที่ต้องการสอบถามครับ/ค่ะ"
    lines = [
        "เพื่อให้ตอบได้แม่นยำขึ้น กรุณาเลือกหัวข้อที่ต้องการสอบถามเพิ่มเติมครับ/ค่ะ",
        f"คำถามที่คุณพิมพ์คือ: {query}",
    ]
    for category, questions in list(grouped.items())[:4]:
        lines.append(f"- {category}")
        for q in questions[:3]:
            lines.append(f"  • {q}")
    return "\n".join(lines)


def format_direct_answer(top: RetrievalCandidate) -> str:
    parts = [top.answer.strip()]
    if top.notes:
        parts.append(f"หมายเหตุ: {top.notes}")
    if top.department:
        parts.append(f"หน่วยงาน: {top.department}")
    if top.contact:
        parts.append(f"ติดต่อ: {top.contact}")
    formatted_updated = _format_last_updated(top.last_updated_at)
    if formatted_updated:
        parts.append(f"อัปเดตล่าสุด: {formatted_updated}")
    if top.stale:
        parts.append("หมายเหตุเพิ่มเติม: ข้อมูลนี้อาจมีการเปลี่ยนแปลง ควรยืนยันกับเจ้าหน้าที่อีกครั้ง")
    return "\n".join(parts)


def build_category_not_found_text(query: str, category: str, items: list[str]) -> str:
    title = display_category_name(category)
    lines = [
        f"ขออภัยครับ/ค่ะ ขณะนี้ยังไม่พบหัวข้อ '{query}' ในหมวด {title} จากฐานข้อมูลปัจจุบัน",
    ]
    if items:
        lines.append(f"หมวด {title} มีหัวข้อที่สอบถามได้ เช่น")
        for item in items[:8]:
            lines.append(f"- {item}")
        lines.append("กรุณาเลือกหัวข้อที่ใกล้ที่สุด หรือพิมพ์รายละเอียดเพิ่มได้เลยครับ/ค่ะ")
    else:
        lines.append("แนะนำติดต่อประชาสัมพันธ์โรงพยาบาลเพื่อยืนยันข้อมูลเพิ่มเติมครับ/ค่ะ")
    return "\n".join(lines)


def build_followup_hint_text(category: str | None, topic: str | None) -> str:
    title = display_category_name(category)
    if topic and title:
        return f"หากต้องการถามต่อเกี่ยวกับ {topic} คุณสามารถถามต่อได้ เช่น ราคาเท่าไหร่, ติดต่อที่ไหน, เปิดวันไหน หรือเข้าได้เลยไหม"
    if title:
        return f"คุณสามารถถามต่อในหมวด {title} ได้ เช่น ราคาเท่าไหร่, ติดต่อที่ไหน, เปิดวันไหน หรือกลับไปดูหัวข้อในหมวด"
    return "คุณสามารถถามต่อได้โดยพิมพ์รายละเอียดเพิ่ม หรือเลือกหัวข้อจากปุ่มด้านบนครับ/ค่ะ"


def build_llm_messages(question: str, top: RetrievalCandidate, candidates: list[RetrievalCandidate]) -> list[dict[str, str]]:
    context_lines = []
    for idx, cand in enumerate(candidates, start=1):
        context_lines.append(
            f"[{idx}] หมวด: {cand.category} | หัวข้อ: {cand.subcategory or '-'} | คำถาม: {cand.question} | คำตอบ: {cand.answer}"
        )
    context = "\n".join(context_lines)
    user = f"คำถามผู้ใช้: {question}\n\nบริบท:\n{context}\n\nให้ตอบจากบริบทเท่านั้น"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
