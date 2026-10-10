"""End-to-end API test (needs the seeded database). Run from backend/:  SEED_PASSWORD=TestPass-1234 python db/seed.py && python tests/test_api.py"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
import api.auth as auth
from api.main import app

PW, mails = "TestPass-1234", []
auth.send_email = lambda to, subject, body: mails.append((to, body))      # no real email in tests
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))

def sign_in(user):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": user, "password": PW}); assert r.status_code == 200, r.text
    code = re.search(r"code is (\d{6})", mails[-1][1]).group(1)
    r2 = c.post("/api/auth/verify", json={"challenge_id": r.json()["challenge_id"], "code": code}); assert r2.status_code == 200, r2.text
    return c, r.json(), code

c0 = TestClient(app)
r = c0.post("/api/auth/login", json={"username": "cs", "password": "wrong"})
ok(r.status_code == 401 and "incorrect" in r.json()["detail"], "wrong password gives a generic message")
r = c0.post("/api/auth/login", json={"username": "nobody", "password": "x"})
ok(r.status_code == 401 and "incorrect" in r.json()["detail"], "unknown username gives the same message")
r = c0.post("/api/auth/login", json={"username": "cs", "password": PW}); ch = r.json()
ok(ch["email_hint"] == "c***@college.edu" and mails[-1][0] == "cs@college.edu", "code goes to the registered email; address is masked")
ok(c0.post("/api/auth/verify", json={"challenge_id": ch["challenge_id"], "code": "000000"}).status_code == 400, "wrong code is refused")
ok(c0.post("/api/auth/resend", json={"challenge_id": ch["challenge_id"]}).status_code == 429, "resend cooldown applies")
ok(c0.get("/api/auth/me").status_code == 401, "no access before the code is entered")
code = re.search(r"code is (\d{6})", mails[-1][1]).group(1)
ok(c0.post("/api/auth/verify", json={"challenge_id": ch["challenge_id"], "code": code}).status_code == 200, "correct code signs in")
ok(c0.post("/api/auth/verify", json={"challenge_id": ch["challenge_id"], "code": code}).status_code == 400, "a code works only once")
ok(c0.get("/api/auth/me").json()["department"]["name"] == "Computer Science", "department comes from the account")

cs = c0
maths, _, _ = sign_in("maths"); phy, _, _ = sign_in("physics")
for n, cl in (("Computer Science", cs), ("Mathematics", maths), ("Physics", phy)):
    r = cl.post("/api/generate", json={}); ok(r.status_code == 200 and r.json()["status"] == "ok", f"{n} generates its timetable: quality {r.json().get('quality')}")

my = maths.get("/api/classes").json(); csc = cs.get("/api/classes").json()
ok(len(my) == 1 and my[0]["name"].startswith("BSc Maths"), "Mathematics sees only its own classes")
ok(maths.get(f"/api/timetable/{csc[0]['id']}").status_code == 403, "Mathematics cannot open a CS class timetable")
ok(maths.post("/api/allocations", json={"class_id": csc[0]["id"], "subject": "X", "faculty_id": 1, "sessions": 1}).status_code == 403, "Mathematics cannot add subjects to CS")

fac = {f["name"]: f["id"] for f in maths.get("/api/faculty").json()}
av = maths.get(f"/api/faculty/{fac['Dr. Anil Kumar']}/availability").json()
busy = [a for a in av if a["state"] == "busy"]
ok(busy and "Currently scheduled in" in busy[0]["reason"], f"Maths sees Dr. Anil busy elsewhere: {busy[0]['reason']}")

tt = maths.get(f"/api/timetable/{my[0]['id']}").json()
e = next(x for x in tt if x["teacher"] == "Dr. Anil Kumar")
other = next((b for b in busy if (b["day"], b["period"]) not in {(x["day"], x["period"]) for x in tt}), None)
if other:   # (on a rare random schedule the Maths class is busy at every one of Dr. Anil's other slots; then this one check is skipped)
    r = maths.post(f"/api/entries/{e['id']}/move", json={"day": other["day"], "period": other["period"]})
    ok(r.status_code == 409 and "already teaching" in r.json()["detail"], f"clashing move blocked: {r.json()['detail']}")
else:
    print("SKIP clashing-move check (random schedule left no free clashing slot)")
ok(cs.post(f"/api/entries/{e['id']}/move", json={"day": 0, "period": 0}).status_code == 403, "CS cannot edit a Maths session")

ok(maths.put("/api/status", json={"status": "under_review"}).status_code == 200, "status moves Draft to Under review")
ok(maths.put("/api/status", json={"status": "frozen"}).status_code == 400, "invalid status jump refused")

ok(maths.post("/api/auth/change-password", json={"current": PW, "new": "short"}).status_code == 400, "weak new password refused")
ok(maths.post("/api/auth/change-password", json={"current": PW, "new": "NewPass-98765"}).status_code == 200, "password change works")
ok(maths.post("/api/auth/logout").status_code == 200 and maths.get("/api/auth/me").status_code == 401, "logout ends the session")
r = c0.post("/api/auth/login", json={"username": "maths", "password": "NewPass-98765"}); ok(r.status_code == 200, "new password signs in")
for i in range(5): TestClient(app).post("/api/auth/login", json={"username": "physics", "password": "bad"})
ok(TestClient(app).post("/api/auth/login", json={"username": "physics", "password": PW}).status_code == 429, "account locks after repeated wrong passwords")
print("ALL API CHECKS PASSED")
