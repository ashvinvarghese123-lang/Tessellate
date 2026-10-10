"""Faculty editing test. Needs the seeded DB:  SEED_PASSWORD=TestPass-1234 python db/seed.py && python tests/test_faculty.py"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
import api.auth as auth
from api.main import app
PW, mails = "TestPass-1234", []
auth.send_email = lambda to, s, b: mails.append((to, b))
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
def sign_in(u):
    c = TestClient(app); r = c.post("/api/auth/login", json={"username": u, "password": PW})
    c.post("/api/auth/verify", json={"challenge_id": r.json()["challenge_id"], "code": re.search(r"code is (\d{6})", mails[-1][1]).group(1)}); return c
cs, maths = sign_in("cs"), sign_in("maths")
cs.post("/api/generate", json={})
lst = cs.get("/api/faculty").json(); by = {f["name"]: f for f in lst}
ok(by["Dr. Anil Kumar"]["editable"] and not by["Dr. Rahul Menon"]["editable"], "only your own department's teachers are editable")
r = cs.post("/api/faculty", json={"name": "Dr. Test Teacher", "designation": "Lecturer", "email": "test@college.edu", "max_weekly_sessions": 12}); ok(r.status_code == 200 and r.json()["faculty_code"].startswith("FAC-"), "add teacher gets a new global ID: " + r.json()["faculty_code"])
fid = r.json()["id"]
ok(cs.post("/api/faculty", json={"name": "dr. test teacher"}).status_code == 409, "duplicate name in the same department refused")
ok(any(f["id"] == fid for f in maths.get("/api/faculty").json()), "other departments can see and choose the new teacher")
ok(maths.put(f"/api/faculty/{fid}", json={"name": "Hacked"}).status_code == 403, "another department cannot edit this teacher")
ok(maths.delete(f"/api/faculty/{fid}").status_code == 403, "another department cannot remove this teacher")
ok(cs.put(f"/api/faculty/{fid}", json={"name": "Dr. Test T.", "designation": "Reader", "max_weekly_sessions": 14}).status_code == 200, "edit own teacher")
ok(cs.put(f"/api/faculty/{fid}", json={"name": "X", "max_weekly_sessions": 14}).status_code == 400, "invalid name refused")
anil = by["Dr. Anil Kumar"]["id"]; used = by["Dr. Anil Kumar"]["sessions"]
r = cs.put(f"/api/faculty/{anil}", json={"name": "Dr. Anil Kumar", "max_weekly_sessions": max(1, used - 1)}); ok(r.status_code == 409, "limit below current sessions refused: " + r.json()["detail"])
ok(cs.put(f"/api/faculty/{fid}/unavailable", json={"slots": [[0, 0], [0, 1]]}).status_code == 200, "mark periods unavailable")
av = cs.get(f"/api/faculty/{fid}/availability").json(); ok(sum(a["state"] == "unavailable" for a in av) == 2, "unavailable periods show in the shared view")
busy = next(a for a in cs.get(f"/api/faculty/{anil}/availability").json() if a["state"] == "busy")
r = cs.put(f"/api/faculty/{anil}/unavailable", json={"slots": [[busy["day"], busy["period"]]]}); ok(r.status_code == 409 and "Move that session first" in r.json()["detail"], "cannot block a period while teaching: " + r.json()["detail"])
ok(cs.put(f"/api/faculty/{fid}/unavailable", json={"slots": [[9, 9]]}).status_code == 400, "non-teaching period refused")
ok(cs.delete(f"/api/faculty/{anil}").status_code == 409, "cannot remove a teacher who still has subjects")
ok(cs.delete(f"/api/faculty/{fid}").status_code == 200 and not any(f["id"] == fid for f in cs.get("/api/faculty").json()), "unassigned teacher can be removed")
print("ALL FACULTY CHECKS PASSED")
