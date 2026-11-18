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
    c.execute("DELETE FROM login_audit WHERE account_id IN (SELECT id FROM department_account WHERE username='biotest')")
    c.execute("DELETE FROM department_account WHERE username='biotest'")
    c.execute("DELETE FROM department WHERE name='Biotech Test'")
cl = TestClient(app)
body = dict(department_name="Biotech Test", email="biotest@college.edu", username="biotest", password="Bio-Pass-2026")
bad = lambda **k: cl.post("/api/auth/signup", json={**body, **k})

ok(bad(email="x@gmail.com").status_code == 400, "non-college email refused")
ok(bad(password="short").status_code == 400, "weak password refused")
ok(bad(username="Bad Name").status_code == 400, "bad username refused")
ok(bad(department_name="Computer Science").status_code == 409, "existing department cannot be taken over")
ok(bad(username="cs").status_code == 409, "taken username refused")
ok(bad(email="cs@college.edu").status_code == 409, "already-registered email refused")
r = cl.post("/api/auth/signup", json=body); ok(r.status_code == 200 and r.json().get("created") is True, "sign-up directly creates account")

d = TestClient(app)
r = d.post("/api/auth/login", json={"username": "biotest", "password": body["password"]}); ok(r.status_code == 200 and r.json().get("signed_in") is True, "new account signs in directly")
ok(d.get("/api/auth/me").json()["department"]["name"] == "Biotech Test", "workspace belongs to the new department")
ok(d.get("/api/classes").json() == [], "new department starts with no classes")
r = d.post("/api/classes", json={"name": "BSc Biotech · Sem 1 · A", "semester": 1, "section": "A", "students": 40}); ok(r.status_code == 200, "department adds its first class")
ok(d.post("/api/classes", json={"name": "Duplicate", "semester": 1, "section": "A"}).status_code == 409, "duplicate semester+section refused")
ok(len(d.get("/api/classes").json()) == 1, "class appears in the department workspace")
print("ALL SIGN-UP CHECKS PASSED")
