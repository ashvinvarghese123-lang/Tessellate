"""Tessellate API. Run from the backend folder:  uvicorn api.main:app

Every route learns the department from the signed-in session (api/auth.py). There are no roles and no
department priority: all departments use the same rules and the same shared resources.
"""
import logging
import re
import psycopg
from psycopg.types.json import Jsonb
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import os
from pydantic import BaseModel

from engine.solver import generate, rebalance, validate_move
from .auth import current_department, router as auth_router
from .registry import router as registry_router
from .db import db

# Refuse to start in production with unsafe settings (so a mistake shows up at deploy time, not as a breach later).
if os.environ.get("TESSELLATE_ENV") == "production":
    _bad = []
    if len(os.environ.get("TESSELLATE_SECRET", "")) < 32:
        _bad.append("TESSELLATE_SECRET must be a random value of at least 32 characters")
    if os.environ.get("COOKIE_SECURE") != "1":
        _bad.append("COOKIE_SECURE must be 1 (HTTPS only)")
    if not os.environ.get("SMTP_HOST"):
        _bad.append("SMTP_HOST (and SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM) must be set so codes are emailed, not logged")
    if not os.environ.get("DATABASE_URL"):
        _bad.append("DATABASE_URL must be set")
    if _bad:
        raise RuntimeError("Production settings missing: " + "; ".join(_bad))

app = FastAPI(title="Tessellate")
app.include_router(auth_router)
app.include_router(registry_router)
log = logging.getLogger("tessellate")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@app.exception_handler(Exception)
async def friendly(request, exc):   # never show SQL errors, stack traces or solver messages
    log.exception("unhandled")
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again, and check the faculty and room settings if it continues."})


def slots(conn):
    return {r["id"]: (r["day"], r["period"], str(r["starts"])[:5], str(r["ends"])[:5]) for r in conn.execute("SELECT * FROM time_slot")}


def when(s):
    return f"{DAYS[s[0]]} · {s[2]}–{s[3]}"


def own_class(conn, d, class_id):
    c = conn.execute("SELECT * FROM class WHERE id=%s", (class_id,)).fetchone()
    if not c:
        raise HTTPException(404, "We couldn't find that class.")
    if c["department_id"] != d["id"]:
        raise HTTPException(403, "This class belongs to another department. You can view shared resources but not change their timetable.")
    return c


def shared(conn, sl):
    """Teachers and rooms are college-wide records. Same data for every department."""
    teachers = {}
    for f in conn.execute("SELECT * FROM faculty WHERE active"):
        un = conn.execute("""SELECT ts.day, ts.period FROM faculty_availability fa JOIN time_slot ts ON ts.id=fa.time_slot_id
                             WHERE fa.faculty_id=%s AND fa.kind='unavailable'""", (f["id"],)).fetchall()
        teachers[f["id"]] = dict(name=f["name"], max_load=f["max_weekly_sessions"], unavailable=[[u["day"], u["period"]] for u in un])
    return teachers, [dict(id=r["id"], type=r["room_type"]) for r in conn.execute("SELECT * FROM room")]


def placed(conn, sl, exclude_entry=None, only_class=None, exclude_class=None, dept_not=None):
    """Sessions already saved, as 'busy' records that carry a plain-language reason."""
    q = """SELECT x.*, d.name department, s.name subject, c.name class_name FROM timetable_entry x
           JOIN class c ON c.id=x.class_id JOIN department d ON d.id=c.department_id
           JOIN teacher_allocation a ON a.id=x.allocation_id JOIN subject s ON s.id=a.subject_id WHERE TRUE"""
    out = []
    for o in conn.execute(q):
        if o["id"] == exclude_entry or o["class_id"] == exclude_class:
            continue
        day, per, _, _ = sl[o["time_slot_id"]]
        out.append(dict(teacher=o["faculty_id"], room=o["room_id"], day=day, period=per, subject=o["subject"],
                        department=o["department"], class_name=o["class_name"], **{"class": o["class_id"]}))
    return out


def build_input(conn, d, class_id=None, joint=False):
    sl = slots(conn)
    cfg = conn.execute("SELECT days, periods FROM college LIMIT 1").fetchone()
    teachers, rooms = shared(conn, sl)
    where, args = ("", ()) if joint else ("WHERE c.department_id=%s" + (" AND c.id=%s" if class_id else ""), (d["id"],) + ((class_id,) if class_id else ()))
    classes = {c["id"]: dict(name=c["name"], department=c["code"]) for c in conn.execute(
        "SELECT c.id, c.name, dp.code FROM class c JOIN department dp ON dp.id=c.department_id " + where.replace("c.department_id", "c.department_id"), args)}
    allocs = [dict(**{"class": a["class_id"]}, subject=a["subject"], teacher=a["faculty_id"], sessions=a["sessions_per_week"],
                   room_type=a["required_room_type"], id=a["id"], department=a["code"])
              for a in conn.execute("""SELECT a.*, s.name subject, s.required_room_type, dp.code FROM teacher_allocation a
                  JOIN subject s ON s.id=a.subject_id JOIN class c ON c.id=a.class_id JOIN department dp ON dp.id=c.department_id """ + where, args)]
    ids = set(classes)
    busy = [] if joint else [b for b in placed(conn, sl) if b["class"] not in ids]
    # workload already used by sessions that stay as they are
    for t, T in teachers.items():
        T["existing_load"] = sum(1 for b in busy if b["teacher"] == t)
    data = dict(config=cfg, teachers=teachers, classes=classes, rooms=rooms, allocations=allocs, busy=busy)
    if joint:
        idx = {a["id"]: i for i, a in enumerate(allocs)}
        data["current"] = [dict(allocation=idx[o["allocation_id"]], day=sl[o["time_slot_id"]][0], period=sl[o["time_slot_id"]][1], room=o["room_id"])
                           for o in conn.execute("SELECT * FROM timetable_entry") if o["allocation_id"] in idx]
    return data, sl


def note(conn, dept_id, action, entry_id=None, old=None, new=None, reason=None):
    conn.execute("INSERT INTO audit_log (department_id, action, entry_id, old_value, new_value, reason) VALUES (%s,%s,%s,%s,%s,%s)",
                 (dept_id, action, entry_id, Jsonb(old) if old else None, Jsonb(new) if new else None, reason))


# ---------- generate / rebalance ----------
class GenReq(BaseModel):
    class_id: int | None = None


@app.post("/api/generate")
def generate_timetable(req: GenReq, conn=Depends(db), d=Depends(current_department)):
    if req.class_id:
        own_class(conn, d, req.class_id)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(1)")      # one change to shared resources at a time
        data, sl = build_input(conn, d, req.class_id)
        if not data["allocations"]:
            raise HTTPException(400, "Add classes and subjects first, then generate.")
        res = generate(data, 20)
        conn.execute("""INSERT INTO generation_run (department_id, scope, status, quality, problems, started_by)
                        VALUES (%s,%s,%s,%s,%s,%s)""", (d["id"], "class" if req.class_id else "department", res["status"], res.get("score"),
                                                        Jsonb(res["problems"]), d["account_id"]))
        if res["status"] != "ok":
            return dict(status="impossible", message="We couldn't create a valid timetable with the current settings.",
                        problems=res["problems"], suggestions=res["suggestions"], can_look_for_alternative=True)
        by_slot = {(v[0], v[1]): k for k, v in sl.items()}
        conn.execute("DELETE FROM timetable_entry WHERE class_id = ANY(%s)", (list(data["classes"]),))
        for e in res["entries"]:
            conn.execute("""INSERT INTO timetable_entry (timetable_id, allocation_id, class_id, faculty_id, room_id, time_slot_id)
                SELECT t.id, %s, %s, %s, %s, %s FROM timetable t WHERE t.class_id=%s""",
                         (data["allocations"][e["allocation"]]["id"], e["class"], e["teacher"], e["room"], by_slot[(e["day"], e["period"])], e["class"]))
        note(conn, d["id"], "generate", new={"quality": res["score"], "sessions": len(res["entries"])})
    return dict(status="ok", quality=res["score"], sessions=len(res["entries"]))


@app.post("/api/alternatives")
def look_for_alternative(conn=Depends(db), d=Depends(current_department)):
    """Equal priority: solves ALL departments together and reports what would change. Applies nothing."""
    data, sl = build_input(conn, d, joint=True)
    res = rebalance(data, 20)
    if res["status"] != "ok":
        return dict(status="impossible", message="Even with every department's timetable rearranged, the current settings don't fit.",
                    problems=res["problems"], suggestions=res["suggestions"])
    names = {c["code"]: c["name"] for c in conn.execute("SELECT code, name FROM department")}
    return dict(status="proposal", quality=res["score"],
                affected_departments=[dict(department=names.get(k, k), sessions_changed=v) for k, v in res["moved_by_department"].items()],
                message="A better college-wide arrangement exists. Nothing has been changed. Each affected department keeps its own timetable until it chooses to regenerate.")


# ---------- read: workspace + shared resources ----------
@app.get("/api/dashboard")
def dashboard(conn=Depends(db), d=Depends(current_department)):
    n = lambda q, *a: conn.execute(q, a).fetchone()["n"]
    st = conn.execute("SELECT status FROM timetable WHERE department_id=%s GROUP BY status", (d["id"],)).fetchall()
    return dict(department=dict(code=d["code"], name=d["name"]),
                classes=n("SELECT count(*) n FROM class WHERE department_id=%s", d["id"]),
                subjects=n("SELECT count(*) n FROM teacher_allocation a JOIN class c ON c.id=a.class_id WHERE c.department_id=%s", d["id"]),
                faculty=n("SELECT count(DISTINCT a.faculty_id) n FROM teacher_allocation a JOIN class c ON c.id=a.class_id WHERE c.department_id=%s", d["id"]),
                sessions=n("SELECT count(*) n FROM timetable_entry e JOIN class c ON c.id=e.class_id WHERE c.department_id=%s", d["id"]),
                status=[r["status"] for r in st])


class ClassReq(BaseModel):
    name: str
    semester: int = 1
    section: str = "A"
    students: int | None = None


@app.post("/api/classes")
def add_class(req: ClassReq, conn=Depends(db), d=Depends(current_department)):
    name, sec = " ".join(req.name.split()), req.section.strip().upper()[:3] or "A"
    if not 2 <= len(name) <= 80:
        raise HTTPException(400, "Please enter a class name, for example \u201cBSc Chemistry \u00b7 Sem 1 \u00b7 A\u201d.")
    if not 1 <= req.semester <= 12:
        raise HTTPException(400, "Semester should be between 1 and 12.")
    year = conn.execute("SELECT id FROM academic_year ORDER BY id DESC LIMIT 1").fetchone()["id"]
    try:
        with conn.transaction():
            cid = conn.execute("""INSERT INTO class (department_id, academic_year_id, semester, section, name, students)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""", (d["id"], year, req.semester, sec, name, req.students)).fetchone()["id"]
            conn.execute("INSERT INTO timetable (class_id, department_id) VALUES (%s,%s)", (cid, d["id"]))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "You already have a class for that semester and section.")
    note(conn, d["id"], "add_class", new={"name": name})
    return dict(id=cid)


@app.get("/api/classes")
def classes(conn=Depends(db), d=Depends(current_department)):
    return conn.execute("SELECT id, name, semester, section, students FROM class WHERE department_id=%s ORDER BY id", (d["id"],)).fetchall()


@app.get("/api/timetable/{class_id}")
def class_timetable(class_id: int, conn=Depends(db), d=Depends(current_department)):
    own_class(conn, d, class_id)
    sl = slots(conn)
    rows = conn.execute("""SELECT e.id, e.time_slot_id, s.name subject, f.name teacher, r.name room, s.kind FROM timetable_entry e
        JOIN teacher_allocation a ON a.id=e.allocation_id JOIN subject s ON s.id=a.subject_id
        JOIN faculty f ON f.id=e.faculty_id JOIN room r ON r.id=e.room_id WHERE e.class_id=%s""", (class_id,)).fetchall()
    return [dict(id=r["id"], day=sl[r["time_slot_id"]][0], period=sl[r["time_slot_id"]][1], subject=r["subject"], teacher=r["teacher"], room=r["room"], lab=r["kind"] == "Lab") for r in rows]


def view(conn, col, rid):
    sl = slots(conn)
    rows = conn.execute(f"""SELECT e.time_slot_id, s.name subject, f.name teacher, r.name room, c.name class_name, dp.name department
        FROM timetable_entry e JOIN teacher_allocation a ON a.id=e.allocation_id JOIN subject s ON s.id=a.subject_id
        JOIN faculty f ON f.id=e.faculty_id JOIN room r ON r.id=e.room_id JOIN class c ON c.id=e.class_id
        JOIN department dp ON dp.id=c.department_id WHERE e.{col}=%s""", (rid,)).fetchall()
    return [dict(day=sl[r["time_slot_id"]][0], period=sl[r["time_slot_id"]][1], **{k: r[k] for k in ("subject", "teacher", "room", "class_name", "department")}) for r in rows]


@app.get("/api/faculty")
def faculty(conn=Depends(db), d=Depends(current_department)):
    return conn.execute("""SELECT f.id, f.faculty_code, f.name, dp.name department, f.designation, f.email, f.max_weekly_sessions,
        (f.home_department_id = %s) AS editable,
        (SELECT count(*) FROM timetable_entry e WHERE e.faculty_id=f.id) AS sessions
        FROM faculty f LEFT JOIN department dp ON dp.id=f.home_department_id WHERE f.active ORDER BY f.faculty_code""", (d["id"],)).fetchall()


class FacReq(BaseModel):
    name: str
    designation: str | None = None
    email: str | None = None
    max_weekly_sessions: int = 18


def clean_fac(req):
    name = " ".join(req.name.split())
    if not 2 <= len(name) <= 80:
        raise HTTPException(400, "Please enter the teacher's name.")
    if not 1 <= req.max_weekly_sessions <= 40:
        raise HTTPException(400, "Weekly sessions should be between 1 and 40.")
    email = (req.email or "").strip().lower() or None
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "That email address doesn't look right.")
    return name, (req.designation or "").strip() or None, email


def own_faculty(conn, d, fid):
    f = conn.execute("SELECT f.*, dp.name dept_name FROM faculty f LEFT JOIN department dp ON dp.id=f.home_department_id WHERE f.id=%s AND f.active", (fid,)).fetchone()
    if not f:
        raise HTTPException(404, "We couldn't find that teacher.")
    if f["home_department_id"] != d["id"]:
        raise HTTPException(403, f"{f['name']} belongs to {f['dept_name'] or 'another department'}. Ask them to change this teacher's details.")
    return f


@app.post("/api/faculty")
def add_faculty(req: FacReq, conn=Depends(db), d=Depends(current_department)):
    name, desig, email = clean_fac(req)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(2)")
        if conn.execute("SELECT 1 FROM faculty WHERE lower(name)=lower(%s) AND home_department_id=%s AND active", (name, d["id"])).fetchone():
            raise HTTPException(409, "A teacher with this name already exists in your department.")
        n = conn.execute("SELECT coalesce(max(substring(faculty_code from 5)::int),0)+1 n FROM faculty WHERE faculty_code ~ '^FAC-[0-9]+$'").fetchone()["n"]
        row = conn.execute("""INSERT INTO faculty (faculty_code, name, home_department_id, designation, email, max_weekly_sessions)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, faculty_code""", (f"FAC-{n:03d}", name, d["id"], desig, email, req.max_weekly_sessions)).fetchone()
        note(conn, d["id"], "faculty_add", new={"name": name, "code": row["faculty_code"]})
    return dict(id=row["id"], faculty_code=row["faculty_code"])


@app.put("/api/faculty/{fid}")
def edit_faculty(fid: int, req: FacReq, conn=Depends(db), d=Depends(current_department)):
    f = own_faculty(conn, d, fid)
    name, desig, email = clean_fac(req)
    used = conn.execute("SELECT count(*) n FROM timetable_entry WHERE faculty_id=%s", (fid,)).fetchone()["n"]
    if req.max_weekly_sessions < used:
        raise HTTPException(409, f"{f['name']} already has {used} sessions this week, so the limit can't be lower than {used}.")
    if conn.execute("SELECT 1 FROM faculty WHERE lower(name)=lower(%s) AND home_department_id=%s AND active AND id<>%s", (name, d["id"], fid)).fetchone():
        raise HTTPException(409, "Another teacher in your department already has this name.")
    conn.execute("UPDATE faculty SET name=%s, designation=%s, email=%s, max_weekly_sessions=%s WHERE id=%s",
                 (name, desig, email, req.max_weekly_sessions, fid))
    note(conn, d["id"], "faculty_edit", old={"name": f["name"], "max": f["max_weekly_sessions"]}, new={"name": name, "max": req.max_weekly_sessions})
    return dict(ok=True)


class UnavReq(BaseModel):
    slots: list[list[int]]


@app.put("/api/faculty/{fid}/unavailable")
def set_unavailable(fid: int, req: UnavReq, conn=Depends(db), d=Depends(current_department)):
    f = own_faculty(conn, d, fid)
    sl = slots(conn)
    by = {(v[0], v[1]): k for k, v in sl.items()}
    want = {tuple(x) for x in req.slots}
    if not want <= set(by):
        raise HTTPException(400, "One of those periods isn't a teaching period.")
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(1)")        # same lock as scheduling, so nothing slips in between
        for v in view(conn, "faculty_id", fid):
            if (v["day"], v["period"]) in want:
                s_ = next(x for x in sl.values() if x[0] == v["day"] and x[1] == v["period"])
                raise HTTPException(409, f"{f['name']} is already teaching {v['department']} · {v['subject']} on {when(s_)}. Move that session first.")
        conn.execute("DELETE FROM faculty_availability WHERE faculty_id=%s AND kind='unavailable'", (fid,))
        for k in want:
            conn.execute("INSERT INTO faculty_availability (faculty_id, time_slot_id, kind) VALUES (%s,%s,'unavailable')", (fid, by[k]))
        note(conn, d["id"], "faculty_availability", new={"teacher": f["name"], "unavailable": len(want)})
    return dict(ok=True)


@app.delete("/api/faculty/{fid}")
def remove_faculty(fid: int, conn=Depends(db), d=Depends(current_department)):
    f = own_faculty(conn, d, fid)
    n = conn.execute("SELECT count(*) n FROM teacher_allocation WHERE faculty_id=%s", (fid,)).fetchone()["n"]
    if n:
        raise HTTPException(409, f"{f['name']} is still assigned to {n} subject(s). Choose another teacher for those first.")
    conn.execute("UPDATE faculty SET active=FALSE WHERE id=%s", (fid,))
    note(conn, d["id"], "faculty_remove", old={"name": f["name"]})
    return dict(ok=True)


@app.get("/api/rooms")
def rooms(conn=Depends(db), d=Depends(current_department)):
    return conn.execute("SELECT id, name, room_type, capacity FROM room ORDER BY id").fetchall()


@app.get("/api/faculty/{fid}/timetable")
def teacher_timetable(fid: int, conn=Depends(db), d=Depends(current_department)):
    return view(conn, "faculty_id", fid)


@app.get("/api/rooms/{rid}/timetable")
def room_timetable(rid: int, conn=Depends(db), d=Depends(current_department)):
    return view(conn, "room_id", rid)


def availability(conn, col, rid):
    """Each period is Available, Busy (with who is using it) or Unavailable (with why)."""
    sl = slots(conn)
    busy = {(b["day"], b["period"]): b for b in view(conn, col, rid)}
    off = set()
    if col == "faculty_id":
        off = {(sl[r["time_slot_id"]][0], sl[r["time_slot_id"]][1]) for r in conn.execute("SELECT time_slot_id FROM faculty_availability WHERE faculty_id=%s", (rid,))}
    else:
        off = {(sl[r["time_slot_id"]][0], sl[r["time_slot_id"]][1]) for r in conn.execute("SELECT time_slot_id FROM room_availability WHERE room_id=%s", (rid,))} if False else set()
    out = []
    for (day, per, a, b) in sorted(sl.values()):
        k = (day, per)
        if k in busy:
            x = busy[k]
            out.append(dict(day=day, period=per, state="busy", reason=f"Currently scheduled in {x['department']} — {x['class_name']}, {x['subject']}."))
        elif k in off:
            out.append(dict(day=day, period=per, state="unavailable", reason="Marked as not available at this time."))
        else:
            out.append(dict(day=day, period=per, state="available", reason=""))
    return out


@app.get("/api/faculty/{fid}/availability")
def faculty_availability(fid: int, conn=Depends(db), d=Depends(current_department)):
    return availability(conn, "faculty_id", fid)


@app.get("/api/rooms/{rid}/availability")
def room_availability(rid: int, conn=Depends(db), d=Depends(current_department)):
    return availability(conn, "room_id", rid)


# ---------- department data ----------
class AllocReq(BaseModel):
    class_id: int
    subject: str
    faculty_id: int
    sessions: int
    lab: str | None = None   # 'Computer lab' | 'Laboratory' | None


@app.post("/api/allocations")
def add_allocation(req: AllocReq, conn=Depends(db), d=Depends(current_department)):
    own_class(conn, d, req.class_id)
    if not 1 <= req.sessions <= 30:
        raise HTTPException(400, "Weekly sessions should be between 1 and 30.")
    rt = req.lab or "Classroom"
    sid = conn.execute("INSERT INTO subject (name, department_id, kind, required_room_type) VALUES (%s,%s,%s,%s) RETURNING id",
                       (req.subject.strip(), d["id"], "Lab" if req.lab else "Lecture", rt)).fetchone()["id"]
    try:
        conn.execute("INSERT INTO teacher_allocation (class_id, subject_id, faculty_id, sessions_per_week) VALUES (%s,%s,%s,%s)",
                     (req.class_id, sid, req.faculty_id, req.sessions))
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(400, "Please choose a faculty member from the list.")
    note(conn, d["id"], "add_subject", new=req.model_dump())
    return dict(ok=True)


@app.get("/api/allocations")
def allocations(conn=Depends(db), d=Depends(current_department)):
    return conn.execute("""SELECT a.id, c.name class_name, s.name subject, f.name teacher, f.faculty_code, a.sessions_per_week,
        (SELECT count(*) FROM timetable_entry e WHERE e.allocation_id=a.id) placed FROM teacher_allocation a
        JOIN class c ON c.id=a.class_id JOIN subject s ON s.id=a.subject_id JOIN faculty f ON f.id=a.faculty_id
        WHERE c.department_id=%s ORDER BY c.id, a.id""", (d["id"],)).fetchall()


# ---------- status ----------
NEXT = {"draft": ["under_review"], "under_review": ["approved", "draft"], "approved": ["published", "draft"],
        "published": ["frozen"], "frozen": ["published"]}


class StatusReq(BaseModel):
    status: str


@app.put("/api/status")
def set_status(req: StatusReq, conn=Depends(db), d=Depends(current_department)):
    cur = {r["status"] for r in conn.execute("SELECT status FROM timetable WHERE department_id=%s", (d["id"],))}
    if len(cur) != 1 or req.status not in NEXT[next(iter(cur))]:
        raise HTTPException(400, "That status change isn't available from the current state.")
    conn.execute("UPDATE timetable SET status=%s, updated_at=now() WHERE department_id=%s", (req.status, d["id"]))
    note(conn, d["id"], "status", old={"status": next(iter(cur))}, new={"status": req.status})
    return dict(status=req.status)


# ---------- editing one session ----------
class MoveReq(BaseModel):
    day: int
    period: int
    reason: str | None = None


def check(conn, d, entry_id, day, period):
    e = conn.execute("SELECT e.*, c.department_id, t.status FROM timetable_entry e JOIN class c ON c.id=e.class_id JOIN timetable t ON t.class_id=c.id WHERE e.id=%s", (entry_id,)).fetchone()
    if not e:
        raise HTTPException(404, "We couldn't find that session.")
    if e["department_id"] != d["id"]:
        raise HTTPException(403, "This session belongs to another department's timetable.")
    sl = slots(conn)
    target = next((k for k, v in sl.items() if v[0] == day and v[1] == period), None)
    if target is None:
        return e, None, False, "That isn't a teaching period.", None
    teachers, rooms_ = shared(conn, sl)
    data = dict(teachers=teachers, rooms=rooms_, busy=placed(conn, sl, exclude_entry=entry_id))
    ok, why = validate_move(data, {"class": e["class_id"], "teacher": e["faculty_id"], "room": e["room_id"]}, day, period)
    room = e["room_id"]
    if ok:
        taken = {b["room"] for b in data["busy"] if b["day"] == day and b["period"] == period}
        if room in taken:
            kind = next(r["type"] for r in rooms_ if r["id"] == room)
            room = next(r["id"] for r in rooms_ if r["type"] == kind and r["id"] not in taken)
    return e, (target, room), ok, why, sl


def apply_move(conn, d, entry_id, day, period, reason, action):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(1)")
        e, tgt, ok, why, sl = check(conn, d, entry_id, day, period)   # re-checked inside the lock
        if not ok:
            raise HTTPException(409, f"This change can't be made. {why}")
        old = sl[e["time_slot_id"]]
        try:
            conn.execute("UPDATE timetable_entry SET time_slot_id=%s, room_id=%s WHERE id=%s", (tgt[0], tgt[1], entry_id))
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "This change can't be made. Someone just used that time. Please choose another period.")
        note(conn, d["id"], action, entry_id, {"when": when(old)}, {"when": when(sl[tgt[0]])}, reason)
    return dict(ok=True, message="Change made.")


@app.post("/api/entries/{entry_id}/check")
def check_move(entry_id: int, req: MoveReq, conn=Depends(db), d=Depends(current_department)):
    _, _, ok, why, _ = check(conn, d, entry_id, req.day, req.period)
    return dict(allowed=ok, message=why if not ok else "This change is allowed.")


@app.post("/api/entries/{entry_id}/move")
def move(entry_id: int, req: MoveReq, conn=Depends(db), d=Depends(current_department)):
    e = check(conn, d, entry_id, req.day, req.period)[0]
    if e["status"] in ("published", "frozen"):
        raise HTTPException(409, "This timetable is published. Please use Request change and give a short reason.")
    return apply_move(conn, d, entry_id, req.day, req.period, req.reason, "move")


@app.post("/api/entries/{entry_id}/request-change")
def request_change(entry_id: int, req: MoveReq, conn=Depends(db), d=Depends(current_department)):
    if not (req.reason or "").strip():
        raise HTTPException(400, "Please add a short reason for the change.")
    res = apply_move(conn, d, entry_id, req.day, req.period, req.reason, "change_request")
    conn.execute("INSERT INTO change_request (timetable_id, requested_by, reason, entry_id, new_day, new_period) SELECT t.id,%s,%s,%s,%s,%s FROM timetable t JOIN timetable_entry e ON e.class_id=t.class_id WHERE e.id=%s",
                 (d["account_id"], req.reason, entry_id, req.day, req.period, entry_id))
    return res


@app.get("/api/audit")
def audit_history(conn=Depends(db), d=Depends(current_department)):
    return conn.execute("SELECT at, action, entry_id, old_value, new_value, reason FROM audit_log WHERE department_id=%s ORDER BY id DESC LIMIT 100", (d["id"],)).fetchall()


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.get("/registry", include_in_schema=False)
def registry_page():
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "registry.html"))


@app.get("/signup", include_in_schema=False)
def signup_page():
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "signup.html"))


@app.get("/login", include_in_schema=False)
def login_page():
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "login.html"))


# Serve the interface from the same address, so cookies and the API share one origin. Keep this LAST.
_ui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend")
if os.path.isdir(_ui):
    app.mount("/", StaticFiles(directory=_ui, html=True), name="ui")
