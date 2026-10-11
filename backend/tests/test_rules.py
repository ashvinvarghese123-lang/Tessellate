"""Department timing and rules, end to end. Needs the seeded DB:  SEED_PASSWORD=TestPass-1234 python db/seed.py && python tests/test_rules.py"""
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
P = lambda a, b: {"start": a, "end": b}
MIDS = [P("09:30", "10:30"), P("10:45", "11:45"), P("12:00", "13:00"), P("14:30", "15:30")]
body = lambda **k: {**dict(days=[0, 1, 2, 3], periods=MIDS, rules={"spread": {"mode": "require", "max_per_day": 1}}, free=[[3, 3]]), **k}

g = maths.get("/api/settings").json()
ok(g["config"]["saved"] is False and len(g["config"]["periods"]) == 6 and all(r["mode"] == "off" for r in g["config"]["rules"].values()) if g["config"]["rules"] else g["config"]["rules"] == {}, "a new department starts with no rules chosen (only the clash checks)")
ok(len(g["rule_defs"]) >= 8, "the rule options are offered to the department")
bad = lambda **k: maths.put("/api/settings", json=body(**k)).status_code
ok(bad(periods=[P("09:00", "10:00"), P("09:30", "10:30")]) == 400, "overlapping periods refused")
ok(bad(periods=[P("10:00", "09:00")]) == 400, "end before start refused")
ok(bad(days=[]) == 400, "no working days refused")
ok(bad(rules={"balance": {"mode": "require"}}) == 400, "a rule that cannot be Required is refused")
ok(bad(rules={"spread": {"mode": "require", "max_per_day": 99}}) == 400, "rule value out of range refused")

ok(cs.post("/api/generate", json={}).json()["status"] == "ok", "CS generates with the default period times")
ok(maths.put("/api/settings", json=body()).status_code == 200, "Maths saves its own days, period times, a Required rule and a free period")
s = maths.get("/api/settings").json(); ok(s["config"]["saved"] and s["config"]["days"] == [0, 1, 2, 3] and len(s["config"]["periods"]) == 4 and s["stale"] is False, "settings are stored")
ok(len(cs.get("/api/settings").json()["config"]["periods"]) == 6 and cs.get("/api/settings").json()["config"]["saved"] is False, "another department's settings are untouched")
r = maths.post("/api/generate", json={}); ok(r.status_code == 200 and r.json()["status"] == "ok" and r.json()["rules_used"] >= 1, "Maths generates on its own timing: quality %s" % r.json().get("quality"))

mc = maths.get("/api/classes").json()[0]["id"]; tt = maths.get(f"/api/timetable/{mc}").json()
ok(all(e["start"] in ("09:30", "10:45", "12:00", "14:30") for e in tt), "every Maths session uses Maths' own period times")
ok(all(e["day"] <= 3 for e in tt), "only Maths' working days are used")
ok(not any((e["day"], e["period"]) == (3, 3) for e in tt), "the period Maths chose to keep free is empty")
from collections import Counter
ok(max(Counter((e["subject"], e["day"]) for e in tt).values()) == 1, "Required rule held: a subject at most once a day")

fac = maths.get("/api/faculty").json(); clash = 0
for f in fac:
    es = maths.get(f"/api/faculty/{f['id']}/timetable").json()
    for i, a in enumerate(es):
        for b in es[i + 1:]:
            if a["day"] == b["day"] and a["smin"] < b["emin"] and b["smin"] < a["emin"]: clash += 1
ok(clash == 0, "no teacher is double-booked in REAL time across CS (9:00 grid) and Maths (9:30 grid)")

anil = next(f["id"] for f in fac if f["name"] == "Dr. Anil Kumar")
av = maths.get(f"/api/faculty/{anil}/availability").json()
ok({a["start"] for a in av} == {"09:30", "10:45", "12:00", "14:30"} and any(a["state"] == "busy" for a in av), "teacher availability is shown on the viewing department's own periods")
mine = next((e for e in tt if e["teacher"] == "Dr. Anil Kumar"), None)
msgs = {maths.post(f"/api/entries/{mine['id']}/check", json={"day": d, "period": p}).json()["message"] for d in range(4) for p in range(4)}
ok(any("already teaching" in m for m in msgs), "a move that overlaps another department's session in real time is refused")
ok(any("keep that period free" in m for m in msgs), "a move into a period the department keeps free is refused")
ok("one of your teaching periods" in maths.post(f"/api/entries/{mine['id']}/check", json={"day": 4, "period": 0}).json()["message"], "a non-working day is refused")

r = maths.put("/api/settings", json=body(periods=MIDS[:3] + [P("14:00", "15:00")])); ok(r.json()["stale"] is True, "changing the timing after generating is flagged, so the department knows to generate again")
ok(maths.post("/api/generate", json={}).json()["status"] == "ok" and maths.get("/api/settings").json()["stale"] is False, "generating again clears the notice")
ok(cs.get(f"/api/timetable/{maths.get('/api/classes').json()[0]['id']}").status_code == 403, "CS still cannot open Maths' timetable")
ok(maths.put("/api/settings", json=body(rules={"class_day_max": {"mode": "require", "max": 1}})).status_code == 200, "a too-strict rule can be saved")
r = maths.post("/api/generate", json={}).json(); ok(r["status"] == "impossible" and any("Required" in p for p in r.get("problems", [])), "too-strict rules: plain explanation naming the Required rule, no bad timetable")
print("ALL RULES CHECKS PASSED")
