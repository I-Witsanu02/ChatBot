"""Focused runtime regression tests for UPH chatbot UAT routing fixes."""

from __future__ import annotations

import json
import sys
from typing import Any

import requests


FORBIDDEN_TEXT = [
    "D:\\",
    "หมายเหตุ:",
    "อัปเดตล่าสุด:",
    "หากต้องการถามต่อเกี่ยวกับ",
    "ไหมค่ะ",
]


class FocusedRuntimeRegressionTest:
    def __init__(self, base_url: str = "http://127.0.0.1:8000") -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = "test_focused_regression_v3"
        self.results: list[dict[str, Any]] = []

    def reset_session(self) -> None:
        try:
            requests.post(
                f"{self.base_url}/chat/reset-session",
                json={"session_id": self.session_id},
                timeout=15,
            )
        except Exception as exc:  # pragma: no cover
            print(f"Warning: could not reset session: {exc}")

    def chat(self, question: str) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/chat",
            json={
                "question": question,
                "session_id": self.session_id,
                "use_llm": False,
                "top_k": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        return response.json()

    def record(self, name: str, query: str, passed: bool, details: str) -> None:
        self.results.append(
            {
                "test_name": name,
                "query": query,
                "passed": bool(passed),
                "details": details,
            }
        )
        print(f"{name}: {'PASS' if passed else 'FAIL'}")

    def _attachment_urls(self, response: dict[str, Any]) -> list[str]:
        return [str(item.get("url") or "") for item in response.get("attachments") or []]

    def _assert_no_leakage(self, answer: str) -> tuple[bool, list[str]]:
        found = [token for token in FORBIDDEN_TEXT if token in answer]
        return (not found), found

    def run_health_program_test(self) -> None:
        self.reset_session()
        response = self.chat("โปรแกรมตรวจสุขภาพ")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        expected_urls = {
            "/assets/health-check/โปรแกรมตรวจสุขภาพ.jpg",
            "/assets/health-check/โปรแกรมตรวจสุขภาพ 2.jpg",
            "/assets/health-check/ไลน์ Check-up.jpg",
        }
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "054 466 666 ต่อ 7173" in answer
            and "08.00-16.00" in answer
            and expected_urls.issubset(set(urls))
            and len(urls) == len(set(urls))
            and no_leakage
            and "054 466 666 ต่อ 7173\n054 466 666 ต่อ 7173" not in answer
        )
        self.record(
            "HC_Program",
            "โปรแกรมตรวจสุขภาพ",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_health_hours_test(self) -> None:
        self.reset_session()
        response = self.chat("เวลาตรวจสุขภาพ")
        answer = str(response.get("answer") or "")
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "เวลา 08.00-16.00 น." in answer
            and "หยุดทุกวันเสาร์-อาทิตย์" in answer
            and "ติดต่อแผนกตรวจสุขภาพ" not in answer
            and no_leakage
        )
        self.record(
            "HC_Hours",
            "เวลาตรวจสุขภาพ",
            passed,
            f"answer={answer!r}, forbidden={found}",
        )

    def run_health_certificate_test(self) -> None:
        self.reset_session()
        response = self.chat("ใบรับรองแพทย์")
        answer = str(response.get("answer") or "")
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "054 466 666 ต่อ 7173" in answer
            and "08.00-16.00" in answer
            and no_leakage
        )
        self.record(
            "HC_Certificate",
            "ใบรับรองแพทย์",
            passed,
            f"answer={answer!r}, urls={self._attachment_urls(response)}, forbidden={found}",
        )

    def run_schedule_eye_test(self) -> None:
        self.reset_session()
        response = self.chat("จักษุแพทย์ (ตา)")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "นายแพทย์ดนัยภัทร" in answer
            and "แพทย์หญิงชญานี" in answer
            and "ยังไม่ระบุชื่อแพทย์ในข้อมูล" not in answer
            and "/assets/schedule/ตา.png" in urls
            and no_leakage
        )
        self.record(
            "SCH_Eye",
            "จักษุแพทย์ (ตา)",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_schedule_internal_medicine_group_test(self) -> None:
        self.reset_session()
        response = self.chat("อายุรกรรม")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        required_names = [
            "แพทย์หญิงเพชราภรณ์",
            "นายแพทย์ภาษา",
            "แพทย์หญิงมัลลิกา",
            "นายแพทย์พงศธร",
        ]
        passed = (
            all(name in answer for name in required_names)
            and "/assets/schedule/อายุรกรรม 1.png" in urls
            and "/assets/schedule/อายุรกรรม 2.png" in urls
            and no_leakage
        )
        self.record(
            "SCH_InternalMed_Group",
            "อายุรกรรม",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_schedule_skin_test(self) -> None:
        self.reset_session()
        response = self.chat("ผิวหนัง")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "แพทย์หญิงภัทรภร" in answer
            and "นายแพทย์วสุชล" in answer
            and "/assets/schedule/ผิวหนัง.png" in urls
            and no_leakage
        )
        self.record(
            "SCH_Skin",
            "ผิวหนัง",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_pediatrics_schedule_test(self) -> None:
        self.reset_session()
        response = self.chat("กุมารแพทย์")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "กุมารแพทย์ (ผู้ป่วยนอก 3/OPD 3)" in answer
            and "เพ็ญพรรณ" in answer
            and "สรกิจ" in answer
            and "สรัสวดี" not in answer
            and "/assets/schedule/กุมารแพทย์.png" in urls
            and no_leakage
        )
        self.record(
            "SCH_Pediatrics",
            "กุมารแพทย์",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_pediatric_cardiology_schedule_test(self) -> None:
        self.reset_session()
        response = self.chat("กุมารแพทย์ โรคหัวใจ")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "กุมารแพทย์ โรคหัวใจ (ผู้ป่วยนอก 3/OPD 3)" in answer
            and "สรัสวดี" in answer
            and "เพ็ญพรรณ" not in answer
            and "สรกิจ" not in answer
            and "/assets/schedule/กุมารแพทย์.png" in urls
            and no_leakage
        )
        self.record(
            "SCH_PediatricCardiology",
            "กุมารแพทย์ โรคหัวใจ",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_adult_cardiology_schedule_test(self) -> None:
        self.reset_session()
        response = self.chat("อายุรแพทย์โรคหัวใจ")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "อายุรแพทย์โรคหัวใจ" in answer
            and "พงศธร" in answer
            and "สรัสวดี" not in answer
            and "เพ็ญพรรณ" not in answer
            and "สรกิจ" not in answer
            and "/assets/schedule/อายุรกรรม 1.png" in urls
            and no_leakage
        )
        self.record(
            "SCH_AdultCardiology",
            "อายุรแพทย์โรคหัวใจ",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_doctor_name_tests(self) -> None:
        cases = [
            (
                "DOC_Krittin",
                "หมอกฤตินออกตรวจวันไหน",
                ["นายแพทย์กฤติน นาราเวชสกุล", "ระบบทางเดินปัสสาวะ", "วันอังคาร", "08.00-12.00"],
                "/assets/schedule/ทางเดินปัสสาวะ.png",
            ),
            (
                "DOC_PacharaShort",
                "หมอพชร วันไหน",
                ["นายแพทย์พชรพล อุดมลักษณ์", "ศัลยแพทย์กระดูกและข้อ", "วันศุกร์", "08.00-16.00"],
                "/assets/schedule/กระดูกและข้อ.png",
            ),
            (
                "DOC_Pacharapol",
                "พชรพล",
                ["นายแพทย์พชรพล อุดมลักษณ์", "ศัลยแพทย์กระดูกและข้อ"],
                "/assets/schedule/กระดูกและข้อ.png",
            ),
            (
                "DOC_Nitiphumi",
                "นิติภูมิ",
                ["นายแพทย์นิติภูมิ สินณฐากร", "ศัลยแพทย์กระดูกและข้อ", "วันพุธ"],
                "/assets/schedule/กระดูกและข้อ.png",
            ),
        ]
        for name, query, required_parts, required_url in cases:
            self.reset_session()
            response = self.chat(query)
            answer = str(response.get("answer") or "")
            urls = self._attachment_urls(response)
            no_leakage, found = self._assert_no_leakage(answer)
            passed = all(part in answer for part in required_parts) and required_url in urls and no_leakage
            self.record(
                name,
                query,
                passed,
                f"answer={answer!r}, urls={urls}, forbidden={found}",
            )

    def run_reschedule_route_test(self) -> None:
        self.reset_session()
        response = self.chat("ขอเลื่อนนัดพบแพทย์")
        answer = str(response.get("answer") or "")
        buttons = response.get("action_buttons") or []
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "ต่อ 7304" in answer
            and "ต่อ 7173" in answer
            and "ต่อ 7210" in answer
            and "กุมารแพทย์" not in answer
            and not urls
            and buttons == ["การจัดการนัดหมาย", "ตารางแพทย์และเวลาทำการ", "กลับหน้าหลัก"]
            and no_leakage
        )
        self.record(
            "UAT_Reschedule",
            "ขอเลื่อนนัดพบแพทย์",
            passed,
            f"answer={answer!r}, buttons={buttons}, urls={urls}, forbidden={found}",
        )

    def run_mental_health_specialty_test(self) -> None:
        self.reset_session()
        response = self.chat("สุขภาพจิตชุมชน")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "เธียรชัย" in answer
            and "สุขภาพจิตชุมชน" in answer
            and "ภาษา สุขสอน" not in answer
            and "/assets/schedule/เวชศาสตร์.png" in urls
            and no_leakage
        )
        self.record(
            "UAT_MentalHealth",
            "สุขภาพจิตชุมชน",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_checkup_schedule_test(self) -> None:
        self.reset_session()
        response = self.chat("ตรวจสุขภาพ")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "ตรวจสุขภาพ (ผู้ป่วยนอก 2/OPD 2)" in answer
            and "ชนกนันท์" in answer
            and "อชิรญา" in answer
            and "ภาษา สุขสอน" not in answer
            and "/assets/schedule/เวชศาสตร์.png" in urls
            and no_leakage
        )
        self.record(
            "UAT_CheckupSchedule",
            "ตรวจสุขภาพ",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_elderly_specialty_test(self) -> None:
        self.reset_session()
        response = self.chat("อายุรแพทย์ผู้สูงอายุ")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "อายุรแพทย์คลินิกผู้สูงอายุ" in answer
            and "ภาษา สุขสอน" in answer
            and all(name not in answer for name in ["มัลลิกา", "กานต์ธิรา", "พงศธร"])
            and "/assets/schedule/อายุรกรรม 1.png" in urls
            and no_leakage
        )
        self.record(
            "UAT_ElderlySpecialty",
            "อายุรแพทย์ผู้สูงอายุ",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_cancer_specialty_test(self) -> None:
        self.reset_session()
        response = self.chat("อายุรแพทย์มะเร็งวิทยา")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "อายุรแพทย์มะเร็งวิทยา" in answer
            and "มัลลิกา" in answer
            and all(name not in answer for name in ["ภาษา สุขสอน", "กานต์ธิรา", "พงศธร"])
            and "/assets/schedule/อายุรกรรม 1.png" in urls
            and no_leakage
        )
        self.record(
            "UAT_CancerSpecialty",
            "อายุรแพทย์มะเร็งวิทยา",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_neuro_specialty_test(self) -> None:
        self.reset_session()
        response = self.chat("ระบบประสาทและสมอง")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "ระบบประสาทและสมอง" in answer
            and "จิตราภรณ์" in answer
            and "วัชเรสร" in answer
            and "ภาษา สุขสอน" not in answer
            and "/assets/schedule/อายุรกรรม 1.png" in urls
            and "/assets/schedule/อายุรกรรม 2.png" in urls
            and no_leakage
        )
        self.record(
            "UAT_NeuroSpecialty",
            "ระบบประสาทและสมอง",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_ortho_rehab_specialty_test(self) -> None:
        self.reset_session()
        response = self.chat("ออร์โธปิดิคส์บูรณสภาพ")
        answer = str(response.get("answer") or "")
        urls = self._attachment_urls(response)
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "ออร์โธปิดิคส์บูรณสภาพ" in answer
            and "ฐิตินันท์" in answer
            and "พชรพล" not in answer
            and "/assets/schedule/กระดูกและข้อ.png" in urls
            and no_leakage
        )
        self.record(
            "UAT_OrthoRehab",
            "ออร์โธปิดิคส์บูรณสภาพ",
            passed,
            f"answer={answer!r}, urls={urls}, forbidden={found}",
        )

    def run_opd_hours_route_test(self) -> None:
        self.reset_session()
        response = self.chat("เวลาทำการแผนกผู้ป่วยนอก")
        answer = str(response.get("answer") or "")
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            "08.00-16.00" in answer
            and "16.00-20.00" in answer
            and "ฉุกเฉินเปิดบริการ 24 ชั่วโมง" in answer
            and "ต้องการทราบตารางแพทย์" not in answer
            and no_leakage
        )
        self.record(
            "UAT_OPDHours",
            "เวลาทำการแผนกผู้ป่วยนอก",
            passed,
            f"answer={answer!r}, forbidden={found}",
        )

    def run_fallback_test(self) -> None:
        self.reset_session()
        response = self.chat("ผ่าตัดหัวใจราคาเท่าไหร่")
        answer = str(response.get("answer") or "")
        buttons = response.get("action_buttons") or []
        no_leakage, found = self._assert_no_leakage(answer)
        passed = (
            response.get("route") == "fallback"
            and "0 5446 6666 ต่อ 7000" in answer
            and buttons == ["กลับหน้าหลัก", "ติดต่อโรงพยาบาล"]
            and no_leakage
        )
        self.record(
            "Fallback_Unsupported",
            "ผ่าตัดหัวใจราคาเท่าไหร่",
            passed,
            f"route={response.get('route')}, answer={answer!r}, buttons={buttons}, forbidden={found}",
        )

    def run_all_tests(self) -> dict[str, Any]:
        print("=" * 60)
        print("Starting Focused Runtime Regression Tests")
        print("=" * 60)

        self.run_health_program_test()
        self.run_health_hours_test()
        self.run_health_certificate_test()
        self.run_schedule_eye_test()
        self.run_schedule_internal_medicine_group_test()
        self.run_schedule_skin_test()
        self.run_pediatrics_schedule_test()
        self.run_pediatric_cardiology_schedule_test()
        self.run_adult_cardiology_schedule_test()
        self.run_doctor_name_tests()
        self.run_reschedule_route_test()
        self.run_mental_health_specialty_test()
        self.run_checkup_schedule_test()
        self.run_elderly_specialty_test()
        self.run_cancer_specialty_test()
        self.run_neuro_specialty_test()
        self.run_ortho_rehab_specialty_test()
        self.run_opd_hours_route_test()
        self.run_fallback_test()

        total = len(self.results)
        passed = sum(1 for item in self.results if item["passed"])
        failed = total - passed
        summary = {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{(passed / total * 100):.1f}%" if total else "0%",
            "results": self.results,
        }

        print("\n" + "=" * 60)
        print("Test Summary")
        print("=" * 60)
        print(f"Total tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Pass rate: {summary['pass_rate']}")
        print("=" * 60)

        if failed:
            print("\nFailed tests:")
            for item in self.results:
                if not item["passed"]:
                    print(f"  - {item['test_name']}: {item['details']}")

        return summary


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    tester = FocusedRuntimeRegressionTest(base_url)
    summary = tester.run_all_tests()
    with open("focused_runtime_regression_results.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    print("\nResults saved to focused_runtime_regression_results.json")
    sys.exit(0 if summary.get("failed", 0) == 0 else 1)


if __name__ == "__main__":
    main()
