"""Human-in-the-loop handoff queue backed by SQLite.

V19 adds:
- ticket claiming for live takeover
- streaming-friendly live message table for admin ↔ user handoff replies
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .request_log import init_request_log_db
from .versioning import now_bangkok_iso


def _init_handoff_tables(db_path: Path) -> None:
    init_request_log_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS handoff_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                session_id TEXT,
                question TEXT NOT NULL,
                category TEXT,
                confidence REAL,
                route TEXT,
                reason TEXT,
                source_id TEXT,
                candidate_ids_json TEXT,
                admin_response_text TEXT,
                admin_responder TEXT,
                assigned_to TEXT,
                takeover_started_at TEXT,
                closed_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handoff_status ON handoff_tickets(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handoff_session ON handoff_tickets(session_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS handoff_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                session_id TEXT,
                created_at TEXT NOT NULL,
                role TEXT NOT NULL,
                responder TEXT,
                message_text TEXT NOT NULL,
                close_ticket INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handoff_messages_ticket ON handoff_messages(ticket_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handoff_messages_session ON handoff_messages(session_id)")
        conn.commit()
        # Ensure older DBs get required columns (migration safety)
        def _has_column(table: str, col: str) -> bool:
            cur = conn.execute(f"PRAGMA table_info({table})")
            return any(r[1] == col for r in cur.fetchall())

        # handoff_tickets required columns
        tickets_extra = {
            'admin_response_text': 'TEXT',
            'admin_responder': 'TEXT',
            'assigned_to': 'TEXT',
            'takeover_started_at': 'TEXT',
            'closed_at': 'TEXT',
            'candidate_ids_json': 'TEXT',
        }
        for c, typ in tickets_extra.items():
            if not _has_column('handoff_tickets', c):
                try:
                    conn.execute(f"ALTER TABLE handoff_tickets ADD COLUMN {c} {typ}")
                except Exception:
                    pass

        # handoff_messages required columns
        messages_extra = {
            'close_ticket': 'INTEGER',
        }
        for c, typ in messages_extra.items():
            if not _has_column('handoff_messages', c):
                try:
                    conn.execute(f"ALTER TABLE handoff_messages ADD COLUMN {c} {typ} DEFAULT 0")
                except Exception:
                    pass
        conn.commit()


def create_handoff_ticket(
    db_path: Path,
    *,
    session_id: str,
    question: str,
    category: str | None,
    confidence: float,
    route: str,
    reason: str,
    candidate_ids: list[str] | None = None,
    source_id: str | None = None,
) -> int:
    _init_handoff_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM handoff_tickets WHERE status IN ('open','in_progress') AND session_id = ? AND question = ? ORDER BY id DESC LIMIT 1",
            (session_id, question),
        ).fetchone()
        if existing:
            return int(existing[0])
        now = now_bangkok_iso()
        cur = conn.execute(
            """
            INSERT INTO handoff_tickets (
                created_at, updated_at, status, session_id, question, category, confidence,
                route, reason, source_id, candidate_ids_json
            ) VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                session_id,
                question,
                category,
                float(confidence),
                route,
                reason,
                source_id,
                json.dumps(candidate_ids or [], ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def claim_ticket(db_path: Path, *, ticket_id: int, responder: str) -> dict[str, Any]:
    _init_handoff_tables(db_path)
    now = now_bangkok_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE handoff_tickets
            SET updated_at = ?, status = 'in_progress', assigned_to = ?, takeover_started_at = COALESCE(takeover_started_at, ?)
            WHERE id = ?
            """,
            (now, responder, now, ticket_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, session_id, status, assigned_to, takeover_started_at, question FROM handoff_tickets WHERE id = ?",
            (ticket_id,),
        ).fetchone()
    if not row:
        raise ValueError(f'ticket {ticket_id} not found')
    return {
        'ticket_id': row[0],
        'session_id': row[1],
        'status': row[2],
        'assigned_to': row[3],
        'takeover_started_at': row[4],
        'question': row[5],
    }


def list_handoff_tickets(db_path: Path, *, status: str = 'open', limit: int = 200) -> list[dict[str, Any]]:
    _init_handoff_tables(db_path)
    sql = "SELECT id, created_at, updated_at, status, session_id, question, category, confidence, route, reason, source_id, candidate_ids_json, admin_response_text, admin_responder, assigned_to, takeover_started_at, closed_at FROM handoff_tickets"
    params: list[Any] = []
    if status != 'all':
        sql += ' WHERE status = ?'
        params.append(status)
    sql += ' ORDER BY id DESC LIMIT ?'
    params.append(limit)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for row in rows:
        out.append(
            {
                'id': row[0],
                'created_at': row[1],
                'updated_at': row[2],
                'status': row[3],
                'session_id': row[4],
                'question': row[5],
                'category': row[6],
                'confidence': row[7],
                'route': row[8],
                'reason': row[9],
                'source_id': row[10],
                'candidate_ids': json.loads(row[11] or '[]'),
                'admin_response_text': row[12],
                'admin_responder': row[13],
                'assigned_to': row[14],
                'takeover_started_at': row[15],
                'closed_at': row[16],
            }
        )
    return out


def respond_to_ticket(db_path: Path, *, ticket_id: int, response_text: str, responder: str, close_ticket: bool = True) -> dict[str, Any]:
    _init_handoff_tables(db_path)
    now = now_bangkok_iso()
    status = 'resolved' if close_ticket else 'in_progress'
    closed_at = now if close_ticket else None
    with sqlite3.connect(db_path) as conn:
        session_row = conn.execute('SELECT session_id FROM handoff_tickets WHERE id = ?', (ticket_id,)).fetchone()
        session_id = session_row[0] if session_row else None
        conn.execute(
            """
            UPDATE handoff_tickets
            SET updated_at = ?, status = ?, admin_response_text = ?, admin_responder = ?, assigned_to = COALESCE(assigned_to, ?), closed_at = ?
            WHERE id = ?
            """,
            (now, status, response_text, responder, responder, closed_at, ticket_id),
        )
        conn.execute(
            """
            INSERT INTO handoff_messages (ticket_id, session_id, created_at, role, responder, message_text, close_ticket)
            VALUES (?, ?, ?, 'admin', ?, ?, ?)
            """,
            (ticket_id, session_id, now, responder, response_text, 1 if close_ticket else 0),
        )
        conn.commit()
        row = conn.execute(
            'SELECT id, session_id, status, admin_response_text, admin_responder, updated_at FROM handoff_tickets WHERE id = ?',
            (ticket_id,),
        ).fetchone()
    if not row:
        raise ValueError(f'ticket {ticket_id} not found')
    return {
        'ticket_id': row[0],
        'session_id': row[1],
        'status': row[2],
        'response_text': row[3],
        'responder': row[4],
        'updated_at': row[5],
    }


def append_live_message(db_path: Path, *, ticket_id: int, responder: str, message_text: str, close_ticket: bool = False) -> dict[str, Any]:
    _init_handoff_tables(db_path)
    now = now_bangkok_iso()
    status = 'resolved' if close_ticket else 'in_progress'
    closed_at = now if close_ticket else None
    with sqlite3.connect(db_path) as conn:
        row = conn.execute('SELECT session_id FROM handoff_tickets WHERE id = ?', (ticket_id,)).fetchone()
        if not row:
            raise ValueError(f'ticket {ticket_id} not found')
        session_id = row[0]
        conn.execute(
            "INSERT INTO handoff_messages (ticket_id, session_id, created_at, role, responder, message_text, close_ticket) VALUES (?, ?, ?, 'admin', ?, ?, ?)",
            (ticket_id, session_id, now, responder, message_text, 1 if close_ticket else 0),
        )
        conn.execute(
            "UPDATE handoff_tickets SET updated_at=?, status=?, assigned_to=COALESCE(assigned_to, ?), admin_response_text=?, admin_responder=?, closed_at=? WHERE id=?",
            (now, status, responder, message_text, responder, closed_at, ticket_id),
        )
        msg_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
    return {
        'message_id': int(msg_id),
        'ticket_id': ticket_id,
        'session_id': session_id,
        'response_text': message_text,
        'responder': responder,
        'close_ticket': close_ticket,
        'created_at': now,
    }


def fetch_session_responses(db_path: Path, session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    _init_handoff_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, session_id, message_text, responder, close_ticket, ticket_id
            FROM handoff_messages
            WHERE session_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [
        {
            'message_id': row[0],
            'ts': row[1],
            'session_id': row[2],
            'response_text': row[3],
            'responder': row[4],
            'close_ticket': bool(row[5]),
            'ticket_id': row[6],
        }
        for row in rows
    ]


def fetch_session_responses_after(db_path: Path, session_id: str, *, after_id: int = 0, limit: int = 50) -> list[dict[str, Any]]:
    _init_handoff_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, session_id, message_text, responder, close_ticket, ticket_id
            FROM handoff_messages
            WHERE session_id = ? AND id > ?
            ORDER BY id ASC LIMIT ?
            """,
            (session_id, after_id, limit),
        ).fetchall()
    return [
        {
            'message_id': row[0],
            'ts': row[1],
            'session_id': row[2],
            'response_text': row[3],
            'responder': row[4],
            'close_ticket': bool(row[5]),
            'ticket_id': row[6],
        }
        for row in rows
    ]
