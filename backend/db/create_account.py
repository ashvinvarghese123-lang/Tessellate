"""Create a new department account (and optionally its classes).

Examples (run from the tessellate folder):
  python backend\\db\\create_account.py --name "Chemistry" --username chemistry --email chemistry@college.edu --class "BSc Chemistry · Sem 1 · A"
Add --class more than once for more classes. You will be asked to type the password (it is not shown).
A department account cannot be created from the website on purpose: only someone with access to the server can add one.
"""
import argparse, getpass, os, re, sys
import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api.auth import hash_password, strong_enough  # noqa: E402

DSN = os.environ.get("DATABASE_URL", "postgresql://tess:tess@localhost:5432/tessellate")
ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True, help="Department name, e.g. Chemistry")
ap.add_argument("--username", required=True, help="Login name, e.g. chemistry (lowercase, no spaces)")
ap.add_argument("--email", required=True, help="Registered department email; codes are sent here")
ap.add_argument("--class", dest="classes", action="append", default=[], help="Class name (repeatable)")
ap.add_argument("--semester", type=int, default=1)
a = ap.parse_args()

user = a.username.strip().lower()
if not re.fullmatch(r"[a-z0-9_.-]{2,30}", user):
    sys.exit("Username: use 2-30 lowercase letters, numbers, dot, dash or underscore.")
if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a.email):
    sys.exit("That email address doesn't look right.")
pw = getpass.getpass("Password (10+ characters, letters and numbers): ")
if pw != getpass.getpass("Type it again: "):
    sys.exit("The two passwords don't match.")
try:
    strong_enough(pw)
except Exception as e:
    sys.exit(getattr(e, "detail", str(e)))

code = "DEPT-" + re.sub(r"[^A-Z0-9]", "", a.name.upper())[:8]
with psycopg.connect(DSN) as c:
    if c.execute("SELECT 1 FROM department_account WHERE username=%s", (user,)).fetchone():
        sys.exit(f"The username '{user}' already exists.")
    d = c.execute("SELECT id FROM department WHERE code=%s", (code,)).fetchone()
    if d and c.execute("SELECT 1 FROM department_account WHERE department_id=%s", (d[0],)).fetchone():
        sys.exit("That department already has an account.")
    did = d[0] if d else c.execute("INSERT INTO department (code, name) VALUES (%s,%s) RETURNING id", (code, a.name)).fetchone()[0]
    c.execute("INSERT INTO department_account (department_id, username, email, password_hash) VALUES (%s,%s,%s,%s)",
              (did, user, a.email.strip().lower(), hash_password(pw)))
    year = c.execute("SELECT id FROM academic_year ORDER BY id DESC LIMIT 1").fetchone()[0]
    for i, n in enumerate(a.classes):
        cid = c.execute("""INSERT INTO class (department_id, academic_year_id, semester, section, name)
                           VALUES (%s,%s,%s,%s,%s) RETURNING id""", (did, year, a.semester, chr(65 + i), n)).fetchone()[0]
        c.execute("INSERT INTO timetable (class_id, department_id) VALUES (%s,%s)", (cid, did))
print(f"Created {a.name} ({code}). Sign in with username '{user}'. Codes go to {a.email}.")
