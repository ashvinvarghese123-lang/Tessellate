"""Registry test. Needs the seeded DB:  SEED_PASSWORD=TestPass-1234 python db/seed.py && python tests/test_registry.py"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
import api.auth as auth, api.registry as reg
from api.main import app
PW, mails = "TestPass-1234", []
auth.send_email = lambda to, s, b: mails.append((to, b)); reg.send_email = auth.send_email
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
code = lambda: re.search(r"code is (\d{6})", mails[-1][1]).group(1)

R = TestClient(app)
ok(R.post("/api/registry/auth/login", json={"username": "registry", "password": "wrong"}).status_code == 401, "wrong registry password refused")
ok(R.get("/api/registry/overview").status_code == 401, "no data before signing in")
r = R.post("/api/registry/auth/login", json={"username": "registry", "password": PW}); ok(r.json()["email_hint"] == "r***@college.edu" and mails[-1][0] == "registry@college.edu", "code sent to the registry's registered email")
ok(R.post("/api/registry/auth/verify", json={"challenge_id": r.json()["challenge_id"], "code": "000000"}).status_code == 400, "wrong code refused")
ok(R.post("/api/registry/auth/verify", json={"challenge_id": r.json()["challenge_id"], "code": code()}).status_code == 200, "correct code signs in")
ok(R.get("/api/registry/auth/me").json()["username"] == "registry", "registry session works")

D = TestClient(app); r = D.post("/api/auth/login", json={"username": "cs", "password": PW})
D.post("/api/auth/verify", json={"challenge_id": r.json()["challenge_id"], "code": code()})
ok(D.get("/api/registry/overview").status_code == 401, "a department login cannot open the registry")
ok(R.get("/api/dashboard").status_code == 401 and R.post("/api/generate", json={}).status_code == 401, "the registry cannot open department workspaces or generate timetables")

# departments
r = R.post("/api/registry/departments", json={"name": "Chemistry"}); ok(r.status_code == 200, "registry creates a department")
did = r.json()["id"]; ok(R.post("/api/registry/departments", json={"name": "chemistry"}).status_code == 409, "duplicate department refused")
ok(R.put(f"/api/registry/departments/{did}", json={"name": "Chemistry Sciences"}).status_code == 200, "rename department")
cs_id = next(x["id"] for x in R.get("/api/registry/departments").json() if x["name"] == "Computer Science")
ok(R.delete(f"/api/registry/departments/{cs_id}").status_code == 409, "department with an account cannot be deleted")
# faculty
r = R.post("/api/registry/faculty", json={"name": "Dr. Reg Teacher", "home_department_id": did, "designation": "Professor", "email": "reg@college.edu", "max_weekly_sessions": 10}); ok(r.status_code == 200, "registry adds faculty to any department: " + r.json()["faculty_code"])
fid = r.json()["id"]
ok(any(f["id"] == fid and not f["editable"] for f in D.get("/api/faculty").json()), "CS (logged in) immediately sees the new teacher")
ok(R.put(f"/api/registry/faculty/{fid}", json={"name": "Dr. Reg Teacher", "home_department_id": cs_id, "max_weekly_sessions": 10}).status_code == 200, "registry moves a teacher to another department")
ok(next(f for f in D.get("/api/faculty").json() if f["id"] == fid)["editable"], "after the move CS can edit that teacher")
# classes
r = R.post("/api/registry/classes", json={"name": "BSc Chem · Sem 1 · A", "department_id": did, "semester": 1, "section": "A", "students": 45}); ok(r.status_code == 200, "registry adds a class for a department")
cid = r.json()["id"]; ok(R.post("/api/registry/classes", json={"name": "Dup", "department_id": did, "semester": 1, "section": "A"}).status_code == 409, "duplicate semester+section refused")
ok(R.put(f"/api/registry/classes/{cid}", json={"name": "BSc Chem · Sem 1 · A", "department_id": cs_id}).status_code == 400, "class cannot be moved between departments")
ok(R.put(f"/api/registry/classes/{cid}", json={"name": "BSc Chemistry · Sem 1 · A", "department_id": did, "students": 50}).status_code == 200, "edit class")
# rooms
r = R.post("/api/registry/rooms", json={"name": "Chem Lab", "room_type": "Laboratory", "capacity": 30}); ok(r.status_code == 200, "registry adds a laboratory"); rid = r.json()["id"]
ok(any(x["name"] == "Chem Lab" for x in D.get("/api/rooms").json()), "departments immediately see the new laboratory")
ok(R.post("/api/registry/rooms", json={"name": "Chem Lab", "room_type": "Laboratory"}).status_code == 409, "duplicate room refused")
ok(R.post("/api/registry/rooms", json={"name": "X", "room_type": "Garage"}).status_code == 400, "invalid room type refused")
# protections once the CS timetable exists
D.post("/api/generate", json={})
used = next(x for x in R.get("/api/registry/rooms").json() if x["sessions"] > 0)
ok(R.delete(f"/api/registry/rooms/{used['id']}").status_code == 409, "a room in use by scheduled sessions cannot be deleted")
anil = next(f for f in R.get("/api/registry/faculty").json() if f["name"] == "Dr. Anil Kumar")
r = R.put(f"/api/registry/faculty/{anil['id']}", json={"name": "Dr. Anil Kumar", "home_department_id": anil["home_department_id"], "max_weekly_sessions": 1}); ok(r.status_code == 409, "cannot set a limit below scheduled sessions")
ok(R.delete(f"/api/registry/faculty/{anil['id']}").status_code == 409, "cannot remove a teacher departments still use")
cs_class = next(c for c in R.get("/api/registry/classes").json() if c["department"] == "Computer Science")
ok(R.delete(f"/api/registry/classes/{cs_class['id']}").status_code == 409, "cannot delete a class that has subjects")
# cleanup + history
ok(R.delete(f"/api/registry/classes/{cid}").status_code == 200 and R.delete(f"/api/registry/rooms/{rid}").status_code == 200 and R.delete(f"/api/registry/faculty/{fid}").status_code == 200, "unused records can be deleted")
ok(R.delete(f"/api/registry/departments/{did}").status_code == 200, "empty department without account can be deleted")
ok(any("Registry" in (a["reason"] or "") for a in D.get("/api/audit").json()), "departments see registry changes in their own history")
ok(R.post("/api/registry/auth/logout").status_code == 200 and R.get("/api/registry/overview").status_code == 401, "logout ends the registry session")
print("ALL REGISTRY CHECKS PASSED")
