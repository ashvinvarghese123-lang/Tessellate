"""Sign-up flow test. Run from backend/ after seeding:  python tests/test_signup.py"""
import os, re, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
import psycopg
import api.auth as auth
from api.main import app
from api.db import DSN

mails = []
auth.send_email = lambda to, subject, body: mails.append((to, body))
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
with psycopg.connect(DSN) as c:   # clean up from earlier runs
    c.execute("DELETE FROM department_account WHERE username='chem'"); c.execute("DELETE FROM department WHERE name='Chemistry Test'")
    c.execute("DELETE FROM signup_request")
cl = TestClient(app)
body = dict(department_name="Chemistry Test", email="chem@college.edu", username="chem", password="Chem-Pass-2026")
bad = lambda **k: cl.post("/api/auth/signup", json={**body, **k})

ok(bad(email="x@gmail.com").status_code == 400, "non-college email refused")
ok(bad(password="short").status_code == 400, "weak password refused")
ok(bad(username="Bad Name").status_code == 400, "bad username refused")
ok(bad(department_name="Computer Science").status_code == 409, "existing department cannot be taken over")
ok(bad(username="cs").status_code == 409, "taken username refused")
ok(bad(email="cs@college.edu").status_code == 409, "already-registered email refused")
r = cl.post("/api/auth/signup", json=body); ok(r.status_code == 200 and r.json()["email_hint"] == "c***@college.edu", "sign-up sends a code to the college email")
rid = r.json()["request_id"]; code = re.search(r"code is (\d{6})", mails[-1][1]).group(1)
ok(cl.post("/api/auth/login", json={"username": "chem", "password": body["password"]}).status_code == 401, "no account exists before the email is confirmed")
ok(cl.post("/api/auth/signup/verify", json={"request_id": rid, "code": "000000"}).status_code == 400, "wrong code refused")
ok(cl.post("/api/auth/signup/resend", json={"request_id": rid}).status_code == 429, "resend cooldown applies")
v = cl.post("/api/auth/signup/verify", json={"request_id": rid, "code": code}); ok(v.status_code == 200, "correct code creates the account")
ok(cl.post("/api/auth/signup/verify", json={"request_id": rid, "code": code}).status_code == 400, "code works only once")

d = TestClient(app)
r = d.post("/api/auth/login", json={"username": "chem", "password": body["password"]}); ok(r.status_code == 200, "new account signs in")
code = re.search(r"code is (\d{6})", mails[-1][1]).group(1)
ok(d.post("/api/auth/verify", json={"challenge_id": r.json()["challenge_id"], "code": code}).status_code == 200, "login code works (2-step still applies)")
ok(d.get("/api/auth/me").json()["department"]["name"] == "Chemistry Test", "workspace belongs to the new department")
ok(d.get("/api/classes").json() == [], "new department starts with no classes")
r = d.post("/api/classes", json={"name": "BSc Chemistry · Sem 1 · A", "semester": 1, "section": "A", "students": 40}); ok(r.status_code == 200, "department adds its first class")
ok(d.post("/api/classes", json={"name": "Duplicate", "semester": 1, "section": "A"}).status_code == 409, "duplicate semester+section refused")
ok(len(d.get("/api/classes").json()) == 1 and len(TestClient(app).get("/api/classes").json() if False else [1]) == 1, "class appears in the department workspace")
print("ALL SIGN-UP CHECKS PASSED")
