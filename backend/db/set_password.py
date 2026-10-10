"""Set a new password for any department or registry login, from the server. Use this if you forgot a password
and can't use the email reset. Run from the tessellate folder:
  python backend\\db\\set_password.py --username cs
  python backend\\db\\set_password.py --username registry --registry
You are asked to type the new password twice. Nothing is shown while you type (that is normal)."""
import argparse, getpass, os, sys
import psycopg
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api.auth import hash_password, strong_enough  # noqa: E402
ap = argparse.ArgumentParser(); ap.add_argument("--username", required=True); ap.add_argument("--registry", action="store_true"); a = ap.parse_args()
pw = os.environ.get("NEW_PASSWORD") or getpass.getpass("New password (10+ characters, letters and numbers; nothing shows while you type): ")
if not os.environ.get("NEW_PASSWORD") and pw != getpass.getpass("Type it again: "): sys.exit("The two passwords don't match.")
try: strong_enough(pw)
except Exception as e: sys.exit(getattr(e, "detail", str(e)))
acct, sess = ("registry_account", "registry_session") if a.registry else ("department_account", "auth_session")
with psycopg.connect(os.environ.get("DATABASE_URL", "postgresql://tess:tess@localhost:5432/tessellate")) as c:
    r = c.execute(f"SELECT id FROM {acct} WHERE username=%s", (a.username.strip().lower(),)).fetchone()
    if not r: sys.exit(f"No {'registry' if a.registry else 'department'} login named '{a.username}'.")
    c.execute(f"UPDATE {acct} SET password_hash=%s, failed_logins=0, locked_until=NULL WHERE id=%s", (hash_password(pw), r[0]))
    c.execute(f"UPDATE {sess} SET revoked=TRUE WHERE account_id=%s", (r[0],))
print("Password updated. Any old sessions were signed out. You can sign in now.")
