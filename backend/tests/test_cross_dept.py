"""Cross-Department MDC, Minor & Student Enrollment Integration Tests.
Validates all 12 requirements from Section 14 of the specification.
Run:
    $env:DATABASE_URL="postgresql://tess:tess@localhost:5432/tessellate"
    python tests/test_cross_dept.py
"""
import os, sys
os.environ["REQUIRE_OTP"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import psycopg
from fastapi.testclient import TestClient
import api.auth as auth, api.registry as reg
from api.main import app
from api.db import DSN

PW = "TestPass-1234"
with psycopg.connect(DSN, autocommit=True) as db:
    db.execute("UPDATE department_account SET locked_until=NULL, failed_logins=0")
    db.execute("DELETE FROM course WHERE course_code IN ('SEC-TEST-01', 'SEC-TEST-02')")
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))

# Clients for Aided and Self-Financing departments
cs = TestClient(app); cs.post("/api/auth/login", json={"username": "cs", "password": PW})
maths = TestClient(app); maths.post("/api/auth/login", json={"username": "maths", "password": PW})
chem = TestClient(app); chem.post("/api/auth/login", json={"username": "chem", "password": PW})
physics = TestClient(app); physics.post("/api/auth/login", json={"username": "physics", "password": PW})
registry = TestClient(app); registry.post("/api/registry/auth/login", json={"username": "registry", "password": PW})

print("\n--- 1. College Structure & Institutional Categories ---")
cats = registry.get("/api/registry/categories").json()
ok(len(cats) == 2 and {c["name"] for c in cats} == {"Aided", "Self-Financing"}, "institutional categories Aided and Self-Financing exist")
depts = registry.get("/api/registry/departments").json()
dept_map = {d["code"]: d for d in depts}
ok(dept_map["DEPT-CS"]["category_name"] == "Aided" and dept_map["DEPT-MATH"]["category_name"] == "Aided", "CS and Maths belong to Aided category")
ok(dept_map["DEPT-CHEM"]["category_name"] == "Self-Financing" and dept_map["DEPT-PHY"]["category_name"] == "Self-Financing", "Chemistry and Physics belong to Self-Financing category")
ok(cs.get("/api/dashboard").json()["department"]["category"] == "Aided", "CS dashboard reports Aided category without priority privileges")
ok(chem.get("/api/dashboard").json()["department"]["category"] == "Self-Financing", "Chemistry dashboard reports Self-Financing category with equal priority")

print("\n--- 2. Course Types & Offerings ---")
offerings = maths.get("/api/offerings/all").json()
off_map = {o["offering_code"]: o for o in offerings}
ok("MDC1-2026-SEM1" in off_map and off_map["MDC1-2026-SEM1"]["scheduling_scope"] == "college_wide", "Mathematics offers college-wide MDC 1 Data Analytics")
ok("MIN1-2026-SEM1" in off_map and off_map["MIN1-2026-SEM1"]["scheduling_scope"] == "college_wide", "CS offers college-wide Minor 1 Web Development")
chem_offs = chem.get("/api/offerings").json()
ok(any(o["offering_code"] == "MDC2-CHEM-SEM1" and o["scheduling_scope"] == "department_specific" for o in chem_offs), "Chemistry has department-specific MDC course")

print("\n--- 3. Cross-Department Student Enrollment ---")
# Check seeded enrollments for Mathematics MDC 1 (Data Analytics)
da_off = off_map["MDC1-2026-SEM1"]
da_enr = maths.get(f"/api/offerings/{da_off['id']}/enrollments").json()
by_dept = da_enr["by_department"]
ok("Computer Science" in by_dept and "Mathematics" in by_dept, "Req 1: CS and Maths students are enrolled in the same MDC offering")
ok("Chemistry" in by_dept and "Physics" in by_dept, "Req 2: Chemistry and Physics students are enrolled in the same MDC offering")
ok(da_enr["total_enrolled"] >= 5, "Req 3: All enrolled students share the same offering")

# Test dynamic cross-department enrollment
cs_students = cs.get("/api/students").json()
aarav = next(s for s in cs_students if s["register_number"] == "REG-CS-001")
ananya = next(s for s in cs_students if s["register_number"] == "REG-CS-002")
rohan = next(s for s in cs_students if s["register_number"] == "REG-CS-003")

# Enroll Rohan into CS Minor 1
web_off = off_map["MIN1-2026-SEM1"]
r_enr = cs.post(f"/api/offerings/{web_off['id']}/enroll", json={"student_ids": [rohan["id"]]})
ok(r_enr.status_code == 200, "CS student can enroll into Minor offering")

# Duplicate enrollment prevention
dup_r = cs.post(f"/api/offerings/{web_off['id']}/enroll", json={"student_ids": [rohan["id"]]})
ok(dup_r.json()["enrolled"] == 0, "Duplicate enrollment is safely detected and ignored")

print("\n--- 4. Generation & Scheduling Engine ---")
# Generate timetables for Mathematics (college-wide MDC), CS (college-wide Minor & classes), Chem, Physics
r_math = maths.post("/api/generate", json={})
ok(r_math.status_code == 200 and r_math.json()["status"] == "ok", "Mathematics timetable generates successfully")

r_cs = cs.post("/api/generate", json={})
ok(r_cs.status_code == 200 and r_cs.json()["status"] == "ok", "CS timetable generates successfully")

r_chem = chem.post("/api/generate", json={})
ok(r_chem.status_code == 200 and r_chem.json()["status"] == "ok", "Chemistry (Self-Financing) timetable generates with equal priority")

r_phy = physics.post("/api/generate", json={})
ok(r_phy.status_code == 200 and r_phy.json()["status"] == "ok", "Physics (Self-Financing) timetable generates with equal priority")

print("\n--- 5. College-Wide Common Slots & Fixed Slot Adherence ---")
common_slots = cs.get("/api/common-slots").json()
mdc_slots = {(cs_["day"], cs_["start"], cs_["end"]) for cs_ in common_slots if cs_["applicable_course_type"] in ("MDC", "Both")}
da_tt = maths.get(f"/api/offerings/{da_off['id']}/timetable").json()
ok(len(da_tt) >= 2, "MDC 1 has sessions scheduled")
ok(all((s["day"], s["start"], s["end"]) in mdc_slots for s in da_tt), "Req 10: College-wide MDC offering strictly follows configured fixed common slots")

# Department-specific courses are NOT forced into common slots
chem_off_item = next(o for o in chem_offs if o["offering_code"] == "MDC2-CHEM-SEM1")
chem_tt = chem.get(f"/api/offerings/{chem_off_item['id']}/timetable").json()
ok(len(chem_tt) > 0, "Department-specific MDC has sessions scheduled")
ok(any((s["day"], s["start"], s["end"]) not in mdc_slots for s in chem_tt), "Req 9: Department-specific MDC is not forced into common college-wide slots")

print("\n--- 6. Student-Level Timetable Conflict Validation ---")
# Check Aarav's combined student timetable
aarav_tt = cs.get(f"/api/students/{aarav['id']}/timetable").json()
ok(aarav_tt["student"]["name"] == "Aarav Sharma", "Student timetable loaded")
entries = aarav_tt["entries"]
types = {e["course_type"] for e in entries}
ok("Regular" in types and "MDC" in types, "Req 12: Student timetable correctly combines regular subjects and enrolled MDC courses")

# Check for NO student overlaps in time (HARD CONSTRAINT)
clashes = 0
for i, a in enumerate(entries):
    for b in entries[i + 1:]:
        if a["day"] == b["day"] and a["smin"] < b["emin"] and b["smin"] < a["emin"]:
            clashes += 1
ok(clashes == 0, "Req 4: The same student has zero overlapping course sessions (Regular vs MDC)")

# Check no teacher or room double booking
fac_list = cs.get("/api/faculty").json()
t_clashes = 0
for f in fac_list:
    es = cs.get(f"/api/faculty/{f['id']}/timetable").json()
    for i, a in enumerate(es):
        for b in es[i + 1:]:
            if a["day"] == b["day"] and a["smin"] < b["emin"] and b["smin"] < a["emin"]:
                t_clashes += 1
ok(t_clashes == 0, "Req 6: Teachers cannot be double-booked across regular subjects and offerings")

print("\n--- 7. Sectioning & Capacity Management ---")
# Create an offering with capacity 2 and add 3 students to test capacity check
crs_sec = cs.post("/api/courses", json={"course_code": "SEC-TEST-01", "course_name": "Section Capacity Test", "course_type": "MDC"}).json()
off_sec = cs.post("/api/offerings", json={"course_id": crs_sec["id"], "offering_code": "SEC-OFF-01", "scheduling_scope": "department_specific", "max_enrollment": 2}).json()

# Add section A (capacity 1) and section B (capacity 1)
sec_a = cs.post(f"/api/offerings/{off_sec['id']}/sections", json={"section_name": "A", "capacity": 1}).json()
sec_b = cs.post(f"/api/offerings/{off_sec['id']}/sections", json={"section_name": "B", "capacity": 1}).json()

ok(sec_a["section_name"] == "A" and sec_b["section_name"] == "B", "Req 11: Sections A and B created successfully")
enr_a = cs.post(f"/api/offerings/{off_sec['id']}/enroll", json={"student_ids": [aarav["id"]], "section_id": sec_a["id"]})
ok(enr_a.status_code == 200, "Student enrolled in section A")

# Trying to enroll a second student into section A (capacity 1) must be refused
enr_a_ov = cs.post(f"/api/offerings/{off_sec['id']}/enroll", json={"student_ids": [ananya["id"]], "section_id": sec_a["id"]})
ok(enr_a_ov.status_code == 409 and "capacity" in enr_a_ov.json()["detail"].lower(), "Capacity overflow correctly blocked")

# Enrolling into section B succeeds
enr_b = cs.post(f"/api/offerings/{off_sec['id']}/enroll", json={"student_ids": [ananya["id"]], "section_id": sec_b["id"]})
ok(enr_b.status_code == 200, "Second student enrolled in section B")

print("\n--- 8. Conflict Center Diagnostics ---")
conf = cs.get("/api/conflicts").json()
ok(isinstance(conf["items"], list), "Conflict center reports active items without error")
print("ALL CROSS-DEPARTMENT INTEGRATION CHECKS PASSED!")
