"""Create (or add another) College Registry login. Run from the tessellate folder:
  python backend\\db\\create_registry_account.py --username registry --email registry@college.edu
The registry is a data-only account (departments, faculty, classes, rooms). It cannot see or change timetables."""
import argparse, getpass, os, re, sys
import psycopg
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api.auth import hash_password, strong_enough  # noqa: E402
ap = argparse.ArgumentParser(); ap.add_argument("--username", required=True); ap.add_argument("--email", required=True); a = ap.parse_args()
user = a.username.strip().lower()
if not re.fullmatch(r"[a-z0-9_.-]{2,30}", user): sys.exit("Username: use 2-30 lowercase letters, numbers, dot, dash or underscore.")
if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a.email): sys.exit("That email address doesn't look right.")
pw = os.environ.get("REGISTRY_PASSWORD") or getpass.getpass("Password (10+ characters, letters and numbers): ")
if not os.environ.get("REGISTRY_PASSWORD") and pw != getpass.getpass("Type it again: "): sys.exit("The two passwords don't match.")
try: strong_enough(pw)
except Exception as e: sys.exit(getattr(e, "detail", str(e)))
with psycopg.connect(os.environ.get("DATABASE_URL", "postgresql://tess:tess@localhost:5432/tessellate")) as c:
    if c.execute("SELECT 1 FROM registry_account WHERE username=%s", (user,)).fetchone(): sys.exit(f"The username '{user}' already exists.")
    c.execute("INSERT INTO registry_account (username, email, password_hash) VALUES (%s,%s,%s)", (user, a.email.strip().lower(), hash_password(pw)))
print(f"Created registry login '{user}'. Sign in at http://localhost:8000/registry-login.html")
