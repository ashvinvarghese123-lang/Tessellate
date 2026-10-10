"""College Registry: an EXTERNAL, DATA-ONLY account.

It maintains the shared master data every department reads (departments, faculty, classes, rooms).
It has NO access to timetables, subjects/allocations, generation, publishing or any department workspace,
and it gives no department any priority. Login = password + emailed one-time code, same as departments.
"""
import hashlib, hmac, re, secrets
from datetime import timedelta
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from psycopg.types.json import Jsonb

from .auth import (hash_password, check_password, strong_enough, send_email, mask, code_hash, now, _DUMMY,
                   OTP_MINUTES, MAX_TRIES, RESEND_SECONDS, MAX_SENDS, SESSION_HOURS, IDLE_MINUTES, LOCK_AFTER, LOCK_MINUTES)
from .db import db
import os

COOKIE = "tess_registry"
router = APIRouter(prefix="/api/registry")
ROOM_TYPES = ("Classroom", "Computer lab", "Laboratory")


# ---------- sign-in (same security as departments) ----------
class LoginReq(BaseModel):
    username: str
    password: str


def _issue(conn, acct, cid=None):
    code = f"{secrets.randbelow(10**6):06d}"
    if cid is None:
        cid = conn.execute("INSERT INTO registry_challenge (account_id, code_hash, expires_at) VALUES (%s,'',%s) RETURNING id",
                           (acct["id"], now() + timedelta(minutes=OTP_MINUTES))).fetchone()["id"]
    conn.execute("UPDATE registry_challenge SET code_hash=%s, expires_at=%s, attempts=0, last_sent_at=now() WHERE id=%s",
                 (code_hash(cid, code), now() + timedelta(minutes=OTP_MINUTES), cid))
    send_email(acct["email"], "Your Tessellate Registry verification code",
               f"Your code is {code}. It expires in {OTP_MINUTES} minutes. If this wasn't you, ignore this email.")
    return str(cid)


@router.post("/auth/login")
def login(req: LoginReq, conn=Depends(db)):
    bad = HTTPException(401, "The username or password is incorrect.")
    a = conn.execute("SELECT * FROM registry_account WHERE username=%s AND active", (req.username.strip().lower(),)).fetchone()
    if not a:
        check_password(req.password, _DUMMY)
        raise bad
    if a["locked_until"] and a["locked_until"] > now():
        raise HTTPException(429, "Too many attempts. Please wait a few minutes and try again.")
    if not check_password(req.password, a["password_hash"]):
        n = a["failed_logins"] + 1
        conn.execute("UPDATE registry_account SET failed_logins=%s, locked_until=%s WHERE id=%s",
                     (0 if n >= LOCK_AFTER else n, now() + timedelta(minutes=LOCK_MINUTES) if n >= LOCK_AFTER else None, a["id"]))
        conn.commit()
        raise bad
    conn.execute("UPDATE registry_account SET failed_logins=0, locked_until=NULL WHERE id=%s", (a["id"],))
    cid = _issue(conn, a)
    conn.commit()
    return dict(challenge_id=cid, email_hint=mask(a["email"]))


def _chal(conn, cid):
    try:
        return conn.execute("SELECT c.*, a.email, a.username FROM registry_challenge c JOIN registry_account a ON a.id=c.account_id WHERE c.id=%s", (cid,)).fetchone()
    except Exception:
        conn.rollback()
        return None


@router.post("/auth/verify")
def verify(req: dict, response: Response, conn=Depends(db)):
    c = _chal(conn, req.get("challenge_id"))
    if not c or c["used"] or c["expires_at"] < now():
        raise HTTPException(400, "This code has expired. Please request a new one.")
    if c["attempts"] >= MAX_TRIES:
        raise HTTPException(429, "Too many incorrect codes. Please sign in again.")
    if not hmac.compare_digest(c["code_hash"], code_hash(c["id"], str(req.get("code", "")).strip())):
        conn.execute("UPDATE registry_challenge SET attempts=attempts+1 WHERE id=%s", (c["id"],))
        conn.commit()
        raise HTTPException(400, "That code isn't correct. Please check it and try again.")
    conn.execute("UPDATE registry_challenge SET used=TRUE WHERE id=%s", (c["id"],))
    tok = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO registry_session (token_hash, account_id, expires_at) VALUES (%s,%s,%s)",
                 (hashlib.sha256(tok.encode()).hexdigest(), c["account_id"], now() + timedelta(hours=SESSION_HOURS)))
    conn.commit()
    response.set_cookie(COOKIE, tok, httponly=True, samesite="lax", max_age=SESSION_HOURS * 3600, secure=os.environ.get("COOKIE_SECURE", "0") == "1")
    return dict(ok=True)


@router.post("/auth/resend")
def resend(req: dict, conn=Depends(db)):
    c = _chal(conn, req.get("challenge_id"))
    if not c or c["used"]:
        raise HTTPException(400, "Please sign in again.")
    if (now() - c["last_sent_at"]).total_seconds() < RESEND_SECONDS:
        raise HTTPException(429, f"Please wait {RESEND_SECONDS} seconds before asking for another code.")
    if c["sends"] >= MAX_SENDS:
        raise HTTPException(429, "Too many codes requested. Please sign in again later.")
    _issue(conn, conn.execute("SELECT * FROM registry_account WHERE id=%s", (c["account_id"],)).fetchone(), c["id"])
    conn.execute("UPDATE registry_challenge SET sends=sends+1 WHERE id=%s", (c["id"],))
    conn.commit()
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
    return dict(id=s["account_id"], username=s["username"], email_hint=mask(s["email"]), token_hash=h)


@router.get("/auth/me")
def me(u=Depends(current_registry)):
    return dict(username=u["username"], email_hint=u["email_hint"])


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


@router.post("/auth/forgot")
def forgot(req: dict, conn=Depends(db)):
    a = conn.execute("SELECT * FROM registry_account WHERE username=%s AND active", (str(req.get("username", "")).strip().lower(),)).fetchone()
    if a:
        tok = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO registry_reset (token_hash, account_id, expires_at) VALUES (%s,%s,%s)", (hashlib.sha256(tok.encode()).hexdigest(), a["id"], now() + timedelta(minutes=30)))
        send_email(a["email"], "Reset your Tessellate Registry password", f"Use this code in the reset screen within 30 minutes: {tok}")
        conn.commit()
    return dict(message="If that username exists, a reset message has been sent to the registered email.")


@router.post("/auth/reset")
def reset(req: dict, conn=Depends(db)):
    h = hashlib.sha256(str(req.get("token", "")).encode()).hexdigest()
    r = conn.execute("SELECT * FROM registry_reset WHERE token_hash=%s AND NOT used AND expires_at>now()", (h,)).fetchone()
    if not r:
        raise HTTPException(400, "This reset code has expired. Please request a new one.")
    new = str(req.get("new_password", ""))
    strong_enough(new)
    conn.execute("UPDATE registry_account SET password_hash=%s, failed_logins=0, locked_until=NULL WHERE id=%s", (hash_password(new), r["account_id"]))
    conn.execute("UPDATE registry_reset SET used=TRUE WHERE token_hash=%s", (h,))
    conn.execute("UPDATE registry_session SET revoked=TRUE WHERE account_id=%s", (r["account_id"],))
    conn.commit()
    return dict(ok=True)


# ---------- shared master data ----------
def rnote(conn, u, dept_id, action, old=None, new=None):
    """Departments see these in their own history, marked as coming from the Registry."""
    conn.execute("INSERT INTO audit_log (department_id, action, old_value, new_value, reason) VALUES (%s,%s,%s,%s,%s)",
                 (dept_id, action, Jsonb(old) if old else None, Jsonb(new) if new else None, f"Registry ({u['username']})"))


def text(v, lo, hi, what):
    v = " ".join(str(v or "").split())
    if not lo <= len(v) <= hi:
        raise HTTPException(400, f"Please enter {what}.")
    return v


@router.get("/overview")
def overview(conn=Depends(db), u=Depends(current_registry)):
    n = lambda t, w="": conn.execute(f"SELECT count(*) n FROM {t} {w}").fetchone()["n"]
    return dict(departments=n("department"), department_accounts=n("department_account"), faculty=n("faculty", "WHERE active"),
                classes=n("class"), rooms=n("room"), subjects=n("teacher_allocation"), scheduled_sessions=n("timetable_entry"))


# -- departments
@router.get("/departments")
def departments(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("""SELECT d.id, d.code, d.name,
        (SELECT count(*) FROM class c WHERE c.department_id=d.id) classes,
        (SELECT count(*) FROM faculty f WHERE f.home_department_id=d.id AND f.active) faculty,
        EXISTS(SELECT 1 FROM department_account a WHERE a.department_id=d.id) has_account FROM department d ORDER BY d.name""").fetchall()


class DeptReq(BaseModel):
    name: str


@router.post("/departments")
def add_department(req: DeptReq, conn=Depends(db), u=Depends(current_registry)):
    name = text(req.name, 2, 60, "the department name")
    if conn.execute("SELECT 1 FROM department WHERE lower(name)=lower(%s)", (name,)).fetchone():
        raise HTTPException(409, "A department with this name already exists.")
    base = "DEPT-" + (re.sub(r"[^A-Z0-9]", "", name.upper())[:8] or "NEW")
    code, k = base, 1
    while conn.execute("SELECT 1 FROM department WHERE code=%s", (code,)).fetchone():
        k += 1
        code = f"{base}{k}"
    did = conn.execute("INSERT INTO department (code, name) VALUES (%s,%s) RETURNING id", (code, name)).fetchone()["id"]
    rnote(conn, u, did, "registry_department_add", new={"name": name})
    return dict(id=did, code=code)


@router.put("/departments/{did}")
def rename_department(did: int, req: DeptReq, conn=Depends(db), u=Depends(current_registry)):
    name = text(req.name, 2, 60, "the department name")
    old = conn.execute("SELECT name FROM department WHERE id=%s", (did,)).fetchone()
    if not old:
        raise HTTPException(404, "We couldn't find that department.")
    if conn.execute("SELECT 1 FROM department WHERE lower(name)=lower(%s) AND id<>%s", (name, did)).fetchone():
        raise HTTPException(409, "A department with this name already exists.")
    conn.execute("UPDATE department SET name=%s WHERE id=%s", (name, did))
    rnote(conn, u, did, "registry_department_edit", {"name": old["name"]}, {"name": name})
    return dict(ok=True)


@router.delete("/departments/{did}")
def delete_department(did: int, conn=Depends(db), u=Depends(current_registry)):
    chk = lambda q: conn.execute(q, (did,)).fetchone()["n"]
    if chk("SELECT count(*) n FROM department_account WHERE department_id=%s"):
        raise HTTPException(409, "This department already has a login account, so it can't be deleted.")
    if chk("SELECT count(*) n FROM class WHERE department_id=%s") or chk("SELECT count(*) n FROM faculty WHERE home_department_id=%s") or chk("SELECT count(*) n FROM subject WHERE department_id=%s"):
        raise HTTPException(409, "This department still has classes, faculty or subjects. Remove or move them first.")
    with conn.transaction():
        conn.execute("UPDATE audit_log SET department_id=NULL WHERE department_id=%s", (did,))      # keep the history
        conn.execute("UPDATE generation_run SET department_id=NULL WHERE department_id=%s", (did,))
        conn.execute("DELETE FROM notification WHERE department_id=%s", (did,))
        conn.execute("DELETE FROM department WHERE id=%s", (did,))
        rnote(conn, u, None, "registry_department_delete", {"id": did})
    return dict(ok=True)


# -- faculty
@router.get("/faculty")
def faculty(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("""SELECT f.id, f.faculty_code, f.name, f.designation, f.email, f.max_weekly_sessions, f.home_department_id,
        dp.name department, (SELECT count(*) FROM timetable_entry e WHERE e.faculty_id=f.id) sessions
        FROM faculty f LEFT JOIN department dp ON dp.id=f.home_department_id WHERE f.active ORDER BY f.faculty_code""").fetchall()


class FacReq(BaseModel):
    name: str
    home_department_id: int
    designation: str | None = None
    email: str | None = None
    max_weekly_sessions: int = 18


def fac_clean(conn, req):
    name = text(req.name, 2, 80, "the teacher's name")
    if not 1 <= req.max_weekly_sessions <= 40:
        raise HTTPException(400, "Weekly sessions should be between 1 and 40.")
    email = (req.email or "").strip().lower() or None
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "That email address doesn't look right.")
    if not conn.execute("SELECT 1 FROM department WHERE id=%s", (req.home_department_id,)).fetchone():
        raise HTTPException(400, "Please choose the teacher's home department.")
    return name, (req.designation or "").strip() or None, email


@router.post("/faculty")
def add_faculty(req: FacReq, conn=Depends(db), u=Depends(current_registry)):
    name, desig, email = fac_clean(conn, req)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(2)")
        if conn.execute("SELECT 1 FROM faculty WHERE lower(name)=lower(%s) AND home_department_id=%s AND active", (name, req.home_department_id)).fetchone():
            raise HTTPException(409, "A teacher with this name already exists in that department.")
        n = conn.execute("SELECT coalesce(max(substring(faculty_code from 5)::int),0)+1 n FROM faculty WHERE faculty_code ~ '^FAC-[0-9]+$'").fetchone()["n"]
        r = conn.execute("INSERT INTO faculty (faculty_code, name, home_department_id, designation, email, max_weekly_sessions) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, faculty_code",
                         (f"FAC-{n:03d}", name, req.home_department_id, desig, email, req.max_weekly_sessions)).fetchone()
        rnote(conn, u, req.home_department_id, "registry_faculty_add", new={"name": name, "code": r["faculty_code"]})
    return dict(id=r["id"], faculty_code=r["faculty_code"])


@router.put("/faculty/{fid}")
def edit_faculty(fid: int, req: FacReq, conn=Depends(db), u=Depends(current_registry)):
    f = conn.execute("SELECT * FROM faculty WHERE id=%s AND active", (fid,)).fetchone()
    if not f:
        raise HTTPException(404, "We couldn't find that teacher.")
    name, desig, email = fac_clean(conn, req)
    used = conn.execute("SELECT count(*) n FROM timetable_entry WHERE faculty_id=%s", (fid,)).fetchone()["n"]
    if req.max_weekly_sessions < used:
        raise HTTPException(409, f"{f['name']} already has {used} sessions this week, so the limit can't be lower than {used}.")
    if conn.execute("SELECT 1 FROM faculty WHERE lower(name)=lower(%s) AND home_department_id=%s AND active AND id<>%s", (name, req.home_department_id, fid)).fetchone():
        raise HTTPException(409, "Another teacher in that department already has this name.")
    conn.execute("UPDATE faculty SET name=%s, home_department_id=%s, designation=%s, email=%s, max_weekly_sessions=%s WHERE id=%s",
                 (name, req.home_department_id, desig, email, req.max_weekly_sessions, fid))
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
    conn.execute("UPDATE faculty SET active=FALSE WHERE id=%s", (fid,))
    rnote(conn, u, f["home_department_id"], "registry_faculty_remove", {"name": f["name"]})
    return dict(ok=True)


# -- classes
@router.get("/classes")
def classes(conn=Depends(db), u=Depends(current_registry)):
    return conn.execute("""SELECT c.id, c.name, c.department_id, d.name department, c.semester, c.section, c.students, c.home_room_id, r.name home_room,
        (SELECT count(*) FROM teacher_allocation a WHERE a.class_id=c.id) subjects
        FROM class c JOIN department d ON d.id=c.department_id LEFT JOIN room r ON r.id=c.home_room_id ORDER BY d.name, c.semester, c.section""").fetchall()


class ClassReq(BaseModel):
    name: str
    department_id: int
    semester: int = 1
    section: str = "A"
    students: int | None = None
    home_room_id: int | None = None


def class_clean(conn, req):
    name = text(req.name, 2, 80, "a class name")
    if not 1 <= req.semester <= 12:
        raise HTTPException(400, "Semester should be between 1 and 12.")
    if req.students is not None and not 1 <= req.students <= 1000:
        raise HTTPException(400, "Number of students should be between 1 and 1000.")
    if req.home_room_id and not conn.execute("SELECT 1 FROM room WHERE id=%s", (req.home_room_id,)).fetchone():
        raise HTTPException(400, "Please choose a room from the list.")
    return name, (req.section.strip().upper()[:3] or "A")


@router.post("/classes")
def add_class(req: ClassReq, conn=Depends(db), u=Depends(current_registry)):
    name, sec = class_clean(conn, req)
    if not conn.execute("SELECT 1 FROM department WHERE id=%s", (req.department_id,)).fetchone():
        raise HTTPException(400, "Please choose the class's department.")
    year = conn.execute("SELECT id FROM academic_year ORDER BY id DESC LIMIT 1").fetchone()["id"]
    try:
        with conn.transaction():
            cid = conn.execute("INSERT INTO class (department_id, academic_year_id, semester, section, name, students, home_room_id) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                               (req.department_id, year, req.semester, sec, name, req.students, req.home_room_id)).fetchone()["id"]
            conn.execute("INSERT INTO timetable (class_id, department_id) VALUES (%s,%s)", (cid, req.department_id))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "That department already has a class for this semester and section.")
    rnote(conn, u, req.department_id, "registry_class_add", new={"name": name})
    return dict(id=cid)


@router.put("/classes/{cid}")
def edit_class(cid: int, req: ClassReq, conn=Depends(db), u=Depends(current_registry)):
    c = conn.execute("SELECT * FROM class WHERE id=%s", (cid,)).fetchone()
    if not c:
        raise HTTPException(404, "We couldn't find that class.")
    if req.department_id != c["department_id"]:
        raise HTTPException(400, "A class can't be moved to another department. Create a new class there instead.")
    name, sec = class_clean(conn, req)
    try:
        conn.execute("UPDATE class SET name=%s, semester=%s, section=%s, students=%s, home_room_id=%s WHERE id=%s", (name, req.semester, sec, req.students, req.home_room_id, cid))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "That department already has a class for this semester and section.")
    rnote(conn, u, c["department_id"], "registry_class_edit", {"name": c["name"]}, {"name": name})
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


# -- rooms and laboratories
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
