# Deploying Tessellate (and updating it later)

Plan: GitHub holds the code, Neon holds the database, Render runs the website. Each step must work before the next.
Prices and free-plan limits change, so check each site's current plans before you rely on them.

## Part 1 - Accounts you need
1. GitHub (github.com). 2. Neon (neon.tech) for PostgreSQL. 3. Render (render.com) to run the app.
4. An email sending service. Login codes are emailed, so this is required. Use your college's mail server (ask IT for SMTP host, port, username, password and a "from" address), or a service such as Brevo or SendGrid. Without it the app refuses to start in production, on purpose.

## Part 2 - Put the code on GitHub
Create a new PRIVATE repository on GitHub named `tessellate`. Then in PowerShell, in D:\SITE\tessellate:
```
git init
git add .
git commit -m "First version"
git branch -M main
git remote add origin https://github.com/YOUR-NAME/tessellate.git
git push -u origin main
```
If Git is blocked on your computer: on the repository page click "Add file > Upload files" and drag the contents of the tessellate folder in (not the .venv folder).
Never upload passwords or a .env file.

## Part 3 - Create the database (Neon)
1. New project. Pick a region near your college. Choose PostgreSQL 16 or newer.
2. Copy the connection string (looks like postgresql://user:password@host/dbname?sslmode=require). Keep it secret.

## Part 4 - Prepare the database from your computer
```
cd D:\SITE\tessellate
$env:PATH = "D:\SITE\sql\bin;" + $env:PATH
$env:DATABASE_URL = "PASTE-THE-NEON-CONNECTION-STRING"
python backend\db\migrate.py
python backend\db\init_prod.py --college "Your College Name" --year 2026-27 --registry-email registry@yourcollege.edu
```
migrate.py creates the tables. init_prod.py adds the college, the academic year, the daily periods and the first Registry login (it asks for a password). It adds NO sample data.
Periods: the default is six teaching periods (9:00-16:00 with a break and lunch). To change them: `--times "08:30-09:30,09:30-10:30,..."` and `--days 6`.

## Part 5 - Run the website (Render)
1. Render > New > Blueprint > choose your GitHub repository. It reads render.yaml.
2. Fill in the secret values it asks for:
   - DATABASE_URL: the Neon connection string
   - ALLOWED_EMAIL_DOMAINS: your college email domain, e.g. yourcollege.edu (only these addresses can create department accounts)
   - SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM from your email service (SMTP_PORT defaults to 587)
3. Create. The first build takes a few minutes.
4. If the deploy fails with "Production settings missing: ...", it is telling you exactly which setting to add. That check is deliberate.
Size: the timetable solver needs memory and CPU while it works. A free instance may be slow or run out of memory with a large college. Start small, watch it, and move to a larger instance if Generate is slow or fails. SOLVER_WORKERS (default 2 in render.yaml) should match the CPUs you have.

## Part 6 - First check
Open your Render address (https://tessellate-xxxx.onrender.com).
1. /registry-login.html: sign in with the Registry login, check the email code arrives in a real inbox.
2. Registry > Departments: add your departments (optional: departments can also sign up themselves).
3. Registry > Faculty, Classes, Rooms: add the shared records.
4. A department opens /signup, creates its account with its college email, adds subjects and generates.

## Part 7 - Updating later
1. Change the code on your computer (or ask me for the changed files), and test locally with the test scripts.
2. Publish:
```
git add .
git commit -m "Describe the change"
git push
```
Render rebuilds and deploys automatically. If something breaks, Render > Deploys > pick the previous good deploy > Rollback.
3. Database changes: add a NEW file in backend\db\migrations, e.g. `004_add_notes.sql`, containing the SQL. migrate.py runs it once at the next deploy. Never edit a migration that has already been used. Take a Neon backup or branch before an important migration.

## Part 8 - Before real users
- Use a custom domain if you want one (Render > Settings > Custom Domains). HTTPS is automatic.
- Keep ALLOWED_EMAIL_DOMAINS set to the college domain only.
- Restrict who can see Render and Neon (your GitHub, Render and Neon logins are the keys to everything).
- Know your backup and restore options on your Neon plan, and test a restore once.
- Sessions, rate limits and lockouts are kept in the app/database, so a restart does not log people out, but sign-up rate limiting is per running instance.

## Email on Render's free plan (important)
Render's free web services block the normal email ports (25, 465, 587), so Gmail/SMTP codes never arrive there. Use an email service over HTTPS instead (works on every plan): Brevo.
1. Create a free Brevo account, verify a sender address (Senders > add your email, click the link they email you).
2. Brevo > SMTP & API > API keys > create a key.
3. In Render > Environment add `BREVO_API_KEY` (the key) and set `SMTP_FROM` to the verified sender address. Save; Render redeploys.
Paid Render plans can use SMTP on ports 465/587, but the HTTPS way works everywhere. If codes still do not arrive, open Render > Logs: a line starting "Email to ... was refused" or "could not be sent" says why.

## Updating an existing live database for department timing and rules (migration 004)
This update adds `backend/db/migrations/004_department_timing.sql`. It runs by itself at the next deploy (migrate.py is part of the start command). Existing sessions keep their days and times. Take a Neon backup or branch first, because it replaces the old per-slot uniqueness with time-overlap protection.
Each department then chooses its days, period times, breaks and rules under **Rules**. Until a department saves its own settings it uses the college's original six periods and has NO optional rules turned on.

## Known gaps
Excel/CSV import, PDF/Excel export and website faculty sync are not built. Email delivery has been tested only with a stand-in, not a real mail server: send yourself a code first.
