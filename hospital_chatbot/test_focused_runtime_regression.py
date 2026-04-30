"""Focused runtime regression tests for 4 specific bug fixes.

Tests:
1. Main menu fix - "นัดหมายและตารางแพทย์" exposes both child branches
2. Follow-up binding fix - Short follow-up questions bind to current topic first
3. "มีรูปไหม" context fix - Returns image/file if exists in current schedule topic
4. Vaccine child mapping fix - Vaccine child topics map exactly to KB child topic
"""

import json
import requests
from typing import Any, Dict, List


class FocusedRuntimeRegressionTest:
    """Test class for focused runtime regression tests."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url
        self.session_id = "test_focused_regression"
        self.results: List[Dict[str, Any]] = []

    def reset_session(self) -> None:
        """Reset the test session."""
        try:
            requests.post(f"{self.base_url}/chat/reset-session", json={"session_id": self.session_id})
        except Exception as e:
            print(f"Warning: Could not reset session: {e}")

    def chat(self, question: str) -> Dict[str, Any]:
        """Send a chat request and return the response."""
        payload = {
            "question": question,
            "session_id": self.session_id,
            "use_llm": False,
            "top_k": 10
        }
        response = requests.post(f"{self.base_url}/chat", json=payload)
        response.raise_for_status()
        return response.json()

    def record_result(self, test_name: str, query: str, expected: str, actual: str, passed: bool, details: str = "") -> None:
        """Record a test result."""
        self.results.append({
            "test_name": test_name,
            "query": query,
            "expected": expected,
            "actual": actual,
            "passed": passed,
            "details": details
        })

    def run_test_group_a_main_menu(self) -> None:
        """Test Group A: Main menu / child tree."""
        print("\n=== Group A: Main menu / child tree ===")

        # Test A1: "นัดหมายและตารางแพทย์" should expose both child branches
        self.reset_session()
        response = self.chat("นัดหมายและตารางแพทย์")
        buttons = response.get("action_buttons", [])
        
        # Check that both child branches are present
        has_appointment = any("การจัดการนัดหมาย" in b or "นัด" in b for b in buttons)
        has_schedule = any("ตารางแพทย์" in b or "เวลาทำการ" in b for b in buttons)
        
        passed = has_appointment and has_schedule
        self.record_result(
            "A1_MainMenuBothBranches",
            "นัดหมายและตารางแพทย์",
            "Both การจัดการนัดหมาย and ตารางแพทย์และเวลาทำการ in buttons",
            f"Buttons: {buttons}",
            passed,
            f"Has appointment branch: {has_appointment}, Has schedule branch: {has_schedule}"
        )
        print(f"A1. Main menu both branches: {'PASS' if passed else 'FAIL'}")

        # Test A2: "ตารางแพทย์" should show schedule options
        self.reset_session()
        response = self.chat("ตารางแพทย์")
        selected_category = response.get("selected_category", "")
        passed = "ตารางแพทย์" in selected_category or "นัดหมายและตารางแพทย์" in selected_category
        self.record_result(
            "A2_ScheduleCategory",
            "ตารางแพทย์",
            "Category contains ตารางแพทย์ or นัดหมายและตารางแพทย์",
            f"Category: {selected_category}",
            passed
        )
        print(f"A2. Schedule category: {'PASS' if passed else 'FAIL'}")

        # Test A3: "เวลาทำการแผนกผู้ป่วยนอก"
        self.reset_session()
        response = self.chat("เวลาทำการแผนกผู้ป่วยนอก")
        selected_category = response.get("selected_category", "")
        passed = "นัดหมายและตารางแพทย์" in selected_category or "ตารางแพทย์" in selected_category
        self.record_result(
            "A3_OPDHours",
            "เวลาทำการแผนกผู้ป่วยนอก",
            "Category contains นัดหมายและตารางแพทย์ or ตารางแพทย์",
            f"Category: {selected_category}",
            passed
        )
        print(f"A3. OPD hours: {'PASS' if passed else 'FAIL'}")

        # Test A4: "ขอเลื่อนนัดพบแพทย์"
        self.reset_session()
        response = self.chat("ขอเลื่อนนัดพบแพทย์")
        selected_category = response.get("selected_category", "")
        passed = "การจัดการนัดหมาย" in selected_category or "นัดหมาย" in selected_category
        self.record_result(
            "A4_AppointmentReschedule",
            "ขอเลื่อนนัดพบแพทย์",
            "Category contains การจัดการนัดหมาย or นัดหมาย",
            f"Category: {selected_category}",
            passed
        )
        print(f"A4. Appointment reschedule: {'PASS' if passed else 'FAIL'}")

    def run_test_group_b_followup_binding(self) -> None:
        """Test Group B: Follow-up binding."""
        print("\n=== Group B: Follow-up binding ===")

        # Test B1: Follow-up should bind to current topic (ติดต่อที่ไหน)
        self.reset_session()
        try:
            response1 = self.chat("นัดหมายและตารางแพทย์")
            response2 = self.chat("ขอเลื่อนนัดพบแพทย์")
            response3 = self.chat("ติดต่อที่ไหน")
            
            # The follow-up should stay in the appointment context, not jump to schedule
            selected_category = response3.get("selected_category", "") or ""
            passed = "การจัดการนัดหมาย" in selected_category or "นัดหมาย" in selected_category
            self.record_result(
                "B1_FollowupContact",
                "นัดหมายและตารางแพทย์ -> ขอเลื่อนนัดพบแพทย์ -> ติดต่อที่ไหน",
                "Category should be การจัดการนัดหมาย (not ตารางแพทย์)",
                f"Category: {selected_category}",
                passed
            )
            print(f"B1. Follow-up contact: {'PASS' if passed else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "B1_FollowupContact",
                "นัดหมายและตารางแพทย์ -> ขอเลื่อนนัดพบแพทย์ -> ติดต่อที่ไหน",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"B1. Follow-up contact: FAIL (error: {e})")

        # Test B2: Follow-up should bind to current topic (เปิดวันไหน)
        self.reset_session()
        try:
            self.chat("นัดหมายและตารางแพทย์")
            self.chat("ขอเลื่อนนัดพบแพทย์")
            response = self.chat("เปิดวันไหน")
            
            selected_category = response.get("selected_category", "") or ""
            passed = "การจัดการนัดหมาย" in selected_category or "นัดหมาย" in selected_category
            self.record_result(
                "B2_FollowupHours",
                "นัดหมายและตารางแพทย์ -> ขอเลื่อนนัดพบแพทย์ -> เปิดวันไหน",
                "Category should be การจัดการนัดหมาย (not ตารางแพทย์)",
                f"Category: {selected_category}",
                passed
            )
            print(f"B2. Follow-up hours: {'PASS' if passed else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "B2_FollowupHours",
                "นัดหมายและตารางแพทย์ -> ขอเลื่อนนัดพบแพทย์ -> เปิดวันไหน",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"B2. Follow-up hours: FAIL (error: {e})")

        # Test B3: Follow-up "มีรูปไหม" should not switch category
        self.reset_session()
        try:
            self.chat("นัดหมายและตารางแพทย์")
            self.chat("ขอเลื่อนนัดพบแพทย์")
            response = self.chat("มีรูปไหม")
            
            selected_category = response.get("selected_category", "") or ""
            passed = "การจัดการนัดหมาย" in selected_category or "นัดหมาย" in selected_category
            self.record_result(
                "B3_FollowupImage",
                "นัดหมายและตารางแพทย์ -> ขอเลื่อนนัดพบแพทย์ -> มีรูปไหม",
                "Category should be การจัดการนัดหมาย (not ตารางแพทย์)",
                f"Category: {selected_category}",
                passed
            )
            print(f"B3. Follow-up image: {'PASS' if passed else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "B3_FollowupImage",
                "นัดหมายและตารางแพทย์ -> ขอเลื่อนนัดพบแพทย์ -> มีรูปไหม",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"B3. Follow-up image: FAIL (error: {e})")

    def run_test_group_c_schedule_image_context(self) -> None:
        """Test Group C: Schedule image context."""
        print("\n=== Group C: Schedule image context ===")

        # Test C1: Schedule topic with "มีรูปไหม" should check current topic
        self.reset_session()
        try:
            self.chat("ตารางแพทย์ออกตรวจ")
            self.chat("จักษุแพทย์ (ตา)")
            response = self.chat("มีรูปไหม")
            
            # Tighten: Must explicitly mention image/file/link OR say no image available
            # Generic greeting/menu response should NOT count as PASS
            answer = response.get("answer", "").lower() or ""
            selected_category = response.get("selected_category", "") or ""
            
            # Check for explicit image-related mentions
            has_image_mention = any(phrase in answer for phrase in ["รูป", "ภาพ", "ไฟล์", "ลิงก์", "link"])
            has_no_image = "ไม่มี" in answer and ("รูป" in answer or "ภาพ" in answer or "ไฟล์" in answer)
            
            # Check that it doesn't jump to wrong category (should stay in schedule-related category)
            correct_category = "ตารางแพทย์" in selected_category or "จักษุ" in selected_category or "ตา" in selected_category
            
            passed = (has_image_mention or has_no_image) and correct_category
            self.record_result(
                "C1_ScheduleImageEye",
                "ตารางแพทย์ออกตรวจ -> จักษุแพทย์ (ตา) -> มีรูปไหม",
                "Must explicitly mention image/file/link OR say no image, AND stay in correct category",
                f"Answer: {answer[:100]}, Category: {selected_category}",
                passed
            )
            print(f"C1. Schedule image (eye): {'PASS' if passed else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "C1_ScheduleImageEye",
                "ตารางแพทย์ออกตรวจ -> จักษุแพทย์ (ตา) -> มีรูปไหม",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"C1. Schedule image (eye): FAIL (error: {e})")

        # Test C2: Another schedule topic
        self.reset_session()
        try:
            self.chat("ตารางแพทย์")
            self.chat("หมอตาวันนี้มีไหม")
            response = self.chat("มีรูปไหม")
            
            answer = response.get("answer", "").lower() or ""
            selected_category = response.get("selected_category", "") or ""
            
            has_image_mention = any(phrase in answer for phrase in ["รูป", "ภาพ", "ไฟล์", "ลิงก์", "link"])
            has_no_image = "ไม่มี" in answer and ("รูป" in answer or "ภาพ" in answer or "ไฟล์" in answer)
            correct_category = "ตารางแพทย์" in selected_category or "จักษุ" in selected_category or "ตา" in selected_category
            
            passed = (has_image_mention or has_no_image) and correct_category
            self.record_result(
                "C2_ScheduleImageToday",
                "ตารางแพทย์ -> หมอตาวันนี้มีไหม -> มีรูปไหม",
                "Must explicitly mention image/file/link OR say no image, AND stay in correct category",
                f"Answer: {answer[:100]}, Category: {selected_category}",
                passed
            )
            print(f"C2. Schedule image (today): {'PASS' if passed else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "C2_ScheduleImageToday",
                "ตารางแพทย์ -> หมอตาวันนี้มีไหม -> มีรูปไหม",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"C2. Schedule image (today): FAIL (error: {e})")

        # Test C3: Orthopedic schedule
        self.reset_session()
        try:
            self.chat("ตารางแพทย์")
            self.chat("หมอกระดูกออกวันไหน")
            response = self.chat("มีรูปไหม")
            
            answer = response.get("answer", "").lower() or ""
            selected_category = response.get("selected_category", "") or ""
            
            has_image_mention = any(phrase in answer for phrase in ["รูป", "ภาพ", "ไฟล์", "ลิงก์", "link"])
            has_no_image = "ไม่มี" in answer and ("รูป" in answer or "ภาพ" in answer or "ไฟล์" in answer)
            correct_category = "ตารางแพทย์" in selected_category or "กระดูก" in selected_category or "ศัลยศาสตร์" in selected_category
            
            passed = (has_image_mention or has_no_image) and correct_category
            self.record_result(
                "C3_ScheduleImageBone",
                "ตารางแพทย์ -> หมอกระดูกออกวันไหน -> มีรูปไหม",
                "Must explicitly mention image/file/link OR say no image, AND stay in correct category",
                f"Answer: {answer[:100]}, Category: {selected_category}",
                passed
            )
            print(f"C3. Schedule image (bone): {'PASS' if passed else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "C3_ScheduleImageBone",
                "ตารางแพทย์ -> หมอกระดูกออกวันไหน -> มีรูปไหม",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"C3. Schedule image (bone): FAIL (error: {e})")

    def run_test_group_d_vaccine_child_mapping(self) -> None:
        """Test Group D: Vaccine exact child mapping."""
        print("\n=== Group D: Vaccine exact child mapping ===")

        # Test D1: HPV vaccine
        self.reset_session()
        try:
            response = self.chat("วัคซีน")
            buttons = response.get("action_buttons", []) or []
            
            # Check that HPV is available as a child option
            has_hpv = any("hpv" in b.lower() or "มะเร็งปากมดลูก" in b for b in buttons)
            self.record_result(
                "D1_VaccineHPV",
                "วัคซีน",
                "HPV/มะเร็งปากมดลูก should be in child options",
                f"Buttons: {buttons}",
                has_hpv
            )
            print(f"D1. Vaccine HPV: {'PASS' if has_hpv else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "D1_VaccineHPV",
                "วัคซีน",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"D1. Vaccine HPV: FAIL (error: {e})")

        # Test D2: Influenza vaccine
        self.reset_session()
        try:
            response = self.chat("วัคซีน")
            buttons = response.get("action_buttons", []) or []
            
            has_flu = any("ไข้หวัด" in b or "influenza" in b.lower() for b in buttons)
            self.record_result(
                "D2_VaccineFlu",
                "วัคซีน",
                "ไข้หวัด/influenza should be in child options",
                f"Buttons: {buttons}",
                has_flu
            )
            print(f"D2. Vaccine flu: {'PASS' if has_flu else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "D2_VaccineFlu",
                "วัคซีน",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"D2. Vaccine flu: FAIL (error: {e})")

        # Test D3: Hepatitis B vaccine
        self.reset_session()
        try:
            response = self.chat("วัคซีน")
            buttons = response.get("action_buttons", []) or []
            
            has_hepb = any("ตับ" in b or "hepatitis" in b.lower() for b in buttons)
            self.record_result(
                "D3_VaccineHepB",
                "วัคซีน",
                "ตับ/hepatitis should be in child options",
                f"Buttons: {buttons}",
                has_hepb
            )
            print(f"D3. Vaccine Hep B: {'PASS' if has_hepb else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "D3_VaccineHepB",
                "วัคซีน",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"D3. Vaccine Hep B: FAIL (error: {e})")

        # Test D4: Rabies/Tetanus vaccine
        self.reset_session()
        try:
            response = self.chat("วัคซีน")
            buttons = response.get("action_buttons", []) or []
            
            has_rabies = any("บาดทะยัก" in b or "พิษสุนัข" in b or "rabies" in b.lower() for b in buttons)
            self.record_result(
                "D4_VaccineRabies",
                "วัคซีน",
                "บาดทะยัก/พิษสุนัข/rabies should be in child options",
                f"Buttons: {buttons}",
                has_rabies
            )
            print(f"D4. Vaccine rabies: {'PASS' if has_rabies else 'FAIL'}")
        except Exception as e:
            self.record_result(
                "D4_VaccineRabies",
                "วัคซีน",
                "Should return valid response",
                f"Error: {e}",
                False
            )
            print(f"D4. Vaccine rabies: FAIL (error: {e})")

    def run_test_group_e_other_categories(self) -> None:
        """Test Group E: Coverage for other real categories."""
        print("\n=== Group E: Other real categories ===")

        test_cases = [
            ("E1_RightsTransfer", "ย้ายสิทธิ"),
            ("E2_MedicalHistory", "ขอประวัติการรักษา"),
            ("E3_TreatmentCost", "ค่ารักษา"),
            ("E4_Dialysis", "ฟอกไต"),
            ("E5_BloodDonation", "บริจาคเลือด"),
            ("E6_Dentist", "หมอฟัน"),
            ("E7_Jobs", "สมัครงาน"),
            ("E8_HealthCheck", "ตรวจสุขภาพ"),
            ("E9_GroupHealthCheck", "ตรวจสุขภาพหมู่คณะ"),
            ("E10_MedicalCertificate", "ใบรับรองแพทย์"),
        ]

        for test_name, query in test_cases:
            self.reset_session()
            try:
                response = self.chat(query)
                selected_category = response.get("selected_category", "") or ""
                route = response.get("route", "") or ""
                # FIX: Make passed a real boolean, not a string
                passed = bool(route in ["answer", "clarify"] and selected_category)
                self.record_result(
                    test_name,
                    query,
                    f"Route should be answer/clarify with category",
                    f"Route: {route}, Category: {selected_category}",
                    passed
                )
                print(f"{test_name}: {'PASS' if passed else 'FAIL'}")
            except Exception as e:
                self.record_result(
                    test_name,
                    query,
                    "Should return valid response",
                    f"Error: {e}",
                    False
                )
                print(f"{test_name}: FAIL (error: {e})")

    def run_all_tests(self) -> Dict[str, Any]:
        """Run all test groups and return summary."""
        print("=" * 60)
        print("Starting Focused Runtime Regression Tests")
        print("=" * 60)

        try:
            self.run_test_group_a_main_menu()
            self.run_test_group_b_followup_binding()
            self.run_test_group_c_schedule_image_context()
            self.run_test_group_d_vaccine_child_mapping()
            self.run_test_group_e_other_categories()
        except Exception as e:
            print(f"\nERROR: Test execution failed: {e}")
            return {"error": str(e)}

        # Calculate summary
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed

        summary = {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{(passed / total * 100):.1f}%" if total > 0 else "0%",
            "results": self.results
        }

        print("\n" + "=" * 60)
        print("Test Summary")
        print("=" * 60)
        print(f"Total tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Pass rate: {summary['pass_rate']}")
        print("=" * 60)

        # Print failed tests
        failed_tests = [r for r in self.results if not r["passed"]]
        if failed_tests:
            print("\nFailed tests:")
            for test in failed_tests:
                print(f"  - {test['test_name']}: {test['details']}")

        return summary


def main():
    """Main entry point."""
    import sys
    
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    
    tester = FocusedRuntimeRegressionTest(base_url)
    summary = tester.run_all_tests()
    
    # Save results to file
    output_file = "focused_runtime_regression_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved to {output_file}")
    
    # Exit with error code if any tests failed
    sys.exit(0 if summary.get("failed", 0) == 0 else 1)


if __name__ == "__main__":
    main()
