import os
import psycopg
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL", "postgresql://tess:tess@localhost:5432/tessellate")


def db():
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        yield conn
