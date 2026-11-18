"""Testing mode with email codes OFF (REQUIRE_OTP=0). Needs the seeded DB:  SEED_PASSWORD=TestPass-1234 python db/seed.py && python tests/test_no_otp.py"""
import os, sys
os.environ["REQUIRE_OTP"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import psycopg
from fastapi.testclient import TestClient
import api.auth as auth, api.registry as reg
from api.main import app
from api.db import DSN
PW, mails = "TestPass-1234", []
auth.send_email = lambda to, s, b: mails.append((to, b)); reg.send_email = auth.send_email
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))

c = TestClient(app)
ok(c.get("/api/auth/config").json() == {"otp": False}, "the page can tell that codes are off")
ok(c.post("/api/auth/login", json={"username": "cs", "password": "wrong"}).status_code == 401, "a wrong password is still refused")
r = c.post("/api/auth/login", json={"username": "cs", "password": PW}); ok(r.status_code == 200 and r.json() == {"signed_in": True}, "the password alone signs a department in")
ok(c.get("/api/auth/me").json()["department"]["name"] == "Computer Science" and not mails, "the session works and no email was sent")
ok(c.post("/api/generate", json={}).status_code == 200, "the workspace works normally")
for i in range(5): TestClient(app).post("/api/auth/login", json={"username": "physics", "password": "bad"})
ok(TestClient(app).post("/api/auth/login", json={"username": "physics", "password": PW}).status_code == 429, "lock-out after repeated wrong passwords still works")
c.post("/api/auth/logout"); ok(c.get("/api/auth/me").status_code == 401, "logout still works")

R = TestClient(app)
ok(R.post("/api/registry/auth/login", json={"username": "registry", "password": "wrong"}).status_code == 401, "registry: wrong password refused")
ok(R.post("/api/registry/auth/login", json={"username": "registry", "password": PW}).json() == {"signed_in": True}, "registry: the password alone signs in")
ok(R.get("/api/registry/overview").status_code == 200 and not mails, "registry works and no email was sent")
ok(c.get("/api/registry/overview").status_code == 401, "a department login still cannot open the registry")

with psycopg.connect(DSN) as db:
    db.execute("DELETE FROM login_audit WHERE account_id IN (SELECT id FROM department_account WHERE username='nootp')")
    db.execute("DELETE FROM department_account WHERE username='nootp'"); db.execute("DELETE FROM department WHERE name='No Code Dept'")
body = dict(department_name="No Code Dept", email="nootp@college.edu", username="nootp", password="Pass-No-Code-26")
S = TestClient(app)
ok(S.post("/api/auth/signup", json={**body, "email": "x@gmail.com"}).status_code == 400, "sign-up still only accepts the allowed email domain")
ok(S.post("/api/auth/signup", json={**body, "department_name": "Computer Science"}).status_code == 409, "an existing department still cannot be taken over")
r = S.post("/api/auth/signup", json=body); ok(r.status_code == 200 and r.json()["created"] is True, "sign-up creates the account straight away")
ok(S.post("/api/auth/login", json={"username": "nootp", "password": body["password"]}).json() == {"signed_in": True}, "the new account signs in")
with psycopg.connect(DSN, autocommit=True) as db:
    db.execute("UPDATE department_account SET locked_until=NULL, failed_logins=0 WHERE username='physics'")
print("ALL NO-CODE CHECKS PASSED")
