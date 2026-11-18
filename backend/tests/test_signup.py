"""Central Registry & Department Account Management test.
Tests that public signup is disabled, and that only accounts created through
the central College Registry can access TESSellate.
"""
import os, re, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
import psycopg
import api.auth as auth
from api.main import app
from api.db import DSN

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))

with psycopg.connect(DSN) as c:
    c.execute("DELETE FROM login_audit WHERE account_id IN (SELECT id FROM department_account WHERE username='biotest')")
    c.execute("DELETE FROM department_account WHERE username='biotest'")
    c.execute("DELETE FROM department WHERE name='Biotech Test'")

cl = TestClient(app)

# 1. Public sign-up is completely disabled
body = dict(department_name="Biotech Test", email="biotest@college.edu", username="biotest", password="Bio-Pass-2026")
r = cl.post("/api/auth/signup", json=body)
ok(r.status_code == 403, "Public sign-up is disabled (returns 403)")
ok("Registry" in r.text or "disabled" in r.text, "Error message states accounts are issued by Registry")

# 2. Registry operator signs in
reg = TestClient(app)
r = reg.post("/api/registry/auth/login", json={"username": "registry", "password": "TestPass-1234"})
ok(r.status_code == 200 and r.json().get("signed_in") is True, "Registry signs in")

# 3. Registry creates department with automatic account & credentials generation
r = reg.post("/api/registry/departments", json={
    "name": "Biotech Test",
    "code": "BIOTEST",
    "username": "biotest",
    "password": "Bio-Pass-2026",
    "category_id": 1
})
ok(r.status_code == 200, "Registry creates department and its login account together")
data = r.json()
ok(data.get("username") == "biotest", "Username is registered")
ok(data.get("initial_password") == "Bio-Pass-2026", "Initial password provided to operator")
ok(data.get("created") is True, "Creation confirmed")

# 4. Department signs in using the generated credentials
dept = TestClient(app)
r = dept.post("/api/auth/login", json={"username": "biotest", "password": "Bio-Pass-2026"})
ok(r.status_code == 200 and r.json().get("signed_in") is True, "Department signs in with generated credentials")

# 5. Department enters its own workspace
me = dept.get("/api/auth/me").json()
ok(me["department"]["name"] == "Biotech Test", "Department workspace is correctly isolated")

# 6. Registry resets password and department signs in with new password
r = reg.post(f"/api/registry/departments/{data['id']}/reset-password", json={"new_password": "New-Bio-Pass-2026"})
ok(r.status_code == 200, "Registry resets department password")
new_pw = r.json().get("new_password")
ok(new_pw == "New-Bio-Pass-2026", "New password returned to operator to copy")

# Old password fails
bad_login = dept.post("/api/auth/login", json={"username": "biotest", "password": "Bio-Pass-2026"})
ok(bad_login.status_code == 401, "Old password no longer works")

# New password succeeds
good_login = dept.post("/api/auth/login", json={"username": "biotest", "password": "New-Bio-Pass-2026"})
ok(good_login.status_code == 200 and good_login.json().get("signed_in") is True, "New reset password signs in successfully")

# 7. Department manages its workspace classes
ok(dept.get("/api/classes").json() == [], "New department starts with no classes")
r = dept.post("/api/classes", json={"name": "BSc Biotech · Sem 1 · A", "semester": 1, "section": "A", "students": 40})
ok(r.status_code == 200, "Department adds class")
ok(len(dept.get("/api/classes").json()) == 1, "Class appears in department workspace")

print("ALL CENTRAL REGISTRY & ACCOUNT MANAGEMENT CHECKS PASSED")
