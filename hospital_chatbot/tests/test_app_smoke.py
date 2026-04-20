from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("WORKBOOK_PATH", str(Path(__file__).resolve().parents[1] / "data" / "master_kb.xlsx"))
os.environ.setdefault("KNOWLEDGE_JSONL", str(Path(__file__).resolve().parents[1] / "data" / "knowledge.jsonl"))

from fastapi.testclient import TestClient  # noqa: E402
from backend.app import app  # noqa: E402


class AppSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_guide(self) -> None:
        res = self.client.get("/guide")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("welcome_message", data)
        self.assertTrue(data["supported_topics"])

    def test_gibberish_fallback(self) -> None:
        res = self.client.post("/chat", json={"question": "ฟหก", "session_id": "t1", "use_llm": False})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["route"], "fallback")
        self.assertIn("handoff_required", data)

    def test_exact_answer(self) -> None:
        res = self.client.post("/chat", json={"question": "วัคซีนไวรัสตับอักเสบบี", "session_id": "t2", "use_llm": False})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn(data["route"], {"answer", "clarify"})
        self.assertTrue(data["answer"])


if __name__ == "__main__":
    unittest.main()
