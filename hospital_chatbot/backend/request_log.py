"""SQLite-backed request logging and lightweight analytics for chatbot traffic."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .versioning import now_bangkok_iso


def init_request_log_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                session_id TEXT,
                question TEXT NOT NULL,
                route TEXT,
                category TEXT,
                confidence REAL,
                reason TEXT,
                source_id TEXT,
                warnings_json TEXT,
                handoff_required INTEGER NOT NULL DEFAULT 0,
                handoff_ticket_id INTEGER,
                meta_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_request_logs_ts ON request_logs(ts DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_request_logs_category ON request_logs(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_request_logs_route ON request_logs(route)")
        conn.commit()


def log_chat_request(
    db_path: Path,
    *,
    session_id: str,
    question: str,
    route: str,
    category: str | None,
    confidence: float,
    reason: str,
    source_id: str | None,
    warnings: list[str] | None = None,
    handoff_required: bool = False,
    handoff_ticket_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    init_request_log_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO request_logs (
                ts, session_id, question, route, category, confidence, reason,
                source_id, warnings_json, handoff_required, handoff_ticket_id, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_bangkok_iso(),
                session_id,
                question,
                route,
                category,
                float(confidence),
                reason,
                source_id,
                json.dumps(warnings or [], ensure_ascii=False),
                1 if handoff_required else 0,
                handoff_ticket_id,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_request_logs(db_path: Path, *, limit: int = 200, category: str | None = None, route: str | None = None) -> list[dict[str, Any]]:
    init_request_log_db(db_path)
    sql = "SELECT id, ts, session_id, question, route, category, confidence, reason, source_id, warnings_json, handoff_required, handoff_ticket_id, meta_json FROM request_logs"
    clauses: list[str] = []
    params: list[Any] = []
    if category:
        clauses.append("category = ?")
        params.append(category)
    if route:
        clauses.append("route = ?")
        params.append(route)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for row in rows:
        out.append(
            {
                "id": row[0],
                "ts": row[1],
                "session_id": row[2],
                "question": row[3],
                "route": row[4],
                "category": row[5],
                "confidence": row[6],
                "reason": row[7],
                "source_id": row[8],
                "warnings": json.loads(row[9] or "[]"),
                "handoff_required": bool(row[10]),
                "handoff_ticket_id": row[11],
                "meta": json.loads(row[12] or "{}"),
            }
        )
    return out


def analytics_summary(db_path: Path) -> dict[str, Any]:
    init_request_log_db(db_path)
    with sqlite3.connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM request_logs").fetchone()[0]
        by_route = conn.execute("SELECT COALESCE(route, ''), COUNT(*) FROM request_logs GROUP BY route ORDER BY COUNT(*) DESC").fetchall()
        by_category = conn.execute("SELECT COALESCE(category, ''), COUNT(*) FROM request_logs GROUP BY category ORDER BY COUNT(*) DESC LIMIT 20").fetchall()
        low_conf = conn.execute("SELECT COUNT(*) FROM request_logs WHERE confidence < 0.60").fetchone()[0]
        handoff = conn.execute("SELECT COUNT(*) FROM request_logs WHERE handoff_required = 1").fetchone()[0]
    return {
        "total_requests": int(total),
        "low_confidence_requests": int(low_conf),
        "handoff_requests": int(handoff),
        "by_route": [{"route": r or "", "count": int(c)} for r, c in by_route],
        "by_category": [{"category": c or "", "count": int(n)} for c, n in by_category],
    }
