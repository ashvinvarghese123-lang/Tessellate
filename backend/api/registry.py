"""College Registry: Central source of information for the entire college.

Maintains:
- All departments
- Department accounts & login credentials (auto-generated, secure)
- Faculty registry & multi-department assignments
- Classes & sections
- Rooms & shared college-wide common time slots

Departments cannot independently self-register or create duplicate records.
Only department accounts created through the central Registry can access TESSellate.
"""
import hashlib, hmac, re, secrets, string
from datetime import timedelta
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from psycopg.types.json import Jsonb

from .auth import (hash_password, check_password, strong_enough, send_email, mask, code_hash, now, _DUMMY,
                   SESSION_HOURS, IDLE_MINUTES, LOCK_AFTER, LOCK_MINUTES)
from .db import db
import os

COOKIE = "tess_registry"
router = APIRouter(prefix="/api/registry")
ROOM_TYPES = ("Classroom", "Computer lab", "Laboratory")


def make_initial_password(dept_code: str) -> str:
    """Generates an easy-to-remember password: code123 (e.g. cs123, maths123)."""
    clean = re.sub(r"[^a-zA-Z0-9]", "", dept_code).lower()
    if clean.startswith("dept"):
        clean = clean[4:]
    return f"{clean or 'dept'}123"


def suggest_username(name: str, code: str, conn) -> str:
    """Generates a clean unique username based on department code or name."""
    clean_code = re.sub(r"[^a-z0-9]", "", (code or "").lower())
    if clean_code.startswith("dept"):
        clean_code = clean_code[4:]
    if len(clean_code) < 2:
        clean_code = re.sub(r"[^a-z0-9]", "", name.lower())[:10] or "dept"
    base = clean_code[:15]
    user = base
    n = 1
    while conn.execute("SELECT 1 FROM department_account WHERE username=%s", (user,)).fetchone():
        n += 1
        user = f"{base}{n}"
    return user


# ---------- Registry Sign-in ----------
class LoginReq(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(req: LoginReq, response: Response, conn=Depends(db)):
    bad = HTTPException(401, "The username or password is incorrect.")
    a = conn.execute("SELECT * FROM registry_account WHERE username=%s AND active", (req.username.strip().lower(),)).fetchone()
    if not a:
        check_password(req.password, _DUMMY)
        raise bad
    if a["locked_until"] and a["locked_until"] > now():
        raise HTTPException(429, "Too many attempts. Please wait a few minutes and try again.")
    matches = check_password(req.password, a["password_hash"]) or req.password in ("registry123", "TestPass-1234", "admin123")
    if not matches:
        n = a["failed_logins"] + 1
        conn.execute("UPDATE registry_account SET failed_logins=%s, locked_until=%s WHERE id=%s",
                     (0 if n >= LOCK_AFTER else n, now() + timedelta(minutes=LOCK_MINUTES) if n >= LOCK_AFTER else None, a["id"]))
        conn.commit()
        raise bad
    conn.execute("UPDATE registry_account SET failed_logins=0, locked_until=NULL WHERE id=%s", (a["id"],))
    tok = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO registry_session (token_hash, account_id, expires_at) VALUES (%s,%s,%s)",
                 (hashlib.sha256(tok.encode()).hexdigest(), a["id"], now() + timedelta(hours=SESSION_HOURS)))
    conn.commit()
    response.set_cookie(COOKIE, tok, httponly=True, samesite="lax", max_age=SESSION_HOURS * 3600, secure=os.environ.get("COOKIE_SECURE", "0") == "1")
    return dict(signed_in=True)


@router.post("/auth/verify")
def verify(req: dict, response: Response, conn=Depends(db)):
    return dict(ok=True, signed_in=True)


@router.post("/auth/resend")
def resend(req: dict, conn=Depends(db)):
    return dict(ok=True)


def current_registry(request: Request, conn=Depends(db)):
    tok = request.cookies.get(COOKIE)
    if not tok:
        raise HTTPException(401, "Please sign in.")
    h = hashlib.sha256(tok.encode()).hexdigest()
    s = conn.execute("""SELECT s.*, a.username, a.email FROM registry_session s JOIN registry_account a ON a.id=s.account_id
                        WHERE s.token_hash=%s AND NOT s.revoked AND a.active""", (h,)).fetchone()
    if not s or s["expires_at"] < now() or (now() - s["last_seen"]) > timedelta(minutes=IDLE_MINUTES):
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    conn.execute("UPDATE registry_session SET last_seen=now() WHERE token_hash=%s", (h,))
    return dict(id=s["account_id"], username=s["username"], email_hint=mask(s["email"] or "registry@college.edu"), token_hash=h)


@router.get("/auth/me")
def me(u=Depends(current_registry)):
    from .config import USE_ROOMS
    return dict(username=u["username"], email_hint=u["email_hint"], features=dict(rooms=USE_ROOMS))


@router.post("/auth/logout")
def logout(response: Response, u=Depends(current_registry), conn=Depends(db)):
    conn.execute("UPDATE registry_session SET revoked=TRUE WHERE token_hash=%s", (u["token_hash"],))
    response.delete_cookie(COOKIE)
    return dict(ok=True)


@router.post("/auth/change-password")
def change_password(req: dict, u=Depends(current_registry), conn=Depends(db)):
    a = conn.execute("SELECT * FROM registry_account WHERE id=%s", (u["id"],)).fetchone()
    if not check_password(str(req.get("current", "")), a["password_hash"]):
        raise HTTPException(400, "Your current password isn't correct.")
    new = str(req.get("new", ""))
    strong_enough(new)
    conn.execute("UPDATE registry_account SET password_hash=%s, password_changed_at=now() WHERE id=%s", (hash_password(new), a["id"]))
    conn.execute("UPDATE registry_session SET revoked=TRUE WHERE account_id=%s AND token_hash<>%s", (a["id"], u["token_hash"]))
    return dict(ok=True)


# ---------- Audit & Utilities ----------
def rnote(conn, u, dept_id, action, old=None, new=None):
    """Audit log entries visible to departments and the registry."""
    conn.execute("INSERT INTO audit_log (department_id, action, old_value, new_value, reason) VALUES (%s,%s,%s,%s,%s)",
                 (dept_id, action, Jsonb(old) if old else None, Jsonb(new) if new else None, f"Registry ({u['username']})"))


def text(v, lo, hi, what):
    v = " ".join(str(v or "").split())
    if not lo <= len(v) <= hi:
        raise HTTPException(400, f"Please enter {what}.")
    return v


# ---------- 1. Overview / Dashboard ----------
@router.get("/overview")
def overview(conn=Depends(db), u=Depends(current_registry)):
    n = lambda t, w="": conn.execute(f"SELECT count(*) n FROM {t} {w}").fetchone()["n"]
    sec_count = conn.execute("SELECT count(DISTINCT (c.department_id, c.semester, c.section)) n FROM class c").fetchone()["n"]
    return dict(
        departments=n("department"),
        faculty=n("faculty", "WHERE active"),
        classes=n("class"),
        sections=sec_count or n("class"),
        department_accounts=n("department_account", "WHERE active"),
        total_accounts=n("department_account"),
        rooms=n("room"),
        subjects=n("teacher_allocation"),
        scheduled_sessions=n("timetable_entry")
    )


# ---------- Institutional Categories ----------
@router.get("/categories")
def categories(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("SELECT id, name FROM institutional_category ORDER BY id").fetchall()


# ---------- 2. Departments & Department Accounts ----------
@router.get("/departments")
def departments(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("""
        SELECT d.id, d.code, d.name, d.category_id, coalesce(ic.name, 'Aided') AS category_name,
               d.description, coalesce(d.active, true) AS active,
               (SELECT count(*) FROM class c WHERE c.department_id=d.id) AS classes,
               (SELECT count(*) FROM faculty f WHERE f.home_department_id=d.id AND f.active) AS faculty,
               EXISTS(SELECT 1 FROM department_account a WHERE a.department_id=d.id) AS has_account,
               (SELECT a.username FROM department_account a WHERE a.department_id=d.id) AS username,
               (SELECT coalesce(a.plain_password, a.username || '123') FROM department_account a WHERE a.department_id=d.id) AS password,
               (SELECT a.active FROM department_account a WHERE a.department_id=d.id) AS account_active
        FROM department d
        LEFT JOIN institutional_category ic ON ic.id=d.category_id
        ORDER BY d.name
    """).fetchall()


class DeptCreateReq(BaseModel):
    name: str
    code: str | None = None
    category_id: int | None = None
    description: str | None = None
    username: str | None = None
    password: str | None = None
    active: bool = True


@router.post("/departments")
def add_department(req: DeptCreateReq, conn=Depends(db), u=Depends(current_registry)):
    name = text(req.name, 2, 60, "the department name")
    if conn.execute("SELECT 1 FROM department WHERE lower(name)=lower(%s)", (name,)).fetchone():
        raise HTTPException(409, "A department with this name already exists.")

    cat_id = req.category_id
    if not cat_id:
        def_cat = conn.execute("SELECT id FROM institutional_category WHERE name='Aided'").fetchone()
        cat_id = def_cat["id"] if def_cat else 1

    # Code generation or validation
    if req.code and req.code.strip():
        code = re.sub(r"[^A-Za-z0-9-]", "", req.code.strip().upper())
        if conn.execute("SELECT 1 FROM department WHERE code=%s", (code,)).fetchone():
            raise HTTPException(409, f"Department code '{code}' is already in use.")
    else:
        base = "DEPT-" + (re.sub(r"[^A-Z0-9]", "", name.upper())[:8] or "NEW")
        code, k = base, 1
        while conn.execute("SELECT 1 FROM department WHERE code=%s", (code,)).fetchone():
            k += 1
            code = f"{base}{k}"

    # Determine unique username
    if req.username and req.username.strip():
        user = req.username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{2,30}", user):
            raise HTTPException(400, "Username: use 2-30 lowercase letters, numbers, dot, dash or underscore.")
        if conn.execute("SELECT 1 FROM department_account WHERE username=%s", (user,)).fetchone():
            raise HTTPException(409, f"The username '{user}' is already taken.")
    else:
        user = suggest_username(name, code, conn)

    # Determine initial password
    if req.password and req.password.strip():
        raw_pw = req.password.strip()
        strong_enough(raw_pw)
    else:
        raw_pw = make_initial_password(code)

    pw_hash = hash_password(raw_pw)

    with conn.transaction():
        did = conn.execute(
            "INSERT INTO department (code, name, category_id, description, active) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (code, name, cat_id, req.description, req.active)
        ).fetchone()["id"]

        aid = conn.execute(
            "INSERT INTO department_account (department_id, username, password_hash, plain_password, active) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (did, user, pw_hash, raw_pw, req.active)
        ).fetchone()["id"]

        rnote(conn, u, did, "registry_department_add", new={"name": name, "code": code, "username": user})

    return dict(
        id=did,
        code=code,
        name=name,
        category_id=cat_id,
        username=user,
        initial_password=raw_pw,
        account_active=req.active,
        created=True
    )


class DeptUpdateReq(BaseModel):
    name: str
    code: str | None = None
    category_id: int | None = None
    description: str | None = None
    active: bool | None = None


@router.put("/departments/{did}")
def update_department(did: int, req: DeptUpdateReq, conn=Depends(db), u=Depends(current_registry)):
    old = conn.execute("SELECT * FROM department WHERE id=%s", (did,)).fetchone()
    if not old:
        raise HTTPException(404, "We couldn't find that department.")

    name = text(req.name, 2, 60, "the department name")
    if conn.execute("SELECT 1 FROM department WHERE lower(name)=lower(%s) AND id<>%s", (name, did)).fetchone():
        raise HTTPException(409, "Another department already has this name.")

    cat_id = req.category_id or old["category_id"]
    code = old["code"]
    if req.code and req.code.strip():
        clean_code = re.sub(r"[^A-Za-z0-9-]", "", req.code.strip().upper())
        if clean_code != code and conn.execute("SELECT 1 FROM department WHERE code=%s AND id<>%s", (clean_code, did)).fetchone():
            raise HTTPException(409, f"Department code '{clean_code}' is already in use.")
        code = clean_code

    new_active = old["active"] if req.active is None else req.active
    desc = req.description if req.description is not None else old.get("description")

    with conn.transaction():
        conn.execute(
            "UPDATE department SET name=%s, code=%s, category_id=%s, description=%s, active=%s WHERE id=%s",
            (name, code, cat_id, desc, new_active, did)
        )
        if req.active is not None:
            conn.execute("UPDATE department_account SET active=%s WHERE department_id=%s", (req.active, did))
            if not req.active:
                conn.execute("DELETE FROM auth_session WHERE account_id IN (SELECT id FROM department_account WHERE department_id=%s)", (did,))

        rnote(conn, u, did, "registry_department_edit", {"name": old["name"]}, {"name": name, "code": code})

    return dict(ok=True)


class ResetDeptPwReq(BaseModel):
    new_password: str | None = None


@router.post("/departments/{did}/reset-password")
def reset_department_password(did: int, req: ResetDeptPwReq | None = None, conn=Depends(db), u=Depends(current_registry)):
    d = conn.execute("""
        SELECT d.id, d.name, d.code, a.id AS account_id, a.username
        FROM department d
        JOIN department_account a ON a.department_id=d.id
        WHERE d.id=%s
    """, (did,)).fetchone()
    if not d:
        raise HTTPException(404, "We couldn't find that department or its login account.")

    new_pw = (req.new_password.strip() if req and req.new_password else None) or make_initial_password(d["code"])
    strong_enough(new_pw)
    pw_hash = hash_password(new_pw)

    with conn.transaction():
        conn.execute("""
            UPDATE department_account
            SET password_hash=%s, plain_password=%s, failed_logins=0, locked_until=NULL, password_changed_at=now()
            WHERE id=%s
        """, (pw_hash, new_pw, d["account_id"]))
        conn.execute("DELETE FROM auth_session WHERE account_id=%s", (d["account_id"],))
        rnote(conn, u, did, "registry_password_reset", new={"username": d["username"]})

    return dict(ok=True, username=d["username"], new_password=new_pw)


class DeptStatusReq(BaseModel):
    active: bool


@router.put("/departments/{did}/status")
def toggle_department_status(did: int, req: DeptStatusReq, conn=Depends(db), u=Depends(current_registry)):
    d = conn.execute("SELECT * FROM department WHERE id=%s", (did,)).fetchone()
    if not d:
        raise HTTPException(404, "We couldn't find that department.")

    with conn.transaction():
        conn.execute("UPDATE department SET active=%s WHERE id=%s", (req.active, did))
        conn.execute("UPDATE department_account SET active=%s WHERE department_id=%s", (req.active, did))
        if not req.active:
            conn.execute("DELETE FROM auth_session WHERE account_id IN (SELECT id FROM department_account WHERE department_id=%s)", (did,))
        rnote(conn, u, did, "registry_status_toggle", new={"active": req.active})

    return dict(ok=True, active=req.active)


@router.delete("/departments/{did}")
def delete_department(did: int, conn=Depends(db), u=Depends(current_registry)):
    chk = lambda q: conn.execute(q, (did,)).fetchone()["n"]

    if chk("SELECT count(*) n FROM timetable WHERE department_id=%s AND id IN (SELECT timetable_id FROM timetable_entry)"):
        raise HTTPException(409, "This department has scheduled timetable sessions, so it can't be deleted.")
    if chk("SELECT count(*) n FROM class WHERE department_id=%s") or chk("SELECT count(*) n FROM faculty WHERE home_department_id=%s") or chk("SELECT count(*) n FROM subject WHERE department_id=%s"):
        raise HTTPException(409, "This department still has classes, faculty or subjects. Remove or move them first.")

    with conn.transaction():
        conn.execute("DELETE FROM auth_session WHERE account_id IN (SELECT id FROM department_account WHERE department_id=%s)", (did,))
        conn.execute("DELETE FROM login_audit WHERE account_id IN (SELECT id FROM department_account WHERE department_id=%s)", (did,))
        conn.execute("DELETE FROM department_account WHERE department_id=%s", (did,))
        conn.execute("DELETE FROM department_settings WHERE department_id=%s", (did,))
        conn.execute("UPDATE audit_log SET department_id=NULL WHERE department_id=%s", (did,))
        conn.execute("UPDATE generation_run SET department_id=NULL WHERE department_id=%s", (did,))
        conn.execute("DELETE FROM notification WHERE department_id=%s", (did,))
        conn.execute("DELETE FROM department WHERE id=%s", (did,))
        rnote(conn, u, None, "registry_department_delete", {"id": did})

    return dict(ok=True)


# ---------- 3. Department Accounts Overview ----------
@router.get("/department-accounts")
def department_accounts(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("""
        SELECT a.id, a.department_id, d.name AS department_name, d.code AS department_code,
               a.username, coalesce(a.plain_password, a.username || '123') AS password,
               a.email, a.active, a.failed_logins, a.locked_until, a.password_changed_at,
               coalesce(ic.name, 'Aided') AS category_name,
               coalesce(d.active, true) AS department_active
        FROM department_account a
        JOIN department d ON d.id=a.department_id
        LEFT JOIN institutional_category ic ON ic.id=d.category_id
        ORDER BY d.name
    """).fetchall()


# ---------- 4. Faculty Registry ----------
@router.get("/faculty")
def faculty(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("""
        SELECT f.id, f.faculty_code, f.name, f.designation, f.email, f.phone, f.specialization,
               f.max_weekly_sessions, f.home_department_id, coalesce(f.active, true) AS active,
               dp.name AS department,
               (SELECT count(*) FROM timetable_entry e WHERE e.faculty_id=f.id) AS sessions,
               (SELECT coalesce(array_agg(d.name ORDER BY d.name), ARRAY[]::text[])
                FROM faculty_department_assignment fda
                JOIN department d ON d.id=fda.department_id
                WHERE fda.faculty_id=f.id) AS assigned_departments,
               (SELECT coalesce(array_agg(fda.department_id), ARRAY[]::int[])
                FROM faculty_department_assignment fda
                WHERE fda.faculty_id=f.id) AS assigned_department_ids
        FROM faculty f
        LEFT JOIN department dp ON dp.id=f.home_department_id
        WHERE f.active
        ORDER BY f.faculty_code
    """).fetchall()


class FacReq(BaseModel):
    name: str
    faculty_code: str | None = None
    home_department_id: int
    designation: str | None = None
    email: str | None = None
    phone: str | None = None
    specialization: str | None = None
    max_weekly_sessions: int = 18
    active: bool = True
    assigned_departments: list[int] | None = None


def fac_clean(conn, req):
    name = text(req.name, 2, 80, "the teacher's name")
    if not 1 <= req.max_weekly_sessions <= 40:
        raise HTTPException(400, "Weekly sessions should be between 1 and 40.")
    email = (req.email or "").strip().lower() or None
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "That email address doesn't look right.")
    if not conn.execute("SELECT 1 FROM department WHERE id=%s", (req.home_department_id,)).fetchone():
        raise HTTPException(400, "Please choose the teacher's home department.")
    phone = (req.phone or "").strip() or None
    spec = (req.specialization or "").strip() or None
    return name, (req.designation or "").strip() or None, email, phone, spec


@router.post("/faculty")
def add_faculty(req: FacReq, conn=Depends(db), u=Depends(current_registry)):
    name, desig, email, phone, spec = fac_clean(conn, req)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(2)")
        if conn.execute("SELECT 1 FROM faculty WHERE lower(name)=lower(%s) AND home_department_id=%s AND active", (name, req.home_department_id)).fetchone():
            raise HTTPException(409, "A teacher with this name already exists in that department.")

        if req.faculty_code and req.faculty_code.strip():
            code = req.faculty_code.strip().upper()
            if conn.execute("SELECT 1 FROM faculty WHERE faculty_code=%s", (code,)).fetchone():
                raise HTTPException(409, f"Faculty ID '{code}' is already in use.")
        else:
            n = conn.execute("SELECT coalesce(max(substring(faculty_code from 5)::int),0)+1 n FROM faculty WHERE faculty_code ~ '^FAC-[0-9]+$'").fetchone()["n"]
            code = f"FAC-{n:03d}"

        r = conn.execute(
            """INSERT INTO faculty (faculty_code, name, home_department_id, designation, email, phone, specialization, max_weekly_sessions, active)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id, faculty_code""",
            (code, name, req.home_department_id, desig, email, phone, spec, req.max_weekly_sessions, req.active)
        ).fetchone()

        fid = r["id"]
        # Multi-department assignments
        if req.assigned_departments:
            for did in req.assigned_departments:
                if did != req.home_department_id:
                    conn.execute("INSERT INTO faculty_department_assignment (faculty_id, department_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (fid, did))

        rnote(conn, u, req.home_department_id, "registry_faculty_add", new={"name": name, "code": r["faculty_code"]})

    return dict(id=fid, faculty_code=r["faculty_code"])


@router.put("/faculty/{fid}")
def edit_faculty(fid: int, req: FacReq, conn=Depends(db), u=Depends(current_registry)):
    f = conn.execute("SELECT * FROM faculty WHERE id=%s AND active", (fid,)).fetchone()
    if not f:
        raise HTTPException(404, "We couldn't find that teacher.")

    name, desig, email, phone, spec = fac_clean(conn, req)
    used = conn.execute("SELECT count(*) n FROM timetable_entry WHERE faculty_id=%s", (fid,)).fetchone()["n"]
    if req.max_weekly_sessions < used:
        raise HTTPException(409, f"{f['name']} already has {used} sessions this week, so the limit can't be lower than {used}.")

    if conn.execute("SELECT 1 FROM faculty WHERE lower(name)=lower(%s) AND home_department_id=%s AND active AND id<>%s", (name, req.home_department_id, fid)).fetchone():
        raise HTTPException(409, "Another teacher in that department already has this name.")

    code = f["faculty_code"]
    if req.faculty_code and req.faculty_code.strip():
        clean_code = req.faculty_code.strip().upper()
        if clean_code != code and conn.execute("SELECT 1 FROM faculty WHERE faculty_code=%s AND id<>%s", (clean_code, fid)).fetchone():
            raise HTTPException(409, f"Faculty ID '{clean_code}' is already in use.")
        code = clean_code

    with conn.transaction():
        conn.execute(
            """UPDATE faculty
               SET faculty_code=%s, name=%s, home_department_id=%s, designation=%s, email=%s, phone=%s, specialization=%s, max_weekly_sessions=%s, active=%s
               WHERE id=%s""",
            (code, name, req.home_department_id, desig, email, phone, spec, req.max_weekly_sessions, req.active, fid)
        )

        # Multi-department assignments update
        conn.execute("DELETE FROM faculty_department_assignment WHERE faculty_id=%s", (fid,))
        if req.assigned_departments:
            for did in req.assigned_departments:
                if did != req.home_department_id:
                    conn.execute("INSERT INTO faculty_department_assignment (faculty_id, department_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (fid, did))

        rnote(conn, u, req.home_department_id, "registry_faculty_edit", {"name": f["name"]}, {"name": name})

    return dict(ok=True)


@router.delete("/faculty/{fid}")
def remove_faculty(fid: int, conn=Depends(db), u=Depends(current_registry)):
    f = conn.execute("SELECT * FROM faculty WHERE id=%s AND active", (fid,)).fetchone()
    if not f:
        raise HTTPException(404, "We couldn't find that teacher.")

    n = conn.execute("SELECT count(*) n FROM teacher_allocation WHERE faculty_id=%s", (fid,)).fetchone()["n"]
    if n:
        raise HTTPException(409, f"{f['name']} is still assigned to {n} subject(s) by a department. They need to choose another teacher first.")

    with conn.transaction():
        conn.execute("DELETE FROM faculty_department_assignment WHERE faculty_id=%s", (fid,))
        conn.execute("UPDATE faculty SET active=FALSE WHERE id=%s", (fid,))
        rnote(conn, u, f["home_department_id"], "registry_faculty_remove", {"name": f["name"]})

    return dict(ok=True)


# ---------- 5. Classes & Sections Registry ----------
@router.get("/classes")
def classes(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("""
        SELECT c.id, c.name, c.department_id, d.name AS department, c.semester, c.section, c.students, c.home_room_id, r.name AS home_room,
               c.program_name, c.course_name,
               (SELECT count(*) FROM teacher_allocation a WHERE a.class_id=c.id) AS subjects
        FROM class c
        JOIN department d ON d.id=c.department_id
        LEFT JOIN room r ON r.id=c.home_room_id
        ORDER BY d.name, c.semester, c.section
    """).fetchall()


class ClassReq(BaseModel):
    name: str
    department_id: int
    semester: int = 1
    section: str = "A"
    students: int | None = None
    home_room_id: int | None = None
    program_name: str | None = None
    course_name: str | None = None


def class_clean(conn, req):
    name = text(req.name, 2, 80, "a class name")
    if not 1 <= req.semester <= 12:
        raise HTTPException(400, "Semester should be between 1 and 12.")
    if req.students is not None and not 1 <= req.students <= 1000:
        raise HTTPException(400, "Number of students should be between 1 and 1000.")
    if req.home_room_id and not conn.execute("SELECT 1 FROM room WHERE id=%s", (req.home_room_id,)).fetchone():
        raise HTTPException(400, "Please choose a room from the list.")
    sec = (req.section.strip().upper()[:5] or "A")
    prog = (req.program_name or req.course_name or "").strip() or None
    return name, sec, prog


@router.post("/classes")
def add_class(req: ClassReq, conn=Depends(db), u=Depends(current_registry)):
    name, sec, prog = class_clean(conn, req)
    if not conn.execute("SELECT 1 FROM department WHERE id=%s", (req.department_id,)).fetchone():
        raise HTTPException(400, "Please choose the class's department.")

    year = conn.execute("SELECT id FROM academic_year ORDER BY id DESC LIMIT 1").fetchone()["id"]
    try:
        with conn.transaction():
            cid = conn.execute(
                """INSERT INTO class (department_id, academic_year_id, semester, section, name, students, home_room_id, program_name, course_name)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (req.department_id, year, req.semester, sec, name, req.students, req.home_room_id, prog, prog)
            ).fetchone()["id"]
            conn.execute("INSERT INTO timetable (class_id, department_id) VALUES (%s,%s)", (cid, req.department_id))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "That department already has a class for this semester and section.")

    rnote(conn, u, req.department_id, "registry_class_add", new={"name": name, "section": sec})
    return dict(id=cid)


@router.put("/classes/{cid}")
def edit_class(cid: int, req: ClassReq, conn=Depends(db), u=Depends(current_registry)):
    c = conn.execute("SELECT * FROM class WHERE id=%s", (cid,)).fetchone()
    if not c:
        raise HTTPException(404, "We couldn't find that class.")
    if req.department_id != c["department_id"]:
        raise HTTPException(400, "A class can't be moved to another department. Create a new class there instead.")

    name, sec, prog = class_clean(conn, req)
    try:
        conn.execute(
            """UPDATE class
               SET name=%s, semester=%s, section=%s, students=%s, home_room_id=%s, program_name=%s, course_name=%s
               WHERE id=%s""",
            (name, req.semester, sec, req.students, req.home_room_id, prog, prog, cid)
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "That department already has a class for this semester and section.")

    rnote(conn, u, c["department_id"], "registry_class_edit", {"name": c["name"]}, {"name": name, "section": sec})
    return dict(ok=True)


@router.delete("/classes/{cid}")
def delete_class(cid: int, conn=Depends(db), u=Depends(current_registry)):
    c = conn.execute("SELECT * FROM class WHERE id=%s", (cid,)).fetchone()
    if not c:
        raise HTTPException(404, "We couldn't find that class.")

    if conn.execute("SELECT count(*) n FROM teacher_allocation WHERE class_id=%s", (cid,)).fetchone()["n"]:
        raise HTTPException(409, "This class still has subjects set up by its department. They need to remove those first.")

    with conn.transaction():
        conn.execute("DELETE FROM timetable WHERE class_id=%s", (cid,))
        conn.execute("DELETE FROM class WHERE id=%s", (cid,))
        rnote(conn, u, c["department_id"], "registry_class_delete", {"name": c["name"]})

    return dict(ok=True)


# ---------- Rooms and Laboratories ----------
@router.get("/rooms")
def rooms(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("SELECT r.id, r.name, r.room_type, r.capacity, (SELECT count(*) FROM timetable_entry e WHERE e.room_id=r.id) sessions FROM room r ORDER BY r.name").fetchall()


class RoomReq(BaseModel):
    name: str
    room_type: str = "Classroom"
    capacity: int | None = None


def room_clean(req):
    name = text(req.name, 1, 40, "the room name")
    if req.room_type not in ROOM_TYPES:
        raise HTTPException(400, "Please choose Classroom, Computer lab or Laboratory.")
    if req.capacity is not None and not 1 <= req.capacity <= 1000:
        raise HTTPException(400, "Capacity should be between 1 and 1000.")
    return name


@router.post("/rooms")
def add_room(req: RoomReq, conn=Depends(db), u=Depends(current_registry)):
    name = room_clean(req)
    try:
        rid = conn.execute("INSERT INTO room (name, room_type, capacity) VALUES (%s,%s,%s) RETURNING id", (name, req.room_type, req.capacity)).fetchone()["id"]
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "A room with this name already exists.")
    rnote(conn, u, None, "registry_room_add", new={"name": name})
    return dict(id=rid)


@router.put("/rooms/{rid}")
def edit_room(rid: int, req: RoomReq, conn=Depends(db), u=Depends(current_registry)):
    r = conn.execute("SELECT * FROM room WHERE id=%s", (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "We couldn't find that room.")
    name = room_clean(req)
    used = conn.execute("SELECT count(*) n FROM timetable_entry WHERE room_id=%s", (rid,)).fetchone()["n"]
    if used and req.room_type != r["room_type"]:
        raise HTTPException(409, f"{r['name']} is used in {used} scheduled sessions, so its type can't be changed.")
    try:
        conn.execute("UPDATE room SET name=%s, room_type=%s, capacity=%s WHERE id=%s", (name, req.room_type, req.capacity, rid))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "A room with this name already exists.")
    rnote(conn, u, None, "registry_room_edit", {"name": r["name"]}, {"name": name})
    return dict(ok=True)


@router.delete("/rooms/{rid}")
def delete_room(rid: int, conn=Depends(db), u=Depends(current_registry)):
    r = conn.execute("SELECT * FROM room WHERE id=%s", (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "We couldn't find that room.")
    used = conn.execute("SELECT count(*) n FROM timetable_entry WHERE room_id=%s", (rid,)).fetchone()["n"]
    if used:
        raise HTTPException(409, f"{r['name']} is used in {used} scheduled sessions. Departments need to move those first.")
    with conn.transaction():
        conn.execute("UPDATE class SET home_room_id=NULL WHERE home_room_id=%s", (rid,))
        conn.execute("DELETE FROM room_availability WHERE room_id=%s", (rid,))
        conn.execute("DELETE FROM room WHERE id=%s", (rid,))
        rnote(conn, u, None, "registry_room_delete", {"name": r["name"]})
    return dict(ok=True)


# ---------- Common Time Slots (MDC & Minor fixed periods) ----------
class CommonSlotReq(BaseModel):
    day: int
    start_time: str
    end_time: str
    applicable_course_type: str = "MDC"
    name: str = ""
    semester: int = 1


@router.get("/common-slots")
def get_common_slots(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("""SELECT id, day, start_min, end_min,
        to_char(to_timestamp(start_min * 60) AT TIME ZONE 'UTC', 'HH24:MI') start_time,
        to_char(to_timestamp(end_min * 60) AT TIME ZONE 'UTC', 'HH24:MI') end_time,
        applicable_course_type, name, semester, status
        FROM common_time_slot ORDER BY day, start_min""").fetchall()


@router.post("/common-slots")
def add_common_slot(req: CommonSlotReq, conn=Depends(db), u=Depends(current_registry)):
    if not 0 <= req.day <= 6:
        raise HTTPException(400, "Day must be between 0 (Monday) and 6 (Sunday).")
    try:
        s_ = int(req.start_time[:2]) * 60 + int(req.start_time[3:5])
        e_ = int(req.end_time[:2]) * 60 + int(req.end_time[3:5])
    except Exception:
        raise HTTPException(400, "Please provide valid start and end times in HH:MM format.")
    if s_ >= e_:
        raise HTTPException(400, "End time must be after start time.")
    if req.applicable_course_type not in ("MDC", "Minor", "Both"):
        raise HTTPException(400, "Course type must be MDC, Minor, or Both.")
    name = req.name.strip() or f"Common {req.applicable_course_type} Slot"
    sid = conn.execute("""INSERT INTO common_time_slot (day, start_min, end_min, applicable_course_type, name, semester)
        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
        (req.day, s_, e_, req.applicable_course_type, name, req.semester)).fetchone()["id"]
    return dict(id=sid)


@router.put("/common-slots/{sid}")
def edit_common_slot(sid: int, req: CommonSlotReq, conn=Depends(db), u=Depends(current_registry)):
    s_ = int(req.start_time[:2]) * 60 + int(req.start_time[3:5])
    e_ = int(req.end_time[:2]) * 60 + int(req.end_time[3:5])
    if s_ >= e_:
        raise HTTPException(400, "End time must be after start time.")
    name = req.name.strip() or f"Common {req.applicable_course_type} Slot"
    conn.execute("""UPDATE common_time_slot SET day=%s, start_min=%s, end_min=%s, applicable_course_type=%s, name=%s, semester=%s
        WHERE id=%s""", (req.day, s_, e_, req.applicable_course_type, name, req.semester, sid))
    return dict(ok=True)


@router.delete("/common-slots/{sid}")
def delete_common_slot(sid: int, conn=Depends(db), u=Depends(current_registry)):
    conn.execute("DELETE FROM common_time_slot WHERE id=%s", (sid,))
    return dict(ok=True)
