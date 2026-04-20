from __future__ import annotations

import unittest
from fastapi.testclient import TestClient
from backend.app import app


class AliasRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def ask(self, text: str):
        return self.client.post("/chat", json={"question": text, "session_id": "alias-test", "use_llm": False}).json()

    def test_typo_vaccine_routes_to_category(self):
        data = self.ask("วัปซีน")
        self.assertEqual(data["route"], "clarify")
        self.assertEqual(data.get("selected_category"), "วัคซีน")

    def test_student_vaccine_routes_to_student_category(self):
        data = self.ask("วัคซีนสำหรับนักศึกษา")
        self.assertEqual(data["route"], "clarify")
        self.assertEqual(data.get("selected_category"), "สวัสดิการวัคซีนนักศึกษา")

    def test_blood_routes_to_blood_category(self):
        data = self.ask("เลือด")
        self.assertEqual(data["route"], "clarify")
        self.assertEqual(data.get("selected_category"), "ธนาคารเลือดและบริจาคเลือด")

    def test_gibberish_fallback(self):
        data = self.ask("ฟหก")
        self.assertEqual(data["route"], "fallback")
        self.assertEqual(data.get("reason"), "unclear_input")


if __name__ == "__main__":
    unittest.main()
