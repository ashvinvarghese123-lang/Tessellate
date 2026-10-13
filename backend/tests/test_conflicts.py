"""Rooms off + clear conflicts. Needs the seeded DB:  SEED_PASSWORD=TestPass-1234 python db/seed.py && python tests/test_conflicts.py"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import psycopg
from fastapi.testclient import TestClient
import api.auth as auth
from api.main import app
from api.db import DSN
PW, mails = "TestPass-1234", []
auth.send_email = lambda to, s, b: mails.append((to, b))
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
def sign_in(u):
    c = TestClient(app); r = c.post("/api/auth/login", json={"username": u, "password": PW})
    c.post("/api/auth/verify", json={"challenge_id": r.json()["challenge_id"], "code": re.search(r"code is (\d{6})", mails[-1][1]).group(1)}); return c

with psycopg.connect(DSN) as c:      # exactly the live site's situation: no rooms exist at all
    c.execute("UPDATE class SET home_room_id=NULL"); c.execute("DELETE FROM room_availability"); c.execute("DELETE FROM room")
cs = sign_in("cs")
ok(cs.get("/api/auth/me").json()["features"]["rooms"] is False, "rooms are switched off")
ok(cs.get("/api/rooms").status_code == 404, "the rooms feature is unavailable")
r = cs.post("/api/generate", json={}); ok(r.json()["status"] == "ok", "with no rooms in the college, a timetable is still made")
cid = cs.get("/api/classes").json()[0]["id"]; tt = cs.get(f"/api/timetable/{cid}").json()
ok(tt and all(e["room"] is None for e in tt), "sessions have no room")
ok(cs.get("/api/conflicts").json()["items"] == [], "a good timetable shows no conflicts")
ok(cs.post("/api/allocations", json={"class_id": cid, "subject": "Lab work", "faculty_id": 1, "sessions": 2, "lab": "Computer lab"}).status_code == 200, "a subject is added even if it asked for a lab")
ok(cs.post("/api/generate", json={}).json()["status"] == "ok", "lab requests are ignored while rooms are off")

# one real problem: a teacher given far more sessions than they have free periods
fac = {f["name"]: f["id"] for f in cs.get("/api/faculty").json()}
for i in range(6):
    cs.post("/api/allocations", json={"class_id": cid, "subject": f"Extra {i}", "faculty_id": fac["Dr. Anil Kumar"], "sessions": 5})
r = cs.post("/api/generate", json={}).json()
ok(r["status"] == "impossible" and 1 <= len(r["issues"]) <= 3, f"one cause gives a short list, not a pile: {len(r['issues'])} issue(s)")
ok(all(i["issue"] and i["fix"] and len(i["fix"]) < 140 for i in r["issues"]), "every issue has one short fix")
print("   issue:", r["issues"][0]["issue"]); print("   fix:  ", r["issues"][0]["fix"])
c2 = cs.get("/api/conflicts").json()
ok(c2["items"] and "Dr. Anil Kumar" in c2["items"][0]["issue"], "the Conflicts page names the real issue")
ok(not any("Missing sessions" in i["issue"] for i in c2["items"]), "no 'missing sessions' pile-up")
print("ALL CONFLICT CHECKS PASSED")
