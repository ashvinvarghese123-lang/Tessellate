"""Prepare an EMPTY production database (no sample data, no sample passwords).

1. creates the tables (via migrate.py logic is separate; run migrate.py first)
2. adds the college row, the academic year and the daily time slots
3. creates the first College Registry login (asks for a password)

  set DATABASE_URL to your production database, then:
  python backend/db/init_prod.py --college "Your College Name" --year 2026-27 --registry-email registry@yourcollege.edu
Safe to run again: it only fills in what is missing.
"""
import argparse, getpass, os, re, sys
import psycopg
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api.auth import hash_password, strong_enough  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--college", required=True)
ap.add_argument("--year", default="2026-27")
ap.add_argument("--days", type=int, default=5, help="working days per week, starting Monday")
ap.add_argument("--times", default="09:00-10:00,10:00-11:00,11:15-12:15,12:15-13:15,14:00-15:00,15:00-16:00",
                help="teaching periods in order; leave out breaks and lunch")
ap.add_argument("--registry-username", default="registry")
ap.add_argument("--registry-email", required=True)
a = ap.parse_args()
dsn = os.environ.get("DATABASE_URL") or sys.exit("Set DATABASE_URL to your production database first.")
slots = []
for t in a.times.split(","):
    m = re.fullmatch(r"(\d\d:\d\d)-(\d\d:\d\d)", t.strip())
    if not m or m.group(1) >= m.group(2):
        sys.exit(f"Time '{t}' isn't valid. Use HH:MM-HH:MM, for example 09:00-10:00.")
    slots.append(m.groups())
if not 1 <= a.days <= 7:
    sys.exit("Days should be between 1 and 7.")
if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a.registry_email):
    sys.exit("That registry email address doesn't look right.")

with psycopg.connect(dsn) as c:
    if not c.execute("SELECT to_regclass('public.department') IS NOT NULL").fetchone()[0]:
        sys.exit("The tables don't exist yet. Run: python backend/db/migrate.py")
    if not c.execute("SELECT 1 FROM college").fetchone():
        c.execute("INSERT INTO college (name, days, periods) VALUES (%s,%s,%s)", (a.college, a.days, len(slots)))
        print("Added college.")
    if not c.execute("SELECT 1 FROM academic_year WHERE label=%s", (a.year,)).fetchone():
        c.execute("INSERT INTO academic_year (label) VALUES (%s)", (a.year,))
        print("Added academic year", a.year)
    if not c.execute("SELECT 1 FROM time_slot").fetchone():
        for d in range(a.days):
            for p, (s, e) in enumerate(slots):
                c.execute("INSERT INTO time_slot (day, period, starts, ends) VALUES (%s,%s,%s,%s)", (d, p, s, e))
        print(f"Added {a.days * len(slots)} time slots.")
    if c.execute("SELECT 1 FROM registry_account").fetchone():
        print("A registry login already exists. Skipped.")
    else:
        pw = os.environ.get("REGISTRY_PASSWORD") or getpass.getpass("Registry password (10+ characters, letters and numbers): ")
        if not os.environ.get("REGISTRY_PASSWORD") and pw != getpass.getpass("Type it again: "):
            sys.exit("The two passwords don't match.")
        try:
            strong_enough(pw)
        except Exception as e:
            sys.exit(getattr(e, "detail", str(e)))
        c.execute("INSERT INTO registry_account (username, email, password_hash) VALUES (%s,%s,%s)",
                  (a.registry_username.lower(), a.registry_email.lower(), hash_password(pw)))
        print("Created registry login:", a.registry_username.lower())
print("Done. Departments can now sign up, or the Registry can create them first.")
