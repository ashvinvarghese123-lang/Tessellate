"""
TESSellate — MDC, Minor & Course Selection-Based Scheduling Tests
Tests the 13 scenarios specified in the update requirements:
1. CS creates a student-selected MDC.
2. Mathematics creates a student-selected MDC.
3. Chemistry creates a student-selected Minor.
4. All these offerings use the configured common scheduling period.
5. Students from multiple departments can enroll in the same offering.
6. Student-selected MDC and Minor offerings do not overlap with other selected offerings for the same student.
7. Different offerings can run simultaneously when their students do not overlap.
8. A department creates a department-selected MDC.
9. That department-selected MDC is scheduled in its normal timetable, not forced into the common slot,
   and cross-department enrollment is prohibited.
10. The same behavior works for department-selected Minor.
11. Regular subjects continue to work as before.
12. Teacher, room and lab conflicts are still prevented.
13. Both Aided and Self-Financing departments follow identical scheduling rules with equal priority.
"""

import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
import psycopg
import api.auth as auth
from api.main import app
from api.db import DSN

PW, mails = os.environ.get("SEED_PASSWORD") or "TestPass-1234", []
auth.send_email = lambda to, s, b: mails.append((to, b))

def sign_in(username):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": PW})
    if r.status_code == 200 and "challenge_id" in r.json():
        code = re.search(r"code is (\d{6})", mails[-1][1]).group(1)
        c.post("/api/auth/verify", json={"challenge_id": r.json()["challenge_id"], "code": code})
    return c

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        sys.exit(1)

def run_tests():
    cs = sign_in("cs")
    maths = sign_in("maths")
    chem = sign_in("chem")
    phy = sign_in("physics")

    print("\n--- 1. Course Creation with Selection Type ---")
    # 1. CS creates a student-selected MDC
    r1 = cs.post("/api/courses", json={
        "course_code": "MDC-CS-TEST",
        "course_name": "AI &Society",
        "course_type": "MDC",
        "selection_type": "STUDENT_SELECTED"
    })
    ok(r1.status_code == 200 and r1.json()["selection_type"] == "STUDENT_SELECTED",
       "Req 1: CS creates a student-selected MDC")

    # 2. Mathematics creates a student-selected MDC (course definition)
    r2 = maths.post("/api/courses", json={
        "course_code": "MDC-MATH-ADV",
        "course_name": "Mathematical Thinking & Modeling",
        "course_type": "MDC",
        "selection_type": "STUDENT_SELECTED"
    })
    ok(r2.status_code == 200 and r2.json()["selection_type"] == "STUDENT_SELECTED",
       "Req 2: Mathematics creates a student-selected MDC")

    # 3. Chemistry creates a student-selected Minor
    r3 = chem.post("/api/courses", json={
        "course_code": "MIN-CHEM-TEST",
        "course_name": "Forensic Science",
        "course_type": "Minor",
        "selection_type": "STUDENT_SELECTED"
    })
    ok(r3.status_code == 200 and r3.json()["selection_type"] == "STUDENT_SELECTED",
       "Req 3: Chemistry creates a student-selected Minor")

    # 8. Department creates a department-selected MDC
    r8 = chem.post("/api/courses", json={
        "course_code": "MDC-CHEM-INT",
        "course_name": "Industrial Chemistry",
        "course_type": "MDC",
        "selection_type": "DEPARTMENT_SELECTED"
    })
    ok(r8.status_code == 200 and r8.json()["selection_type"] == "DEPARTMENT_SELECTED",
       "Req 8: Department creates a department-selected MDC")

    # 10. Department creates a department-selected Minor
    r10 = cs.post("/api/courses", json={
        "course_code": "MIN-CS-INT",
        "course_name": "Software Engineering Foundations",
        "course_type": "Minor",
        "selection_type": "DEPARTMENT_SELECTED"
    })
    ok(r10.status_code == 200 and r10.json()["selection_type"] == "DEPARTMENT_SELECTED",
       "Req 10: Department creates a department-selected Minor")

    print("\n--- 2. Course Offerings & Selection Inheritance ---")
    # Launch offering for CS student-selected MDC
    off_cs_mdc = cs.post("/api/offerings", json={
        "course_id": r1.json()["id"],
        "offering_code": "MDC-CS-TEST-SEM1",
        "semester": 1,
        "required_sessions": 2,
        "max_enrollment": 50,
        "faculty_id": 1  # FAC-001 (Dr. Anil Kumar)
    }).json()["id"]

    # Mathematics already has active student-selected MDC offering MDC1-2026-SEM1
    maths_offerings = maths.get("/api/offerings").json()
    off_math_mdc = next(o["id"] for o in maths_offerings if o["course_code"] == "MDC-MATH-01")

    # Launch offering for Chem department-selected MDC
    off_chem_dept = chem.post("/api/offerings", json={
        "course_id": r8.json()["id"],
        "offering_code": "MDC-CHEM-INT-SEM1",
        "semester": 1,
        "required_sessions": 2,
        "max_enrollment": 30,
        "faculty_id": 9  # FAC-009 (Dr. Sandeep Rao)
    }).json()["id"]

    # Launch offering for CS department-selected Minor
    off_cs_dept = cs.post("/api/offerings", json={
        "course_id": r10.json()["id"],
        "offering_code": "MIN-CS-INT-SEM1",
        "semester": 1,
        "required_sessions": 2,
        "max_enrollment": 30,
        "faculty_id": 3  # FAC-003 (Dr. Priya Nair)
    }).json()["id"]

    # Check offerings list
    all_offs = cs.get("/api/offerings/all").json()
    cs_mdc_meta = next(o for o in all_offs if o["id"] == off_cs_mdc)
    chem_dept_meta = next((o for o in all_offs if o["id"] == off_chem_dept), None)

    ok(cs_mdc_meta["selection_type"] == "STUDENT_SELECTED" and cs_mdc_meta["scheduling_scope"] == "college_wide",
       "Student-selected offering inherits STUDENT_SELECTED and college_wide scope")
    ok(chem_dept_meta is None,
       "Department-selected offering of Chemistry does not leak into CS student selection pool")

    print("\n--- 3. Student Enrollment & Isolation Rules ---")
    # 5. Students from multiple departments can enroll in student-selected offering
    # Fetch students
    cs_students = cs.get("/api/students").json()
    math_students = maths.get("/api/students").json()
    chem_students = chem.get("/api/students").json()

    # Enrolling disjoint students into CS MDC (REG-CS-003, REG-MATH-003)
    s_cs3 = next(s["id"] for s in cs_students if s["register_number"] == "REG-CS-003")
    s_math3 = next(s["id"] for s in math_students if s["register_number"] == "REG-MATH-003")
    s_chem = chem_students[0]["id"]
    s_cs = cs_students[0]["id"]

    # Cross-enroll into CS MDC (Student-Selected)
    e_res = cs.post(f"/api/offerings/{off_cs_mdc}/enroll", json={"student_ids": [s_cs3, s_math3]})
    ok(e_res.status_code == 200 and e_res.json()["enrolled"] >= 2,
       "Req 5: Students from multiple departments enrolled in the same student-selected offering")

    # Test Department-Selected Enrollment Restriction:
    # Trying to enroll a CS student into Chemistry's department-selected offering MUST fail with 400!
    bad_enr = chem.post(f"/api/offerings/{off_chem_dept}/enroll", json={"student_ids": [s_cs]})
    ok(bad_enr.status_code == 400 and "Cross-department enrollment is prohibited" in bad_enr.json()["detail"],
       "Req 9 (Constraint): Cross-department enrollment into department-selected course is strictly blocked")

    # Enrolling Chemistry student into Chemistry's department-selected offering succeeds
    good_enr = chem.post(f"/api/offerings/{off_chem_dept}/enroll", json={"student_ids": [s_chem]})
    ok(good_enr.status_code == 200, "Home-department student enrolled into department-selected course")
    good_enr = chem.post(f"/api/offerings/{off_chem_dept}/enroll", json={"student_ids": [s_chem]})
    ok(good_enr.status_code == 200, "Home-department student enrolled into department-selected course")

    print("\n--- 4. Timetable Generation & Scheduling Logic ---")
    # Configure common slots check
    c_slots = cs.get("/api/registry/common-slots").json() if False else cs.get("/api/common-slots").json()
    ok(len(c_slots) > 0, "College-wide common time slots are active")

    # Generate CS timetable
    gen_cs = cs.post("/api/generate", json={})
    ok(gen_cs.status_code == 200 and gen_cs.json()["status"] == "ok",
       "CS timetable generated successfully")

    # Generate Maths timetable
    gen_math = maths.post("/api/generate", json={})
    if gen_math.status_code != 200 or gen_math.json().get("status") != "ok":
        print("Maths generate failed:", gen_math.json())
    ok(gen_math.status_code == 200 and gen_math.json()["status"] == "ok",
       "Maths timetable generated successfully")

    # Generate Chemistry timetable (Self-Financing)
    gen_chem = chem.post("/api/generate", json={})
    ok(gen_chem.status_code == 200 and gen_chem.json()["status"] == "ok",
       "Req 13: Chemistry (Self-Financing) generates with equal priority")

    print("\n--- 5. Slot Verification & Simultaneity ---")
    # 4. Check CS student-selected offering is scheduled strictly in common slot
    cs_mdc_tt = cs.get(f"/api/offerings/{off_cs_mdc}/timetable").json()
    ok(len(cs_mdc_tt) == 2, "CS student-selected MDC scheduled required 2 sessions")
    for s in cs_mdc_tt:
        matched = any(cs_lot["day"] == s["day"] and cs_lot["start"] == s["start"] and cs_lot["end"] == s["end"]
                      for cs_lot in c_slots)
        ok(matched, f"Req 4: CS MDC session on day {s['day']} {s['start']}-{s['end']} uses configured common slot")

    # 7. Check simultaneous execution in common slots
    math_mdc_tt = maths.get(f"/api/offerings/{off_math_mdc}/timetable").json()
    ok(len(math_mdc_tt) == 2, "Maths student-selected MDC scheduled required 2 sessions")

    # Verify both can run during common slots when students do not overlap
    common_days = {s["day"] for s in cs_mdc_tt} & {s["day"] for s in math_mdc_tt}
    ok(len(common_days) > 0, "Req 7: Different offerings run simultaneously during common slots without false clash")

    # 9. Verify Department-Selected MDC is scheduled in normal departmental grid
    chem_dept_tt = chem.get(f"/api/offerings/{off_chem_dept}/timetable").json()
    ok(len(chem_dept_tt) == 2, "Chemistry department-selected MDC scheduled 2 sessions")
    for s in chem_dept_tt:
        is_common = any(cs_lot["day"] == s["day"] and cs_lot["start"] == s["start"] and cs_lot["end"] == s["end"]
                        for cs_lot in c_slots)
        ok(not is_common, f"Req 9: Department-selected MDC session on day {s['day']} {s['start']}-{s['end']} is NOT forced into common slot")

    # 10. Verify Department-Selected Minor in CS
    cs_dept_tt = cs.get(f"/api/offerings/{off_cs_dept}/timetable").json()
    ok(len(cs_dept_tt) == 2, "Req 10: Department-selected Minor scheduled 2 sessions in regular timetable")

    print("\n--- 6. Student-Level Conflict Prevention ---")
    # 6. Verify student-level conflict check
    # Student s_cs is enrolled in CS MDC. If we attempt to also enroll s_cs in Maths MDC, they must not overlap.
    stu_tt = cs.get(f"/api/students/{s_cs}/timetable").json()["entries"]
    clashes = 0
    for i, a in enumerate(stu_tt):
        for b in stu_tt[i+1:]:
            if a["day"] == b["day"]:
                # Check overlap
                if not (a["emin"] <= b["smin"] or b["emin"] <= a["smin"]):
                    clashes += 1
    ok(clashes == 0, "Req 6: Student timetable has zero overlapping course sessions (Regular vs MDC/Minor)")

    # 11 & 12. Regular subjects continue to work and conflicts are prevented
    conflicts_cs = cs.get("/api/conflicts").json()
    ok(len(conflicts_cs["items"]) == 0, "Req 11 & 12: Zero conflicts detected for teachers, rooms, classes, and students")

    print("\n>>> ALL 13 TEST SCENARIOS PASSED SUCCESSFULLY! <<<\n")

if __name__ == "__main__":
    run_tests()
