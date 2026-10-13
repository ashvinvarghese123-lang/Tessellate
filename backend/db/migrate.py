"""Applies database changes safely, once each. Run it on every deploy (it does nothing if you're up to date).

  python backend/db/migrate.py

- Brand-new database: creates everything from schema.sql.
- Existing database: records where it is, then applies any newer files in db/migrations/ (004_..., 005_...) in order.
To change the database later: add a file like db/migrations/004_add_something.sql and run this. Never edit old migration files.
"""
import glob, os, re, sys
import psycopg

DSN = os.environ.get("DATABASE_URL") or sys.exit("Set DATABASE_URL first.")
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = 5   # schema.sql already includes migrations 2, 3, 4 and 5

def files():
    out = []
    for f in glob.glob(os.path.join(HERE, "migrations", "*.sql")):
        m = re.match(r"(\d+)_", os.path.basename(f))
        if m:
            out.append((int(m.group(1)), f))
    return sorted(out)

with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INT PRIMARY KEY, name TEXT, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
    exists = c.execute("SELECT to_regclass('public.department') IS NOT NULL").fetchone()[0]
    if 1 not in done:
        if not exists:
            c.execute(open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read())
            done |= {1, 2, 3, 4, 5}
            for v, n in ((1, "schema"), (2, "signup"), (3, "registry"), (4, "department_timing"), (5, "rooms_optional")):
                c.execute("INSERT INTO schema_migrations (version, name) VALUES (%s,%s)", (v, n))
            print("Created a new database from schema.sql.")
        else:
            c.execute("INSERT INTO schema_migrations (version, name) VALUES (1, 'schema (existing)')")
            done.add(1)
    for v, f in files():
        if v in done:
            continue
        with c.transaction():
            c.execute(open(f, encoding="utf-8").read())
            c.execute("INSERT INTO schema_migrations (version, name) VALUES (%s,%s)", (v, os.path.basename(f)))
        print("Applied", os.path.basename(f))
    print("Database is up to date.")
