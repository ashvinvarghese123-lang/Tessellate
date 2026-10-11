# Tessellate — Every Department. Equal Priority. Perfectly Aligned.

One department = one secure account = one workspace. No roles, no department ranking.
Teachers, rooms, labs and time slots belong to the college and are shared.

## Deploying online
See DEPLOY.md (GitHub + Neon database + Render). `render.yaml` is included. Updates later: edit, test, `git push`; database changes go in backend/db/migrations/004_*.sql and are applied automatically.

## What is tested
- Scheduling engine (OR-Tools CP-SAT): no overlaps, exact weekly sessions, workload limits, fairness across departments, "look for a better college-wide arrangement" (proposal only, nothing applied silently). `python backend/tests/test_engine.py`
- Database schema and API on a real PostgreSQL: 25 end-to-end checks — password + emailed code, code expiry/one-use/attempt limits, resend cooldown, lockout, logout, password change, department isolation, shared availability with reasons, blocked clashing moves. `python backend/tests/test_api.py`
- The web page was syntax-checked but NOT clicked through in a browser yet. Expect small visual fixes.

## Create a new department account (like a real sign-up)
1. Open http://localhost:8000/signup (also linked from the login page: "Create account").
2. Enter department name, official email, username, password. A confirmation code is sent to that email; the account exists only after the code is entered.
3. Sign in, add classes (Classes page), add subjects (Subjects page), then Generate.
Rules: only emails ending in the allowed domain can register (default `college.edu`). To test with another domain: `$env:ALLOWED_EMAIL_DOMAINS = "college.edu,gmail.com"` before starting the server. A department that already has an account can never be taken over from this page.
Existing database? Run once: `psql -U tess -d tessellate -f backend\db\migrations\002_signup.sql`
Tests: `python backend\tests\test_signup.py`

## Timing and rules chosen by each department
Under **Rules** a department sets its working days, period start/end times (gaps are breaks), periods to keep free, and which optional rules apply (Off / Prefer / Always required). Clash checks are always on. Shared teachers and rooms are compared by real time, so two departments can use different bell times without overlapping. Existing database: it is applied by `python backend\db\migrate.py` (migration 004). Tests: `python backend\tests\test_rules.py`.

## College Registry (external, data-only login)
- Sign in at http://localhost:8000/registry-login.html (linked from the department login page). Same security: password + emailed code.
- It edits the shared records every department reads: departments, faculty (including moving a teacher to another department), classes, rooms/labs. Changes show immediately in every department workspace.
- It cannot see, create, edit or publish any timetable, and gives no department priority. Subjects and weekly sessions stay with each department.
- Existing database? Run once: `psql -U tess -d tessellate -f backend\db\migrations\003_registry.sql`, then create the login: `python backend\db\create_registry_account.py --username registry --email registry@college.edu` (asks for a password).
- Fresh seed creates username `registry` automatically (same password as the departments when SEED_PASSWORD is set).
Tests: `python backend\tests\test_registry.py`

## Not done yet
Excel/CSV import, PDF/Excel export, website faculty sync, "remember this device", live "reserved" indicator, applying a college-wide alternative (it is shown as a proposal only), real email provider setup (set SMTP_* variables).

## Run it (Windows PowerShell, from the tessellate folder)
1. Start the database (needs Docker Desktop):
   `docker compose up -d`
2. Python environment:
   `python -m venv .venv`
   `.\.venv\Scripts\Activate.ps1`
   `pip install -r backend\requirements.txt`
3. Tell the app where the database is (same PowerShell window):
   `$env:DATABASE_URL = "postgresql://tess:tess@localhost:5432/tessellate"`
4. Load the sample college and create the 5 department accounts:
   `python backend\db\seed.py`
   Passwords are printed ONCE. Copy them now. (For a simple test password: `$env:SEED_PASSWORD="TestPass-1234"` before this command.)
5. Start the server:
   `cd backend`
   `python -m uvicorn api.main:app --port 8000`
6. Open http://localhost:8000
7. Sign in (username `cs`, `maths`, `bca`, `commerce` or `physics`). The 6-digit code is NOT shown on the web page. In development it is printed in the PowerShell window running the server ("DEV EMAIL ... Your code is 123456"). With SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM set, it is emailed to the department's registered address.

## Before real use
Set `TESSELLATE_SECRET` to a long random value, `COOKIE_SECURE=1` (behind HTTPS), change all seeded passwords, and use real department email addresses.
