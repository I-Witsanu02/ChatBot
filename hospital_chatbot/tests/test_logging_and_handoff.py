from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.handoff import create_handoff_ticket, fetch_session_responses, list_handoff_tickets, respond_to_ticket
from backend.request_log import analytics_summary, init_request_log_db, list_request_logs, log_chat_request


class LoggingAndHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "analytics.db"
        init_request_log_db(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_request_log_roundtrip(self) -> None:
        row_id = log_chat_request(
            self.db_path,
            session_id="s1",
            question="วัคซีนไวรัสตับอักเสบบี",
            route="answer",
            category="วัคซีน",
            confidence=0.91,
            reason="direct_catalog_match",
            source_id="วัคซีน_2",
            warnings=[],
        )
        self.assertGreater(row_id, 0)
        items = list_request_logs(self.db_path, limit=10)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["category"], "วัคซีน")
        summary = analytics_summary(self.db_path)
        self.assertEqual(summary["total_requests"], 1)

    def test_handoff_ticket_roundtrip(self) -> None:
        ticket_id = create_handoff_ticket(
            self.db_path,
            session_id="session-x",
            question="สิทธิการรักษา",
            category="ประเมินค่าใช้จ่ายทั่วไป",
            confidence=0.33,
            route="fallback",
            reason="low_confidence",
            candidate_ids=["a", "b"],
            source_id=None,
        )
        self.assertGreater(ticket_id, 0)
        queue = list_handoff_tickets(self.db_path, status="open", limit=10)
        self.assertEqual(queue[0]["id"], ticket_id)
        result = respond_to_ticket(self.db_path, ticket_id=ticket_id, response_text="ติดต่อเวชระเบียน ต่อ 7226", responder="PR", close_ticket=True)
        self.assertEqual(result["status"], "resolved")
        session_items = fetch_session_responses(self.db_path, "session-x", limit=5)
        self.assertEqual(session_items[0]["response_text"], "ติดต่อเวชระเบียน ต่อ 7226")


if __name__ == "__main__":
    unittest.main()
