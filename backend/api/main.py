"""Tessellate API. Run from the backend folder:  uvicorn api.main:app

Every route learns the department from the signed-in session (api/auth.py). There are no roles and no
department priority: all departments use the same rules and the same shared resources.
"""
import logging
import re
from collections import defaultdict
import psycopg
from psycopg.types.json import Jsonb
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import os
from pydantic import BaseModel

from engine.solver import RULE_DEFS, generate, issues, rebalance, validate_move, ov
from .auth import current_department, router as auth_router
from .registry import router as registry_router
from .db import db
from .config import USE_ROOMS

# Refuse to start in production with unsafe settings (so a mistake shows up at deploy time, not as a breach later).
if os.environ.get("TESSELLATE_ENV") == "production":
    _bad = []
    if len(os.environ.get("TESSELLATE_SECRET", "")) < 32:
        _bad.append("TESSELLATE_SECRET must be a random value of at least 32 characters")
    if os.environ.get("COOKIE_SECURE") != "1":
        _bad.append("COOKIE_SECURE must be 1 (HTTPS only)")
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


def hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def tomin(v):
    return int(v[:2]) * 60 + int(v[3:5])


tmin = lambda t: t.hour * 60 + t.minute   # noqa: E731


def when(day, start, end):
    return f"{DAYS[day]} \u00b7 {hm(start)}\u2013{hm(end)}"


def base_slots(conn):
    """The college's reference grid. Teachers' unavailable periods are defined on it; departments may use their own times."""
    return [dict(id=r["id"], day=r["day"], period=r["period"], start=tmin(r["starts"]), end=tmin(r["ends"]))
            for r in conn.execute("SELECT * FROM time_slot ORDER BY day, period")]


def default_settings(conn):
    bs = base_slots(conn)
    per = {}
    for b in bs:
        per.setdefault(b["period"], (b["start"], b["end"]))
    return dict(days=sorted({b["day"] for b in bs}) or [0, 1, 2, 3, 4],
                periods=[dict(start=hm(per[p][0]), end=hm(per[p][1])) for p in sorted(per)], rules={}, free=[])


def load_settings(conn, dept_id):
    row = conn.execute("SELECT config FROM department_settings WHERE department_id=%s", (dept_id,)).fetchone()
    cfg = default_settings(conn)
    if row:
        cfg.update(row["config"])
    cfg["saved"] = bool(row)
    return cfg


def solver_cfg(cfg):
    return dict(days=cfg["days"], periods=[dict(start=tomin(p["start"]), end=tomin(p["end"])) for p in cfg["periods"]],
                rules=cfg.get("rules", {}), free=cfg.get("free", []))


def own_class(conn, d, class_id):
    c = conn.execute("SELECT * FROM class WHERE id=%s", (class_id,)).fetchone()
    if not c:
        raise HTTPException(404, "We couldn't find that class.")
    if c["department_id"] != d["id"]:
        raise HTTPException(403, "This class belongs to another department. You can view shared resources but not change their timetable.")
    return c


def shared(conn):
    """Teachers and rooms are college-wide records. Same data for every department."""
    teachers = {}
    for f in conn.execute("SELECT * FROM faculty WHERE active"):
        un = conn.execute("""SELECT ts.day, ts.starts, ts.ends FROM faculty_availability fa JOIN time_slot ts ON ts.id=fa.time_slot_id
                             WHERE fa.faculty_id=%s AND fa.kind='unavailable'""", (f["id"],)).fetchall()
        teachers[f["id"]] = dict(name=f["name"], max_load=f["max_weekly_sessions"],
                                 unavailable=[[u["day"], tmin(u["starts"]), tmin(u["ends"])] for u in un])
    return teachers, [dict(id=r["id"], type=r["room_type"]) for r in conn.execute("SELECT * FROM room")]


def placed(conn, exclude_entry=None, exclude_class=None, exclude_offering=None):
    """Sessions already saved, as 'busy' records (real day and time range) with student_ids and reason."""
    class_stu = defaultdict(set)
    for r in conn.execute("SELECT id, class_id FROM student WHERE class_id IS NOT NULL AND status='active'"):
        class_stu[r["class_id"]].add(r["id"])

    offering_stu = defaultdict(set)
    for r in conn.execute("SELECT student_id, course_offering_id FROM course_enrollment WHERE enrollment_status='enrolled'"):
        offering_stu[r["course_offering_id"]].add(r["student_id"])

    out = []
    # Regular class sessions
    q1 = """SELECT x.*, d.name department, s.name subject, c.name class_name FROM timetable_entry x
           JOIN class c ON c.id=x.class_id JOIN department d ON d.id=c.department_id
           JOIN teacher_allocation a ON a.id=x.allocation_id JOIN subject s ON s.id=a.subject_id"""
    for o in conn.execute(q1):
        if o["id"] == exclude_entry or (exclude_class and o["class_id"] == exclude_class):
            continue
        out.append(dict(teacher=o["faculty_id"], room=o["room_id"], day=o["day"], period=o["period"],
                        start=o["start_min"], end=o["end_min"], subject=o["subject"], department=o["department"],
                        class_name=o["class_name"], student_ids=class_stu.get(o["class_id"], set()),
                        **{"class": o["class_id"]}))

    # Course offering sessions
    q2 = """SELECT x.*, d.name department, crs.course_name subject, co.offering_code class_name,
                   co.scheduling_scope, crs.course_type
            FROM timetable_entry x
            JOIN course_offering co ON co.id=x.course_offering_id
            JOIN course crs ON crs.id=co.course_id
            JOIN department d ON d.id=co.offering_department_id"""
    for o in conn.execute(q2):
        if o["id"] == exclude_entry or (exclude_offering and o["course_offering_id"] == exclude_offering):
            continue
        out.append(dict(teacher=o["faculty_id"], room=o["room_id"], day=o["day"], period=o["period"],
                        start=o["start_min"], end=o["end_min"], subject=o["subject"], department=o["department"],
                        class_name=o["class_name"], scope=o["scheduling_scope"], course_type=o["course_type"],
                        offering_id=o["course_offering_id"], section_id=o["section_id"],
                        student_ids=offering_stu.get(o["course_offering_id"], set()),
                        **{"class": None}))
    return out


def build_input(conn, d, class_id=None, joint=False):
    teachers, rooms = shared(conn)
    where, args = ("", ()) if joint else ("WHERE c.department_id=%s" + (" AND c.id=%s" if class_id else ""), (d["id"],) + ((class_id,) if class_id else ()))
    classes = {c["id"]: dict(name=c["name"], department=c["code"]) for c in conn.execute(
        "SELECT c.id, c.name, dp.code FROM class c JOIN department dp ON dp.id=c.department_id " + where, args)}
    allocs = [dict(**{"class": a["class_id"]}, subject=a["subject"], teacher=a["faculty_id"], sessions=a["sessions_per_week"],
                   room_type=a["required_room_type"], id=a["id"], department=a["code"], kind="regular")
              for a in conn.execute("""SELECT a.*, s.name subject, s.required_room_type, dp.code FROM teacher_allocation a
                  JOIN subject s ON s.id=a.subject_id JOIN class c ON c.id=a.class_id JOIN department dp ON dp.id=c.department_id """ + where, args)]

    offering_ids = set()
    if not class_id:
        off_where, off_args = ("", ()) if joint else ("WHERE co.offering_department_id=%s AND co.status='active'", (d["id"],))
        off_rows = conn.execute(f"""SELECT co.*, crs.course_name, crs.course_code, crs.course_type, crs.selection_type course_sel_type, dp.code dept_code
            FROM course_offering co JOIN course crs ON crs.id=co.course_id
            JOIN department dp ON dp.id=co.offering_department_id {off_where}""", off_args).fetchall()
        for co in off_rows:
            offering_ids.add(co["id"])
            sel_type = co.get("selection_type") or co.get("course_sel_type")
            if not sel_type:
                sel_type = "STUDENT_SELECTED" if co.get("scheduling_scope") == "college_wide" else "DEPARTMENT_SELECTED"
            scope = "college_wide" if sel_type == "STUDENT_SELECTED" else "department_specific"

            enrolled = [r["student_id"] for r in conn.execute(
                "SELECT student_id FROM course_enrollment WHERE course_offering_id=%s AND enrollment_status='enrolled'", (co["id"],))]
            sections = conn.execute("SELECT * FROM course_section WHERE course_offering_id=%s ORDER BY section_name", (co["id"],)).fetchall()
            if sections:
                for sec in sections:
                    sec_enrolled = [r["student_id"] for r in conn.execute(
                        "SELECT student_id FROM course_enrollment WHERE course_offering_id=%s AND section_id=%s AND enrollment_status='enrolled'", (co["id"], sec["id"]))]
                    allocs.append(dict(
                        offering_id=co["id"],
                        section_id=sec["id"],
                        code=f"{co['offering_code']} ({sec['section_name']})",
                        subject=co["course_name"],
                        course_type=co["course_type"],
                        selection_type=sel_type,
                        scope=scope,
                        teacher=sec["faculty_id"] or co["faculty_id"],
                        sessions=co["required_sessions"],
                        room_type=co["required_room_type"],
                        room=sec["room_id"] or co["room_id"],
                        department=co["dept_code"],
                        enrolled_students=sec_enrolled or enrolled,
                        kind="offering",
                        capacity=sec["capacity"],
                        id=f"off-{co['id']}-{sec['id']}",
                        **{"class": None}
                    ))
            else:
                allocs.append(dict(
                    offering_id=co["id"],
                    section_id=None,
                    code=co["offering_code"],
                    subject=co["course_name"],
                    course_type=co["course_type"],
                    selection_type=sel_type,
                    scope=scope,
                    teacher=co["faculty_id"],
                    sessions=co["required_sessions"],
                    room_type=co["required_room_type"],
                    room=co["room_id"],
                    department=co["dept_code"],
                    enrolled_students=enrolled,
                    kind="offering",
                    capacity=co["max_enrollment"],
                    id=f"off-{co['id']}",
                    **{"class": None}
                ))

    common_slots = [dict(id=r["id"], day=r["day"], start=r["start_min"], end=r["end_min"],
                         course_type=r["applicable_course_type"], name=r["name"])
                    for r in conn.execute("SELECT * FROM common_time_slot WHERE status='active'")]

    students = {r["id"]: dict(name=r["name"], reg=r["register_number"], home_dept=r["home_department_id"], class_id=r["class_id"])
                for r in conn.execute("SELECT * FROM student WHERE status='active'")}
    class_students = defaultdict(set)
    for sid, s in students.items():
        if s["class_id"]:
            class_students[s["class_id"]].add(sid)

    cw_rows = conn.execute("""
        SELECT ce.student_id, crs.course_type
        FROM course_enrollment ce
        JOIN course_offering co ON co.id=ce.course_offering_id
        JOIN course crs ON crs.id=co.course_id
        WHERE (co.scheduling_scope='college_wide' OR co.selection_type='STUDENT_SELECTED') AND ce.enrollment_status='enrolled'
    """).fetchall()
    cw_students_by_type = defaultdict(set)
    for r in cw_rows:
        cw_students_by_type[r["course_type"]].add(r["student_id"])

    settings = {dp["code"]: solver_cfg(load_settings(conn, dp["id"]))
                for dp in conn.execute("SELECT id, code FROM department") if joint or dp["id"] == d["id"]}
    ids = set(classes)
    busy = [] if joint else [b for b in placed(conn) if (b.get("class") not in ids and b.get("offering_id") not in offering_ids)]
    for t, T in teachers.items():
        T["existing_load"] = sum(1 for b in busy if b.get("teacher") == t)

    data = dict(settings=settings, teachers=teachers, classes=classes, rooms=rooms, allocations=allocs, busy=busy,
                use_rooms=USE_ROOMS, common_slots=common_slots, students=students, class_students=dict(class_students),
                cw_students_by_type=dict(cw_students_by_type), offering_ids=offering_ids)
    if joint:
        idx = {a["id"]: i for i, a in enumerate(allocs)}
        data["current"] = [dict(allocation=idx[o["allocation_id"]], day=o["day"], start=o["start_min"], room=o["room_id"])
                           for o in conn.execute("SELECT * FROM timetable_entry WHERE allocation_id IS NOT NULL") if o["allocation_id"] in idx]
    return data


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
        data = build_input(conn, d, req.class_id)
        if not data["allocations"]:
            raise HTTPException(400, "Add classes/subjects or course offerings first, then generate.")
        res = generate(data, 20)
        conn.execute("""INSERT INTO generation_run (department_id, scope, status, quality, problems, started_by)
                        VALUES (%s,%s,%s,%s,%s,%s)""", (d["id"], "class" if req.class_id else "department", res["status"], res.get("score"),
                                                        Jsonb(res["problems"]), d["account_id"]))
        if res["status"] != "ok":
            return dict(status="impossible", message="We couldn't create a valid timetable with the current settings.",
                        issues=res["issues"], problems=res["problems"], suggestions=res["suggestions"],
                        can_look_for_alternative=any(i.get("alt") for i in res["issues"]))
        conn.execute("DELETE FROM timetable_entry WHERE class_id = ANY(%s)", (list(data["classes"]),))
        if data.get("offering_ids"):
            conn.execute("DELETE FROM timetable_entry WHERE course_offering_id = ANY(%s)", (list(data["offering_ids"]),))
        try:
            for e in res["entries"]:
                if e.get("kind") == "offering":
                    conn.execute("""INSERT INTO timetable_entry (course_offering_id, section_id, faculty_id, room_id, day, period, start_min, end_min)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (e["offering_id"], e["section_id"], e["teacher"], e["room"], e["day"], e["period"], e["start"], e["end"]))
                else:
                    conn.execute("""INSERT INTO timetable_entry (timetable_id, allocation_id, class_id, faculty_id, room_id, day, period, start_min, end_min)
                        SELECT t.id, %s, %s, %s, %s, %s, %s, %s, %s FROM timetable t WHERE t.class_id=%s""",
                        (data["allocations"][e["allocation"]]["id"], e["class"], e["teacher"], e["room"], e["day"], e["period"], e["start"], e["end"], e["class"]))
        except psycopg.errors.ExclusionViolation:
            raise HTTPException(409, "Another department just booked one of these teachers or rooms. Please generate again.")
        note(conn, d["id"], "generate", new={"quality": res["score"], "sessions": len(res["entries"])})
    return dict(status="ok", quality=res["score"], sessions=len(res["entries"]), rules_used=res.get("rules_used", 0))


@app.post("/api/alternatives")
def look_for_alternative(conn=Depends(db), d=Depends(current_department)):
    """Equal priority: solves ALL departments together and reports what would change. Applies nothing."""
    data = build_input(conn, d, joint=True)
    res = rebalance(data, 20)
    if res["status"] != "ok":
        return dict(status="impossible", message="Even with every department's timetable rearranged, the current settings don't fit.",
                    issues=res["issues"], problems=res["problems"], suggestions=res["suggestions"])
    names = {c["code"]: c["name"] for c in conn.execute("SELECT code, name FROM department")}
    return dict(status="proposal", quality=res["score"],
                affected_departments=[dict(department=names.get(k, k), sessions_changed=v) for k, v in res["moved_by_department"].items()],
                message="A better college-wide arrangement exists. Nothing has been changed. Each affected department keeps its own timetable until it chooses to regenerate.")


# ---------- read: workspace + shared resources ----------
@app.get("/api/conflicts")
def conflicts(conn=Depends(db), d=Depends(current_department)):
    """What is actually wrong, including student-level conflicts. Each item: one issue and one short fix."""
    data = build_input(conn, d)
    items = issues(data) if data["allocations"] else []
    generated = (conn.execute("SELECT count(*) n FROM timetable_entry e JOIN class c ON c.id=e.class_id WHERE c.department_id=%s", (d["id"],)).fetchone()["n"] > 0 or
                 conn.execute("SELECT count(*) n FROM timetable_entry e JOIN course_offering co ON co.id=e.course_offering_id WHERE co.offering_department_id=%s", (d["id"],)).fetchone()["n"] > 0)
    if not items and generated:
        miss = conn.execute("""SELECT count(*) n FROM teacher_allocation a JOIN class c ON c.id=a.class_id WHERE c.department_id=%s
            AND a.sessions_per_week > (SELECT count(*) FROM timetable_entry e WHERE e.allocation_id=a.id)""", (d["id"],)).fetchone()["n"]
        if miss:
            items.append(dict(issue=f"{miss} subject(s) don't have all their weekly sessions yet.",
                              fix="Click Generate timetable again. If it still fails, change a Required rule to Prefer in Rules."))

    # Student-level timetable conflict detection
    stu_conflicts = conn.execute("""
        SELECT s.name student_name, s.register_number,
               e1.day, e1.start_min, e1.end_min,
               coalesce(s1.name, crs1.course_name) sub1, coalesce(d1.name, od1.name) dept1,
               coalesce(s2.name, crs2.course_name) sub2, coalesce(d2.name, od2.name) dept2
        FROM student s
        JOIN (
            SELECT e.id entry_id, s_sub.id student_id, e.day, e.start_min, e.end_min, e.allocation_id, e.course_offering_id, e.class_id
            FROM timetable_entry e
            JOIN student s_sub ON s_sub.class_id=e.class_id
            UNION ALL
            SELECT e.id entry_id, ce.student_id, e.day, e.start_min, e.end_min, e.allocation_id, e.course_offering_id, e.class_id
            FROM timetable_entry e
            JOIN course_enrollment ce ON ce.course_offering_id=e.course_offering_id AND ce.enrollment_status='enrolled'
        ) sess1 ON sess1.student_id=s.id
        JOIN (
            SELECT e.id entry_id, s_sub.id student_id, e.day, e.start_min, e.end_min, e.allocation_id, e.course_offering_id, e.class_id
            FROM timetable_entry e
            JOIN student s_sub ON s_sub.class_id=e.class_id
            UNION ALL
            SELECT e.id entry_id, ce.student_id, e.day, e.start_min, e.end_min, e.allocation_id, e.course_offering_id, e.class_id
            FROM timetable_entry e
            JOIN course_enrollment ce ON ce.course_offering_id=e.course_offering_id AND ce.enrollment_status='enrolled'
        ) sess2 ON sess2.student_id=s.id AND sess2.entry_id < sess1.entry_id
        JOIN timetable_entry e1 ON e1.id=sess1.entry_id
        JOIN timetable_entry e2 ON e2.id=sess2.entry_id
        LEFT JOIN teacher_allocation a1 ON a1.id=e1.allocation_id LEFT JOIN subject s1 ON s1.id=a1.subject_id
        LEFT JOIN class c1 ON c1.id=e1.class_id LEFT JOIN department d1 ON d1.id=c1.department_id
        LEFT JOIN course_offering co1 ON co1.id=e1.course_offering_id LEFT JOIN course crs1 ON crs1.id=co1.course_id LEFT JOIN department od1 ON od1.id=co1.offering_department_id
        LEFT JOIN teacher_allocation a2 ON a2.id=e2.allocation_id LEFT JOIN subject s2 ON s2.id=a2.subject_id
        LEFT JOIN class c2 ON c2.id=e2.class_id LEFT JOIN department d2 ON d2.id=c2.department_id
        LEFT JOIN course_offering co2 ON co2.id=e2.course_offering_id LEFT JOIN course crs2 ON crs2.id=co2.course_id LEFT JOIN department od2 ON od2.id=co2.offering_department_id
        WHERE e1.day = e2.day AND e1.start_min < e2.end_min AND e2.start_min < e1.end_min
          AND (s.home_department_id=%s OR d1.id=%s OR od1.id=%s OR d2.id=%s OR od2.id=%s)
    """, (d["id"], d["id"], d["id"], d["id"], d["id"])).fetchall()

    for sc in stu_conflicts:
        items.append(dict(
            issue=f"Student {sc['student_name']} ({sc['register_number']}) has a conflict between {sc['sub1']} ({sc['dept1']}) and {sc['sub2']} ({sc['dept2']}) on {DAYS[sc['day']]} {hm(sc['start_min'])}\u2013{hm(sc['end_min'])}.",
            fix="Move one of these sessions to another period or common slot."
        ))

    return dict(items=items, generated=generated)


@app.get("/api/dashboard")
def dashboard(conn=Depends(db), d=Depends(current_department)):
    n = lambda q, *a: conn.execute(q, a).fetchone()["n"]
    st = conn.execute("SELECT status FROM timetable WHERE department_id=%s GROUP BY status", (d["id"],)).fetchall()
    return dict(department=dict(code=d["code"], name=d["name"], category=d.get("category", "Aided")),
                classes=n("SELECT count(*) n FROM class WHERE department_id=%s", d["id"]),
                students=n("SELECT count(*) n FROM student WHERE home_department_id=%s", d["id"]),
                courses=n("SELECT count(*) n FROM course WHERE department_id=%s", d["id"]),
                offerings=n("SELECT count(*) n FROM course_offering WHERE offering_department_id=%s", d["id"]),
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
    rows = conn.execute("""SELECT e.id, e.day, e.period, e.start_min, e.end_min, s.name subject,
        f.name teacher, f.id faculty_id, r.name room, r.id room_id, s.kind, 'regular' as entry_type,
        e.class_id, e.course_offering_id FROM timetable_entry e
        JOIN teacher_allocation a ON a.id=e.allocation_id JOIN subject s ON s.id=a.subject_id
        LEFT JOIN faculty f ON f.id=e.faculty_id LEFT JOIN room r ON r.id=e.room_id
        WHERE e.class_id=%s ORDER BY e.day, e.start_min""", (class_id,)).fetchall()

    off_rows = conn.execute("""
        SELECT DISTINCT e.id, e.day, e.period, e.start_min, e.end_min, crs.course_name subject,
               f.name teacher, f.id faculty_id, r.name room, r.id room_id, 'Lecture' as kind,
               crs.course_type as entry_type, e.class_id, e.course_offering_id
        FROM timetable_entry e
        JOIN course_offering co ON co.id=e.course_offering_id
        JOIN course crs ON crs.id=co.course_id
        JOIN course_enrollment ce ON ce.course_offering_id=co.id
        JOIN student s ON s.id=ce.student_id
        LEFT JOIN faculty f ON f.id=e.faculty_id
        LEFT JOIN room r ON r.id=e.room_id
        WHERE s.class_id=%s AND ce.enrollment_status='enrolled'
        ORDER BY e.day, e.start_min
    """, (class_id,)).fetchall()

    seen = set()
    out = []
    for r in list(rows) + list(off_rows):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(dict(
            id=r["id"], day=r["day"], period=r["period"],
            start=hm(r["start_min"]), end=hm(r["end_min"]),
            subject=r["subject"], teacher=r["teacher"] or "Unassigned", faculty_id=r["faculty_id"],
            room=r["room"], room_id=r["room_id"],
            lab=r["kind"] == "Lab", entry_type=r["entry_type"],
            course_offering_id=r["course_offering_id"], class_id=r["class_id"]
        ))
    return out


def view(conn, col, rid):
    q = f"""SELECT e.day, e.period, e.start_min, e.end_min,
        coalesce(s.name, crs.course_name) subject,
        f.name teacher, r.name room,
        coalesce(c.name, co.offering_code) class_name,
        coalesce(dp.name, od.name) department
        FROM timetable_entry e
        LEFT JOIN teacher_allocation a ON a.id=e.allocation_id
        LEFT JOIN subject s ON s.id=a.subject_id
        LEFT JOIN course_offering co ON co.id=e.course_offering_id
        LEFT JOIN course crs ON crs.id=co.course_id
        LEFT JOIN department od ON od.id=co.offering_department_id
        LEFT JOIN faculty f ON f.id=e.faculty_id
        LEFT JOIN room r ON r.id=e.room_id
        LEFT JOIN class c ON c.id=e.class_id
        LEFT JOIN department dp ON dp.id=c.department_id
        WHERE e.{col}=%s ORDER BY e.day, e.start_min"""
    rows = conn.execute(q, (rid,)).fetchall()
    return [dict(day=r["day"], period=r["period"], start=hm(r["start_min"]), end=hm(r["end_min"]), smin=r["start_min"], emin=r["end_min"],
                 **{k: r[k] for k in ("subject", "teacher", "room", "class_name", "department")}) for r in rows]


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


@app.get("/api/faculty/{fid}/base-availability")
def base_availability(fid: int, conn=Depends(db), d=Depends(current_department)):
    """The college's reference grid, used to edit a teacher's unavailable periods."""
    mine = {r["time_slot_id"] for r in conn.execute("SELECT time_slot_id FROM faculty_availability WHERE faculty_id=%s AND kind='unavailable'", (fid,))}
    ents = view(conn, "faculty_id", fid)
    out = []
    for b in base_slots(conn):
        x = next((e for e in ents if e["day"] == b["day"] and ov(b["start"], b["end"], e["smin"], e["emin"])), None)
        state = "busy" if x else "unavailable" if b["id"] in mine else "available"
        out.append(dict(day=b["day"], period=b["period"], start=hm(b["start"]), end=hm(b["end"]), state=state,
                        reason=f"Currently scheduled in {x['department']} \u2014 {x['class_name']}, {x['subject']}." if x else ""))
    return out


@app.put("/api/faculty/{fid}/unavailable")
def set_unavailable(fid: int, req: UnavReq, conn=Depends(db), d=Depends(current_department)):
    f = own_faculty(conn, d, fid)
    bs = base_slots(conn)
    by = {(b["day"], b["period"]): b for b in bs}
    want = {tuple(x) for x in req.slots}
    if not want <= set(by):
        raise HTTPException(400, "One of those periods isn't a teaching period.")
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(1)")        # same lock as scheduling, so nothing slips in between
        for v in view(conn, "faculty_id", fid):
            for k in want:
                b = by[k]
                if b["day"] == v["day"] and ov(b["start"], b["end"], v["smin"], v["emin"]):
                    raise HTTPException(409, f"{f['name']} is already teaching {v['department']} \u00b7 {v['subject']} on {when(v['day'], v['smin'], v['emin'])}. Move that session first.")
        conn.execute("DELETE FROM faculty_availability WHERE faculty_id=%s AND kind='unavailable'", (fid,))
        for k in want:
            conn.execute("INSERT INTO faculty_availability (faculty_id, time_slot_id, kind) VALUES (%s,%s,'unavailable')", (fid, by[k]["id"]))
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
    if not USE_ROOMS:
        raise HTTPException(404, "Rooms aren't used yet.")
    return conn.execute("SELECT id, name, room_type, capacity FROM room ORDER BY id").fetchall()


@app.get("/api/faculty/{fid}/timetable")
def teacher_timetable(fid: int, conn=Depends(db), d=Depends(current_department)):
    return view(conn, "faculty_id", fid)


@app.get("/api/rooms/{rid}/timetable")
def room_timetable(rid: int, conn=Depends(db), d=Depends(current_department)):
    if not USE_ROOMS:
        raise HTTPException(404, "Rooms aren't used yet.")
    return view(conn, "room_id", rid)


def availability(conn, col, rid, dept_id):
    """Shown on the viewing department's OWN period times: Available, Busy (who is using it) or Unavailable (why)."""
    cfg = load_settings(conn, dept_id)
    ents = view(conn, col, rid)
    off = []
    if col == "faculty_id":
        off = [(r["day"], tmin(r["starts"]), tmin(r["ends"])) for r in conn.execute(
            "SELECT ts.day, ts.starts, ts.ends FROM faculty_availability fa JOIN time_slot ts ON ts.id=fa.time_slot_id WHERE fa.faculty_id=%s AND fa.kind='unavailable'", (rid,))]
    out = []
    for day in cfg["days"]:
        for p, per in enumerate(cfg["periods"]):
            s_, e_ = tomin(per["start"]), tomin(per["end"])
            x = next((v for v in ents if v["day"] == day and ov(s_, e_, v["smin"], v["emin"])), None)
            cell = dict(day=day, period=p, start=per["start"], end=per["end"], state="available", reason="")
            if x:
                cell.update(state="busy", reason=f"Currently scheduled in {x['department']} \u2014 {x['class_name']}, {x['subject']} ({hm(x['smin'])}\u2013{hm(x['emin'])}).")
            elif any(od == day and ov(s_, e_, a, b) for od, a, b in off):
                cell.update(state="unavailable", reason="Marked as not available at this time.")
            out.append(cell)
    return out


@app.get("/api/faculty/{fid}/availability")
def faculty_availability(fid: int, conn=Depends(db), d=Depends(current_department)):
    return availability(conn, "faculty_id", fid, d["id"])


@app.get("/api/rooms/{rid}/availability")
def room_availability(rid: int, conn=Depends(db), d=Depends(current_department)):
    if not USE_ROOMS:
        raise HTTPException(404, "Rooms aren't used yet.")
    return availability(conn, "room_id", rid, d["id"])


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
    lab = req.lab if USE_ROOMS else None      # lab types need rooms; ignored while rooms are off
    rt = lab or "Classroom"
    sid = conn.execute("INSERT INTO subject (name, department_id, kind, required_room_type) VALUES (%s,%s,%s,%s) RETURNING id",
                       (req.subject.strip(), d["id"], "Lab" if lab else "Lecture", rt)).fetchone()["id"]
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


# ---------- timetable settings: each department decides how its timetable looks ----------
class SettingsReq(BaseModel):
    days: list[int]
    periods: list[dict]
    rules: dict = {}
    free: list[list[int]] = []


def clean_settings(req):
    days = sorted(set(req.days))
    if not days or any(not 0 <= x <= 6 for x in days):
        raise HTTPException(400, "Choose at least one working day.")
    if not 1 <= len(req.periods) <= 12:
        raise HTTPException(400, "Use between 1 and 12 periods a day.")
    periods, last = [], -1
    for i, p in enumerate(req.periods, 1):
        try:
            s_, e_ = tomin(str(p["start"])), tomin(str(p["end"]))
        except Exception:
            raise HTTPException(400, f"Period {i}: please enter a start and end time.")
        if not (0 <= s_ < e_ <= 24 * 60):
            raise HTTPException(400, f"Period {i}: the end time must be after the start time.")
        if s_ < last:
            raise HTTPException(400, f"Period {i} starts before the previous period ends. List periods in time order without overlap.")
        periods.append(dict(start=hm(s_), end=hm(e_)))
        last = e_
    rules = {}
    for name, df in RULE_DEFS.items():
        r = req.rules.get(name) or {}
        mode = r.get("mode", "off")
        if mode not in df["modes"]:
            raise HTTPException(400, f"\u201c{df['title']}\u201d can't be set to {mode}.")
        item = {"mode": mode}
        if df["param"]:
            v = r.get(df["param"]["key"], df["param"]["default"])
            if not isinstance(v, int) or not df["param"]["min"] <= v <= df["param"]["max"]:
                raise HTTPException(400, f"{df['param']['label']} should be between {df['param']['min']} and {df['param']['max']}.")
            item[df["param"]["key"]] = v
        rules[name] = item
    free = sorted({(a, b) for a, b in req.free if a in days and 0 <= b < len(periods)})
    return dict(days=days, periods=periods, rules=rules, free=[list(x) for x in free])


def stale(conn, dept_id, cfg):
    """True when saved sessions no longer match the department's current days and period times."""
    grid = {(dd, tomin(p["start"]), tomin(p["end"])) for dd in cfg["days"] for p in cfg["periods"]}
    return any((r["day"], r["start_min"], r["end_min"]) not in grid for r in conn.execute(
        "SELECT e.day, e.start_min, e.end_min FROM timetable_entry e JOIN class c ON c.id=e.class_id WHERE c.department_id=%s", (dept_id,)))


@app.get("/api/settings")
def get_settings(conn=Depends(db), d=Depends(current_department)):
    cfg = load_settings(conn, d["id"])
    return dict(config=cfg, rule_defs=RULE_DEFS, stale=stale(conn, d["id"], cfg))


@app.put("/api/settings")
def save_settings(req: SettingsReq, conn=Depends(db), d=Depends(current_department)):
    cfg = clean_settings(req)
    old = load_settings(conn, d["id"])
    conn.execute("""INSERT INTO department_settings (department_id, config) VALUES (%s,%s)
                    ON CONFLICT (department_id) DO UPDATE SET config=EXCLUDED.config, updated_at=now()""", (d["id"], Jsonb(cfg)))
    note(conn, d["id"], "settings", old={"periods": len(old["periods"]), "days": len(old["days"])}, new={"periods": len(cfg["periods"]), "days": len(cfg["days"])})
    cfg["saved"] = True
    return dict(config=cfg, stale=stale(conn, d["id"], cfg))


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
    q = """SELECT e.*,
        coalesce(c.department_id, co.offering_department_id) AS department_id,
        coalesce(t.status, co.status) AS status,
        coalesce(s.name, crs.course_name) AS subject,
        co.scheduling_scope, crs.course_type
        FROM timetable_entry e
        LEFT JOIN class c ON c.id=e.class_id
        LEFT JOIN timetable t ON t.class_id=c.id
        LEFT JOIN teacher_allocation a ON a.id=e.allocation_id
        LEFT JOIN subject s ON s.id=a.subject_id
        LEFT JOIN course_offering co ON co.id=e.course_offering_id
        LEFT JOIN course crs ON crs.id=co.course_id
        WHERE e.id=%s"""
    e = conn.execute(q, (entry_id,)).fetchone()
    if not e:
        raise HTTPException(404, "We couldn't find that session.")
    if e["department_id"] != d["id"]:
        raise HTTPException(403, "This session belongs to another department's timetable.")
    cfg = load_settings(conn, d["id"])
    if day not in cfg["days"] or not 0 <= period < len(cfg["periods"]):
        return e, None, False, "That isn't one of your teaching periods."
    s_, e_ = tomin(cfg["periods"][period]["start"]), tomin(cfg["periods"][period]["end"])
    teachers, rooms_ = shared(conn)
    common_slots = [dict(id=r["id"], day=r["day"], start=r["start_min"], end=r["end_min"],
                         course_type=r["applicable_course_type"], name=r["name"])
                    for r in conn.execute("SELECT * FROM common_time_slot WHERE status='active'")]
    students = {r["id"]: dict(name=r["name"], reg=r["register_number"], home_dept=r["home_department_id"], class_id=r["class_id"])
                for r in conn.execute("SELECT * FROM student WHERE status='active'")}
    class_students = defaultdict(set)
    for sid, st in students.items():
        if st["class_id"]:
            class_students[st["class_id"]].add(sid)
    enrolled = []
    if e["course_offering_id"]:
        enrolled = [r["student_id"] for r in conn.execute(
            "SELECT student_id FROM course_enrollment WHERE course_offering_id=%s AND enrollment_status='enrolled'", (e["course_offering_id"],))]
    data = dict(teachers=teachers, rooms=rooms_, busy=placed(conn, exclude_entry=entry_id),
                settings={d["code"]: solver_cfg(cfg)}, use_rooms=USE_ROOMS, common_slots=common_slots,
                students=students, class_students=dict(class_students))
    entry = {"class": e["class_id"], "teacher": e["faculty_id"], "room": e["room_id"], "subject": e["subject"],
             "department": d["code"], "scope": e.get("scheduling_scope"), "course_type": e.get("course_type"),
             "enrolled_students": enrolled}
    ok, why = validate_move(data, entry, day, period, s_, e_)
    room = e["room_id"]
    if ok:
        taken = {b["room"] for b in data["busy"] if b["day"] == day and ov(s_, e_, b["start"], b["end"]) and b["room"] is not None}
        if USE_ROOMS and room is not None and room in taken:
            kind = next(r["type"] for r in rooms_ if r["id"] == room)
            room = next(r["id"] for r in rooms_ if r["type"] == kind and r["id"] not in taken)
    return e, (day, period, s_, e_, room), ok, why


def apply_move(conn, d, entry_id, day, period, reason, action):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(1)")
        e, tgt, ok, why = check(conn, d, entry_id, day, period)   # re-checked inside the lock
        if not ok:
            raise HTTPException(409, f"This change can't be made. {why}")
        try:
            conn.execute("UPDATE timetable_entry SET day=%s, period=%s, start_min=%s, end_min=%s, room_id=%s WHERE id=%s",
                         (tgt[0], tgt[1], tgt[2], tgt[3], tgt[4], entry_id))
        except (psycopg.errors.ExclusionViolation, psycopg.errors.UniqueViolation):
            raise HTTPException(409, "This change can't be made. Someone just used that time. Please choose another period.")
        note(conn, d["id"], action, entry_id, {"when": when(e["day"], e["start_min"], e["end_min"])}, {"when": when(tgt[0], tgt[2], tgt[3])}, reason)
    return dict(ok=True, message="Change made.")


@app.post("/api/entries/{entry_id}/check")
def check_move(entry_id: int, req: MoveReq, conn=Depends(db), d=Depends(current_department)):
    _, _, ok, why = check(conn, d, entry_id, req.day, req.period)
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


# ---------- interactive timetable batch operations & quick edit ----------
class BatchMoveItem(BaseModel):
    id: int
    day: int
    period: int
    faculty_id: int | None = None
    room_id: int | None = None
    deleted: bool = False


class BatchValidateReq(BaseModel):
    class_id: int | None = None
    moves: list[BatchMoveItem] = []


class QuickEditReq(BaseModel):
    faculty_id: int | None = None
    room_id: int | None = None
    day: int | None = None
    period: int | None = None


def validate_batch_logic(conn, d, moves: list, class_id: int | None = None):
    cfg = load_settings(conn, d["id"])
    periods = cfg["periods"]
    days = set(cfg["days"])
    free_set = {(f[0], f[1]) for f in cfg.get("free", [])}

    dept_entries = conn.execute("""
        SELECT e.id, e.day, e.period, e.start_min, e.end_min, e.faculty_id, e.room_id, e.class_id, e.course_offering_id,
               coalesce(s.name, crs.course_name) AS subject_name,
               f.name AS teacher_name, r.name AS room_name, c.name AS class_name,
               co.scheduling_scope, crs.course_type, crs.selection_type
        FROM timetable_entry e
        LEFT JOIN class c ON c.id=e.class_id
        LEFT JOIN teacher_allocation a ON a.id=e.allocation_id
        LEFT JOIN subject s ON s.id=a.subject_id
        LEFT JOIN course_offering co ON co.id=e.course_offering_id
        LEFT JOIN course crs ON crs.id=co.course_id
        LEFT JOIN faculty f ON f.id=e.faculty_id
        LEFT JOIN room r ON r.id=e.room_id
        WHERE c.department_id=%s OR co.offering_department_id=%s
    """, (d["id"], d["id"])).fetchall()

    entry_map = {e["id"]: dict(e) for e in dept_entries}
    move_map = {m.id if hasattr(m, 'id') else m['id']: (m.model_dump() if hasattr(m, 'model_dump') else m) for m in moves}

    # Cross check if moved entry belongs to another department
    for eid, m in move_map.items():
        if eid not in entry_map:
            other = conn.execute("SELECT id FROM timetable_entry WHERE id=%s", (eid,)).fetchone()
            if not other:
                return False, [{"issue": f"Session #{eid} not found.", "fix": "Refresh your timetable view.", "cells": [], "entry_ids": [eid]}]
            return False, [{"issue": f"Session #{eid} belongs to another department's course offering.", "fix": "Only the offering department can reschedule shared course offerings.", "cells": [], "entry_ids": [eid]}]

    simulated = []
    for eid, e in entry_map.items():
        if eid in move_map:
            m = move_map[eid]
            if m.get("deleted"):
                continue
            day = m["day"]
            p_idx = m["period"]
            if day not in days or not (0 <= p_idx < len(periods)):
                return False, [{"issue": f"'{e['subject_name']}' is placed in an invalid day or period.", "fix": "Move the session to a valid period slot.", "cells": [{"day": day, "period": p_idx}], "entry_ids": [eid]}]
            smin = tomin(periods[p_idx]["start"])
            emin = tomin(periods[p_idx]["end"])
            fac_id = m.get("faculty_id") if m.get("faculty_id") is not None else e["faculty_id"]
            rm_id = m.get("room_id") if m.get("room_id") is not None else e["room_id"]
            sim_e = dict(e)
            sim_e.update(day=day, period=p_idx, start_min=smin, end_min=emin, faculty_id=fac_id, room_id=rm_id)
            simulated.append(sim_e)
        else:
            simulated.append(dict(e))

    other_busy = conn.execute("""
        SELECT e.id, e.day, e.period, e.start_min, e.end_min, e.faculty_id, e.room_id, e.class_id, e.course_offering_id,
               coalesce(s.name, crs.course_name) AS subject_name,
               f.name AS teacher_name, r.name AS room_name,
               coalesce(c.name, co.offering_code) AS class_name,
               coalesce(dp.name, od.name) AS department_name
        FROM timetable_entry e
        LEFT JOIN class c ON c.id=e.class_id
        LEFT JOIN department dp ON dp.id=c.department_id
        LEFT JOIN teacher_allocation a ON a.id=e.allocation_id
        LEFT JOIN subject s ON s.id=a.subject_id
        LEFT JOIN course_offering co ON co.id=e.course_offering_id
        LEFT JOIN course crs ON crs.id=co.course_id
        LEFT JOIN department od ON od.id=co.offering_department_id
        LEFT JOIN faculty f ON f.id=e.faculty_id
        LEFT JOIN room r ON r.id=e.room_id
        WHERE (c.department_id IS NULL OR c.department_id <> %s)
          AND (co.offering_department_id IS NULL OR co.offering_department_id <> %s)
    """, (d["id"], d["id"])).fetchall()

    fac_meta = {}
    for f in conn.execute("SELECT id, name, max_weekly_sessions FROM faculty WHERE active"):
        unav = conn.execute("""
            SELECT ts.day, ts.starts, ts.ends
            FROM faculty_availability fa
            JOIN time_slot ts ON ts.id=fa.time_slot_id
            WHERE fa.faculty_id=%s AND fa.kind='unavailable'
        """, (f["id"],)).fetchall()
        fac_meta[f["id"]] = {
            "name": f["name"],
            "max": f["max_weekly_sessions"],
            "unav": [(u["day"], tmin(u["starts"]), tmin(u["ends"])) for u in unav]
        }

    class_stu = defaultdict(set)
    for st in conn.execute("SELECT id, class_id FROM student WHERE class_id IS NOT NULL AND status='active'"):
        class_stu[st["class_id"]].add(st["id"])

    off_stu = defaultdict(set)
    for ce in conn.execute("SELECT student_id, course_offering_id FROM course_enrollment WHERE enrollment_status='enrolled'"):
        off_stu[ce["course_offering_id"]].add(ce["student_id"])

    cslots = conn.execute("SELECT * FROM common_time_slot WHERE status='active'").fetchall()
    conflicts = []

    for i, e1 in enumerate(simulated):
        if (e1["day"], e1["period"]) in free_set:
            conflicts.append({
                "issue": f"'{e1['subject_name']}' is placed in a kept-free period ({DAYS[e1['day']]} Period {e1['period'] + 1}).",
                "fix": "Move this session to an active teaching period or update Rules.",
                "cells": [{"day": e1["day"], "period": e1["period"]}],
                "entry_ids": [e1["id"]]
            })

        if e1["faculty_id"] and e1["faculty_id"] in fac_meta:
            finfo = fac_meta[e1["faculty_id"]]
            for uday, ustart, uend in finfo["unav"]:
                if e1["day"] == uday and ov(e1["start_min"], e1["end_min"], ustart, uend):
                    conflicts.append({
                        "issue": f"{finfo['name']} is marked unavailable on {when(uday, ustart, uend)}.",
                        "fix": "Move this session to an available period or assign a different faculty member.",
                        "cells": [{"day": e1["day"], "period": e1["period"]}],
                        "entry_ids": [e1["id"]]
                    })

        is_student_selected = (e1.get("selection_type") == "STUDENT_SELECTED" or e1.get("scheduling_scope") == "college_wide")
        if is_student_selected:
            ctype = e1.get("course_type", "MDC")
            matches_slot = any(
                cs["day"] == e1["day"] and cs["start_min"] == e1["start_min"] and cs["end_min"] == e1["end_min"]
                and (cs["applicable_course_type"] in (ctype, "Both") or not cs["applicable_course_type"])
                for cs in cslots
            )
            if not matches_slot:
                conflicts.append({
                    "issue": f"Student-selected course '{e1['subject_name']}' is not in a configured college-wide common time slot.",
                    "fix": f"Move '{e1['subject_name']}' to one of the designated common MDC/Minor periods.",
                    "cells": [{"day": e1["day"], "period": e1["period"]}],
                    "entry_ids": [e1["id"]]
                })

        for j in range(i + 1, len(simulated)):
            e2 = simulated[j]
            if e1["day"] == e2["day"] and ov(e1["start_min"], e1["end_min"], e2["start_min"], e2["end_min"]):
                if e1["faculty_id"] and e1["faculty_id"] == e2["faculty_id"]:
                    fname = fac_meta.get(e1["faculty_id"], {}).get("name", "Faculty")
                    conflicts.append({
                        "issue": f"Teacher conflict: {fname} is scheduled for both '{e1['subject_name']}' and '{e2['subject_name']}' at {when(e1['day'], e1['start_min'], e1['end_min'])}.",
                        "fix": "Move one of these sessions to another period or assign a different teacher.",
                        "cells": [{"day": e1["day"], "period": e1["period"]}, {"day": e2["day"], "period": e2["period"]}],
                        "entry_ids": [e1["id"], e2["id"]]
                    })
                if USE_ROOMS and e1["room_id"] and e1["room_id"] == e2["room_id"]:
                    conflicts.append({
                        "issue": f"Room conflict: Room is double-booked for '{e1['subject_name']}' and '{e2['subject_name']}' at {when(e1['day'], e1['start_min'], e1['end_min'])}.",
                        "fix": "Reassign one of the sessions to another room or move time.",
                        "cells": [{"day": e1["day"], "period": e1["period"]}, {"day": e2["day"], "period": e2["period"]}],
                        "entry_ids": [e1["id"], e2["id"]]
                    })
                if e1["class_id"] and e1["class_id"] == e2["class_id"]:
                    cname = e1.get("class_name") or "Class"
                    conflicts.append({
                        "issue": f"Class overlap: {cname} has overlapping sessions '{e1['subject_name']}' and '{e2['subject_name']}'.",
                        "fix": "Move one of the sessions to a different period.",
                        "cells": [{"day": e1["day"], "period": e1["period"]}, {"day": e2["day"], "period": e2["period"]}],
                        "entry_ids": [e1["id"], e2["id"]]
                    })
                s1_stu = class_stu[e1["class_id"]] if e1["class_id"] else off_stu[e1["course_offering_id"]]
                s2_stu = class_stu[e2["class_id"]] if e2["class_id"] else off_stu[e2["course_offering_id"]]
                shared_st = s1_stu & s2_stu
                if shared_st:
                    conflicts.append({
                        "issue": f"Student clash: {len(shared_st)} student(s) are enrolled in both '{e1['subject_name']}' and '{e2['subject_name']}' at {when(e1['day'], e1['start_min'], e1['end_min'])}.",
                        "fix": "Move one session so enrolled students do not experience timetable clash.",
                        "cells": [{"day": e1["day"], "period": e1["period"]}, {"day": e2["day"], "period": e2["period"]}],
                        "entry_ids": [e1["id"], e2["id"]]
                    })

    for e in simulated:
        for ob in other_busy:
            if e["day"] == ob["day"] and ov(e["start_min"], e["end_min"], ob["start_min"], ob["end_min"]):
                if e["faculty_id"] and e["faculty_id"] == ob["faculty_id"]:
                    fname = fac_meta.get(e["faculty_id"], {}).get("name", "Faculty")
                    conflicts.append({
                        "issue": f"Teacher conflict: {fname} is already teaching '{ob['subject_name']}' ({ob['department_name']}) at {when(e['day'], e['start_min'], e['end_min'])}.",
                        "fix": f"Move '{e['subject_name']}' to another period so {fname} is not double-booked.",
                        "cells": [{"day": e["day"], "period": e["period"]}],
                        "entry_ids": [e["id"]]
                    })
                if USE_ROOMS and e["room_id"] and e["room_id"] == ob["room_id"]:
                    conflicts.append({
                        "issue": f"Room conflict: Room is already booked by {ob['department_name']} for '{ob['subject_name']}' at {when(e['day'], e['start_min'], e['end_min'])}.",
                        "fix": "Assign a different room or select another period.",
                        "cells": [{"day": e["day"], "period": e["period"]}],
                        "entry_ids": [e["id"]]
                    })
                e_stu = class_stu[e["class_id"]] if e["class_id"] else off_stu[e["course_offering_id"]]
                ob_stu = class_stu[ob["class_id"]] if ob["class_id"] else off_stu[ob["course_offering_id"]]
                clash_stu = e_stu & ob_stu
                if clash_stu:
                    conflicts.append({
                        "issue": f"Student clash: {len(clash_stu)} student(s) enrolled in '{e['subject_name']}' are also attending '{ob['subject_name']}' ({ob['department_name']}) at this time.",
                        "fix": "Move this session to another period or common slot.",
                        "cells": [{"day": e["day"], "period": e["period"]}],
                        "entry_ids": [e["id"]]
                    })

    fac_counts = defaultdict(int)
    for ob in other_busy:
        if ob["faculty_id"]:
            fac_counts[ob["faculty_id"]] += 1
    for e in simulated:
        if e["faculty_id"]:
            fac_counts[e["faculty_id"]] += 1
    for fid, cnt in fac_counts.items():
        if fid in fac_meta and cnt > fac_meta[fid]["max"]:
            conflicts.append({
                "issue": f"Workload limit exceeded: {fac_meta[fid]['name']} has {cnt} sessions assigned (maximum limit is {fac_meta[fid]['max']}).",
                "fix": f"Reassign one or more sessions of {fac_meta[fid]['name']} to another teacher.",
                "cells": [],
                "entry_ids": []
            })

    valid = (len(conflicts) == 0)
    return valid, conflicts


@app.post("/api/timetables/validate-batch")
def validate_batch(req: BatchValidateReq, conn=Depends(db), d=Depends(current_department)):
    valid, items = validate_batch_logic(conn, d, req.moves, req.class_id)
    return dict(valid=valid, status="ok" if valid else "conflicts", items=items)


@app.post("/api/timetables/save-batch")
def save_batch(req: BatchValidateReq, conn=Depends(db), d=Depends(current_department)):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(1)")
        valid, items = validate_batch_logic(conn, d, req.moves, req.class_id)
        if not valid:
            raise HTTPException(409, detail={"status": "conflicts", "message": "Cannot save changes because conflicts were detected.", "items": items})

        cfg = load_settings(conn, d["id"])
        periods = cfg["periods"]
        saved_count = 0
        for m in req.moves:
            if m.deleted:
                conn.execute("DELETE FROM timetable_entry WHERE id=%s", (m.id,))
                saved_count += 1
            else:
                p_idx = m.period
                smin = tomin(periods[p_idx]["start"])
                emin = tomin(periods[p_idx]["end"])
                conn.execute("""
                    UPDATE timetable_entry
                    SET day=%s, period=%s, start_min=%s, end_min=%s,
                        faculty_id=coalesce(%s, faculty_id),
                        room_id=coalesce(%s, room_id)
                    WHERE id=%s
                """, (m.day, m.period, smin, emin, m.faculty_id, m.room_id, m.id))
                saved_count += 1
        note(conn, d["id"], "save_batch", new={"saved_count": saved_count})
    return dict(ok=True, saved_count=saved_count, message="All timetable changes saved successfully.")


@app.delete("/api/entries/{entry_id}")
def delete_entry(entry_id: int, conn=Depends(db), d=Depends(current_department)):
    e = conn.execute("""
        SELECT e.*, coalesce(c.department_id, co.offering_department_id) AS dept_id,
               coalesce(s.name, crs.course_name) AS subject
        FROM timetable_entry e
        LEFT JOIN class c ON c.id=e.class_id
        LEFT JOIN teacher_allocation a ON a.id=e.allocation_id
        LEFT JOIN subject s ON s.id=a.subject_id
        LEFT JOIN course_offering co ON co.id=e.course_offering_id
        LEFT JOIN course crs ON crs.id=co.course_id
        WHERE e.id=%s
    """, (entry_id,)).fetchone()
    if not e:
        raise HTTPException(404, "Session not found.")
    if e["dept_id"] != d["id"]:
        raise HTTPException(403, "You cannot delete sessions belonging to another department.")
    conn.execute("DELETE FROM timetable_entry WHERE id=%s", (entry_id,))
    note(conn, d["id"], "delete_entry", entry_id=entry_id, old={"subject": e["subject"], "day": e["day"], "period": e["period"]})
    conn.commit()
    return dict(ok=True)


@app.put("/api/entries/{entry_id}")
def quick_edit_entry(entry_id: int, req: QuickEditReq, conn=Depends(db), d=Depends(current_department)):
    e = conn.execute("""
        SELECT e.*, coalesce(c.department_id, co.offering_department_id) AS dept_id
        FROM timetable_entry e
        LEFT JOIN class c ON c.id=e.class_id
        LEFT JOIN course_offering co ON co.id=e.course_offering_id
        WHERE e.id=%s
    """, (entry_id,)).fetchone()
    if not e:
        raise HTTPException(404, "Session not found.")
    if e["dept_id"] != d["id"]:
        raise HTTPException(403, "You cannot modify sessions belonging to another department.")
    if req.faculty_id is not None:
        conn.execute("UPDATE timetable_entry SET faculty_id=%s WHERE id=%s", (req.faculty_id, entry_id))
    if req.room_id is not None:
        conn.execute("UPDATE timetable_entry SET room_id=%s WHERE id=%s", (req.room_id, entry_id))
    note(conn, d["id"], "quick_edit_entry", entry_id=entry_id, new={"faculty_id": req.faculty_id, "room_id": req.room_id})
    conn.commit()
    return dict(ok=True)


# ---------- common slots (read-only for departments) ----------
@app.get("/api/common-slots")
def list_common_slots(conn=Depends(db), d=Depends(current_department)):
    rows = conn.execute("""SELECT id, day, start_min, end_min, applicable_course_type, name, semester
                           FROM common_time_slot WHERE status='active' ORDER BY day, start_min""").fetchall()
    return [dict(id=r["id"], day=r["day"], day_name=DAYS[r["day"]], start=hm(r["start_min"]), end=hm(r["end_min"]),
                 applicable_course_type=r["applicable_course_type"], name=r["name"], semester=r["semester"])
            for r in rows]


# ---------- courses (Regular, MDC, Minor) ----------
class CourseReq(BaseModel):
    course_code: str
    course_name: str
    course_type: str = "Regular"   # 'Regular', 'MDC', 'Minor'
    selection_type: str | None = None  # 'STUDENT_SELECTED', 'DEPARTMENT_SELECTED'
    description: str | None = None


@app.get("/api/courses")
def get_courses(all: bool = False, conn=Depends(db), d=Depends(current_department)):
    where = "" if all else "WHERE c.department_id=%s"
    args = () if all else (d["id"],)
    rows = conn.execute(f"""SELECT c.*, dp.name department_name, dp.code department_code,
                                   coalesce(ic.name, 'Aided') category_name
                            FROM course c
                            JOIN department dp ON dp.id=c.department_id
                            LEFT JOIN institutional_category ic ON ic.id=dp.category_id
                            {where} ORDER BY c.course_type, c.course_code""", args).fetchall()
    return rows


@app.post("/api/courses")
def create_course(req: CourseReq, conn=Depends(db), d=Depends(current_department)):
    code, name = req.course_code.strip().upper(), " ".join(req.course_name.split())
    if not (2 <= len(code) <= 30 and 2 <= len(name) <= 120):
        raise HTTPException(400, "Please enter valid course code and name.")
    ctype = req.course_type.strip().capitalize()
    if ctype not in ("Regular", "MDC", "Minor"):
        up = req.course_type.strip().upper()
        if up == "REGULAR": ctype = "Regular"
        elif up == "MDC": ctype = "MDC"
        elif up == "MINOR": ctype = "Minor"
        else:
            raise HTTPException(400, "Course type must be Regular, MDC, or Minor.")

    sel_type = req.selection_type
    if ctype == "Regular":
        sel_type = None
    else:
        if sel_type:
            up_sel = sel_type.strip().upper()
            if up_sel in ("STUDENT_SELECTED", "COLLEGE_WIDE", "STUDENT"):
                sel_type = "STUDENT_SELECTED"
            elif up_sel in ("DEPARTMENT_SELECTED", "DEPARTMENT_SPECIFIC", "DEPARTMENT"):
                sel_type = "DEPARTMENT_SELECTED"
            else:
                raise HTTPException(400, "Selection type must be STUDENT_SELECTED or DEPARTMENT_SELECTED for MDC and Minor courses.")
        else:
            sel_type = "STUDENT_SELECTED"

    if conn.execute("SELECT 1 FROM course WHERE lower(course_code)=lower(%s)", (code,)).fetchone():
        raise HTTPException(409, "A course with this code already exists.")
    cid = conn.execute("""INSERT INTO course (course_code, course_name, course_type, selection_type, department_id, description)
                          VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                       (code, name, ctype, sel_type, d["id"], req.description)).fetchone()["id"]
    note(conn, d["id"], "course_add", new={"code": code, "name": name, "type": ctype, "selection_type": sel_type})
    return dict(id=cid, course_code=code, course_type=ctype, selection_type=sel_type)


@app.put("/api/courses/{cid}")
def update_course(cid: int, req: CourseReq, conn=Depends(db), d=Depends(current_department)):
    c = conn.execute("SELECT * FROM course WHERE id=%s", (cid,)).fetchone()
    if not c or c["department_id"] != d["id"]:
        raise HTTPException(404, "Course not found or belongs to another department.")
    code, name = req.course_code.strip().upper(), " ".join(req.course_name.split())
    ctype = req.course_type.strip().capitalize()
    if ctype not in ("Regular", "MDC", "Minor"):
        up = req.course_type.strip().upper()
        if up == "REGULAR": ctype = "Regular"
        elif up == "MDC": ctype = "MDC"
        elif up == "MINOR": ctype = "Minor"
        else:
            raise HTTPException(400, "Course type must be Regular, MDC, or Minor.")

    sel_type = req.selection_type
    if ctype == "Regular":
        sel_type = None
    else:
        if sel_type:
            up_sel = sel_type.strip().upper()
            if up_sel in ("STUDENT_SELECTED", "COLLEGE_WIDE", "STUDENT"):
                sel_type = "STUDENT_SELECTED"
            elif up_sel in ("DEPARTMENT_SELECTED", "DEPARTMENT_SPECIFIC", "DEPARTMENT"):
                sel_type = "DEPARTMENT_SELECTED"
            else:
                raise HTTPException(400, "Selection type must be STUDENT_SELECTED or DEPARTMENT_SELECTED for MDC and Minor courses.")
        else:
            sel_type = c["selection_type"] or "STUDENT_SELECTED"

    if conn.execute("SELECT 1 FROM course WHERE lower(course_code)=lower(%s) AND id<>%s", (code, cid)).fetchone():
        raise HTTPException(409, "A course with this code already exists.")
    conn.execute("""UPDATE course SET course_code=%s, course_name=%s, course_type=%s, selection_type=%s, description=%s WHERE id=%s""",
                 (code, name, ctype, sel_type, req.description, cid))
    note(conn, d["id"], "course_edit", old={"code": c["course_code"]}, new={"code": code, "type": ctype, "selection_type": sel_type})
    return dict(ok=True)


@app.delete("/api/courses/{cid}")
def delete_course(cid: int, conn=Depends(db), d=Depends(current_department)):
    c = conn.execute("SELECT * FROM course WHERE id=%s", (cid,)).fetchone()
    if not c or c["department_id"] != d["id"]:
        raise HTTPException(404, "Course not found or belongs to another department.")
    if conn.execute("SELECT 1 FROM course_offering WHERE course_id=%s", (cid,)).fetchone():
        raise HTTPException(409, "This course has active offerings. Remove offerings first.")
    conn.execute("DELETE FROM course WHERE id=%s", (cid,))
    note(conn, d["id"], "course_delete", old={"code": c["course_code"]})
    return dict(ok=True)


# ---------- course offerings ----------
class OfferingReq(BaseModel):
    course_id: int
    offering_code: str
    scheduling_scope: str | None = None      # 'college_wide', 'department_specific'
    selection_type: str | None = None        # 'STUDENT_SELECTED', 'DEPARTMENT_SELECTED'
    semester: int = 1
    required_sessions: int = 3
    session_duration: int = 60
    max_enrollment: int = 60
    faculty_id: int | None = None
    room_id: int | None = None
    required_room_type: str = "Classroom"


class SectionReq(BaseModel):
    section_name: str
    capacity: int = 60
    faculty_id: int | None = None
    room_id: int | None = None


@app.get("/api/offerings")
def get_offerings(conn=Depends(db), d=Depends(current_department)):
    rows = conn.execute("""
        SELECT co.*, crs.course_code, crs.course_name, crs.course_type,
               coalesce(co.selection_type, crs.selection_type,
                        case when co.scheduling_scope='college_wide' then 'STUDENT_SELECTED' else 'DEPARTMENT_SELECTED' end) selection_type,
               f.name teacher_name, r.name room_name,
               (SELECT count(*) FROM course_enrollment ce WHERE ce.course_offering_id=co.id AND ce.enrollment_status='enrolled') enrolled_count,
               (SELECT count(*) FROM course_section cs WHERE cs.course_offering_id=co.id) section_count,
               EXISTS(SELECT 1 FROM timetable_entry te WHERE te.course_offering_id=co.id) is_scheduled
        FROM course_offering co
        JOIN course crs ON crs.id=co.course_id
        LEFT JOIN faculty f ON f.id=co.faculty_id
        LEFT JOIN room r ON r.id=co.room_id
        WHERE co.offering_department_id=%s
        ORDER BY co.id DESC
    """, (d["id"],)).fetchall()
    return rows


@app.get("/api/offerings/all")
def get_all_offerings(conn=Depends(db), d=Depends(current_department)):
    """Offerings visible for enrollment: student-selected (college-wide) from all depts + department's own offerings."""
    rows = conn.execute("""
        SELECT co.id, co.offering_code, co.semester, co.scheduling_scope,
               coalesce(co.selection_type, crs.selection_type,
                        case when co.scheduling_scope='college_wide' then 'STUDENT_SELECTED' else 'DEPARTMENT_SELECTED' end) selection_type,
               co.required_sessions, co.max_enrollment, co.status, co.offering_department_id,
               crs.course_code, crs.course_name, crs.course_type,
               dp.name offering_department, dp.code department_code,
               coalesce(ic.name, 'Aided') category_name,
               f.name teacher_name, r.name room_name,
               (SELECT count(*) FROM course_enrollment ce WHERE ce.course_offering_id=co.id AND ce.enrollment_status='enrolled') enrolled_count,
               (SELECT count(*) FROM course_section cs WHERE cs.course_offering_id=co.id) section_count
        FROM course_offering co
        JOIN course crs ON crs.id=co.course_id
        JOIN department dp ON dp.id=co.offering_department_id
        LEFT JOIN institutional_category ic ON ic.id=dp.category_id
        LEFT JOIN faculty f ON f.id=co.faculty_id
        LEFT JOIN room r ON r.id=co.room_id
        WHERE co.status='active'
          AND (co.selection_type='STUDENT_SELECTED' OR co.scheduling_scope='college_wide' OR co.offering_department_id=%s)
        ORDER BY co.selection_type, crs.course_type, co.offering_code
    """, (d["id"],)).fetchall()
    return rows


@app.get("/api/offerings/{oid}")
def get_offering_detail(oid: int, conn=Depends(db), d=Depends(current_department)):
    co = conn.execute("""
        SELECT co.*, crs.course_code, crs.course_name, crs.course_type,
               coalesce(co.selection_type, crs.selection_type,
                        case when co.scheduling_scope='college_wide' then 'STUDENT_SELECTED' else 'DEPARTMENT_SELECTED' end) selection_type,
               dp.name offering_department, dp.code department_code,
               f.name teacher_name, r.name room_name
        FROM course_offering co
        JOIN course crs ON crs.id=co.course_id
        JOIN department dp ON dp.id=co.offering_department_id
        LEFT JOIN faculty f ON f.id=co.faculty_id
        LEFT JOIN room r ON r.id=co.room_id
        WHERE co.id=%s
    """, (oid,)).fetchone()
    if not co:
        raise HTTPException(404, "Course offering not found.")
    sections = conn.execute("""
        SELECT cs.*, f.name teacher_name, r.name room_name,
               (SELECT count(*) FROM course_enrollment ce WHERE ce.section_id=cs.id AND ce.enrollment_status='enrolled') enrolled_count
        FROM course_section cs
        LEFT JOIN faculty f ON f.id=cs.faculty_id
        LEFT JOIN room r ON r.id=cs.room_id
        WHERE cs.course_offering_id=%s ORDER BY cs.section_name
    """, (oid,)).fetchall()
    enrollment_summary = conn.execute("""
        SELECT dp.name home_department, count(*) student_count
        FROM course_enrollment ce
        JOIN student s ON s.id=ce.student_id
        JOIN department dp ON dp.id=s.home_department_id
        WHERE ce.course_offering_id=%s AND ce.enrollment_status='enrolled'
        GROUP BY dp.name ORDER BY student_count DESC
    """, (oid,)).fetchall()
    return dict(offering=co, sections=sections, enrollment_summary=enrollment_summary)


@app.post("/api/offerings")
def create_offering(req: OfferingReq, conn=Depends(db), d=Depends(current_department)):
    code = req.offering_code.strip().upper()
    if not (2 <= len(code) <= 40):
        raise HTTPException(400, "Please provide a valid offering code (e.g. MDC1-2026-SEM1).")
    crs = conn.execute("SELECT * FROM course WHERE id=%s", (req.course_id,)).fetchone()
    if not crs:
        raise HTTPException(404, "Course not found.")

    sel_type = req.selection_type or crs["selection_type"]
    if not sel_type:
        if req.scheduling_scope == "department_specific":
            sel_type = "DEPARTMENT_SELECTED"
        else:
            sel_type = "STUDENT_SELECTED"
    else:
        up_sel = sel_type.strip().upper()
        if up_sel in ("STUDENT_SELECTED", "COLLEGE_WIDE", "STUDENT"):
            sel_type = "STUDENT_SELECTED"
        elif up_sel in ("DEPARTMENT_SELECTED", "DEPARTMENT_SPECIFIC", "DEPARTMENT"):
            sel_type = "DEPARTMENT_SELECTED"

    scope = "college_wide" if sel_type == "STUDENT_SELECTED" else "department_specific"

    if conn.execute("SELECT 1 FROM course_offering WHERE lower(offering_code)=lower(%s)", (code,)).fetchone():
        raise HTTPException(409, "A course offering with this code already exists.")

    oid = conn.execute("""
        INSERT INTO course_offering (offering_code, course_id, offering_department_id, semester,
                                     scheduling_scope, selection_type, required_sessions, session_duration, max_enrollment,
                                     faculty_id, room_id, required_room_type)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (code, req.course_id, d["id"], req.semester, scope, sel_type, req.required_sessions,
          req.session_duration, req.max_enrollment, req.faculty_id, req.room_id, req.required_room_type)).fetchone()["id"]
    note(conn, d["id"], "offering_add", new={"code": code, "scope": scope, "selection_type": sel_type})
    return dict(id=oid, offering_code=code, selection_type=sel_type, scheduling_scope=scope)


@app.put("/api/offerings/{oid}")
def update_offering(oid: int, req: OfferingReq, conn=Depends(db), d=Depends(current_department)):
    co = conn.execute("SELECT * FROM course_offering WHERE id=%s", (oid,)).fetchone()
    if not co or co["offering_department_id"] != d["id"]:
        raise HTTPException(404, "Course offering not found or belongs to another department.")
    code = req.offering_code.strip().upper()
    if conn.execute("SELECT 1 FROM course_offering WHERE lower(offering_code)=lower(%s) AND id<>%s", (code, oid)).fetchone():
        raise HTTPException(409, "A course offering with this code already exists.")

    sel_type = req.selection_type or co["selection_type"]
    if req.scheduling_scope:
        if req.scheduling_scope == "college_wide": sel_type = "STUDENT_SELECTED"
        elif req.scheduling_scope == "department_specific": sel_type = "DEPARTMENT_SELECTED"
    if sel_type:
        up_sel = sel_type.strip().upper()
        if up_sel in ("STUDENT_SELECTED", "COLLEGE_WIDE", "STUDENT"): sel_type = "STUDENT_SELECTED"
        elif up_sel in ("DEPARTMENT_SELECTED", "DEPARTMENT_SPECIFIC", "DEPARTMENT"): sel_type = "DEPARTMENT_SELECTED"
    else:
        sel_type = "STUDENT_SELECTED"
    scope = "college_wide" if sel_type == "STUDENT_SELECTED" else "department_specific"

    conn.execute("""
        UPDATE course_offering SET offering_code=%s, course_id=%s, semester=%s,
                                   scheduling_scope=%s, selection_type=%s,
                                   required_sessions=%s, session_duration=%s, max_enrollment=%s,
                                   faculty_id=%s, room_id=%s, required_room_type=%s
        WHERE id=%s
    """, (code, req.course_id, req.semester, scope, sel_type, req.required_sessions,
          req.session_duration, req.max_enrollment, req.faculty_id, req.room_id, req.required_room_type, oid))
    note(conn, d["id"], "offering_edit", old={"code": co["offering_code"]}, new={"code": code, "selection_type": sel_type})
    return dict(ok=True)


@app.delete("/api/offerings/{oid}")
def delete_offering(oid: int, conn=Depends(db), d=Depends(current_department)):
    co = conn.execute("SELECT * FROM course_offering WHERE id=%s", (oid,)).fetchone()
    if not co or co["offering_department_id"] != d["id"]:
        raise HTTPException(404, "Course offering not found or belongs to another department.")
    with conn.transaction():
        conn.execute("DELETE FROM timetable_entry WHERE course_offering_id=%s", (oid,))
        conn.execute("DELETE FROM course_enrollment WHERE course_offering_id=%s", (oid,))
        conn.execute("DELETE FROM course_section WHERE course_offering_id=%s", (oid,))
        conn.execute("DELETE FROM course_offering WHERE id=%s", (oid,))
    note(conn, d["id"], "offering_delete", old={"code": co["offering_code"]})
    return dict(ok=True)


@app.post("/api/offerings/{oid}/sections")
def add_section(oid: int, req: SectionReq, conn=Depends(db), d=Depends(current_department)):
    co = conn.execute("SELECT * FROM course_offering WHERE id=%s", (oid,)).fetchone()
    if not co or co["offering_department_id"] != d["id"]:
        raise HTTPException(404, "Course offering not found.")
    sname = req.section_name.strip().upper()[:10]
    if not sname:
        raise HTTPException(400, "Section name is required (e.g. A, B).")
    try:
        sid = conn.execute("""INSERT INTO course_section (course_offering_id, section_name, capacity, faculty_id, room_id)
                              VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                           (oid, sname, req.capacity, req.faculty_id or co["faculty_id"], req.room_id or co["room_id"])).fetchone()["id"]
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, f"Section {sname} already exists for this offering.")
    return dict(id=sid, section_name=sname)


@app.delete("/api/offerings/{oid}/sections/{sid}")
def delete_section(oid: int, sid: int, conn=Depends(db), d=Depends(current_department)):
    co = conn.execute("SELECT * FROM course_offering WHERE id=%s", (oid,)).fetchone()
    if not co or co["offering_department_id"] != d["id"]:
        raise HTTPException(404, "Course offering not found.")
    conn.execute("DELETE FROM course_section WHERE id=%s AND course_offering_id=%s", (sid, oid))
    return dict(ok=True)


@app.get("/api/offerings/{oid}/timetable")
def offering_timetable(oid: int, conn=Depends(db), d=Depends(current_department)):
    rows = conn.execute("""
        SELECT te.id, te.day, te.period, te.start_min, te.end_min,
               crs.course_name subject, crs.course_type, co.offering_code,
               sec.section_name, f.name teacher, r.name room
        FROM timetable_entry te
        JOIN course_offering co ON co.id=te.course_offering_id
        JOIN course crs ON crs.id=co.course_id
        LEFT JOIN course_section sec ON sec.id=te.section_id
        LEFT JOIN faculty f ON f.id=te.faculty_id
        LEFT JOIN room r ON r.id=te.room_id
        WHERE te.course_offering_id=%s ORDER BY te.day, te.start_min
    """, (oid,)).fetchall()
    return [dict(id=r["id"], day=r["day"], period=r["period"], start=hm(r["start_min"]), end=hm(r["end_min"]),
                 subject=r["subject"], course_type=r["course_type"], offering_code=r["offering_code"],
                 section=r["section_name"], teacher=r["teacher"], room=r["room"])
            for r in rows]


# ---------- students ----------
class StudentReq(BaseModel):
    register_number: str
    name: str
    semester: int = 1
    class_id: int | None = None


class BulkStudentReq(BaseModel):
    students: list[dict] | None = None
    csv: str | None = None


@app.get("/api/students")
def get_students(class_id: int | None = None, conn=Depends(db), d=Depends(current_department)):
    where = "WHERE s.home_department_id=%s" + (" AND s.class_id=%s" if class_id else "")
    args = (d["id"],) + ((class_id,) if class_id else ())
    rows = conn.execute(f"""
        SELECT s.*, c.name class_name, dp.name home_department,
               coalesce(ic.name, 'Aided') category_name,
               (SELECT count(*) FROM course_enrollment ce WHERE ce.student_id=s.id AND ce.enrollment_status='enrolled') enrolled_offerings_count
        FROM student s
        JOIN department dp ON dp.id=s.home_department_id
        LEFT JOIN institutional_category ic ON ic.id=dp.category_id
        LEFT JOIN class c ON c.id=s.class_id
        {where} ORDER BY s.register_number
    """, args).fetchall()
    return rows


@app.post("/api/students")
def create_student(req: StudentReq, conn=Depends(db), d=Depends(current_department)):
    reg = req.register_number.strip().upper()
    name = " ".join(req.name.split())
    if not (2 <= len(reg) <= 30 and 2 <= len(name) <= 80):
        raise HTTPException(400, "Please provide valid student register number and name.")
    if conn.execute("SELECT 1 FROM student WHERE lower(register_number)=lower(%s)", (reg,)).fetchone():
        raise HTTPException(409, "A student with this register number already exists.")
    if req.class_id:
        own_class(conn, d, req.class_id)
    sid = conn.execute("""
        INSERT INTO student (register_number, name, home_department_id, semester, class_id)
        VALUES (%s,%s,%s,%s,%s) RETURNING id
    """, (reg, name, d["id"], req.semester, req.class_id)).fetchone()["id"]
    note(conn, d["id"], "student_add", new={"reg": reg, "name": name})
    return dict(id=sid, register_number=reg)


@app.post("/api/students/bulk")
def bulk_create_students(req: BulkStudentReq, conn=Depends(db), d=Depends(current_department)):
    items = []
    if req.students:
        items = req.students
    elif req.csv:
        lines = [l.strip() for l in req.csv.splitlines() if l.strip()]
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                items.append(dict(register_number=parts[0], name=parts[1],
                                  semester=int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1))
    if not items:
        raise HTTPException(400, "No students provided. Upload CSV or send a student list.")
    created, skipped = 0, 0
    with conn.transaction():
        for st in items:
            reg = str(st.get("register_number", "")).strip().upper()
            name = " ".join(str(st.get("name", "")).split())
            sem = int(st.get("semester", 1))
            cid = st.get("class_id")
            if not (reg and name):
                continue
            if conn.execute("SELECT 1 FROM student WHERE lower(register_number)=lower(%s)", (reg,)).fetchone():
                skipped += 1
                continue
            conn.execute("INSERT INTO student (register_number, name, home_department_id, semester, class_id) VALUES (%s,%s,%s,%s,%s)",
                         (reg, name, d["id"], sem, cid))
            created += 1
    return dict(created=created, skipped=skipped)


@app.put("/api/students/{sid}")
def update_student(sid: int, req: StudentReq, conn=Depends(db), d=Depends(current_department)):
    s = conn.execute("SELECT * FROM student WHERE id=%s", (sid,)).fetchone()
    if not s or s["home_department_id"] != d["id"]:
        raise HTTPException(404, "Student not found or belongs to another department.")
    reg = req.register_number.strip().upper()
    name = " ".join(req.name.split())
    if conn.execute("SELECT 1 FROM student WHERE lower(register_number)=lower(%s) AND id<>%s", (reg, sid)).fetchone():
        raise HTTPException(409, "A student with this register number already exists.")
    if req.class_id:
        own_class(conn, d, req.class_id)
    conn.execute("UPDATE student SET register_number=%s, name=%s, semester=%s, class_id=%s WHERE id=%s",
                 (reg, name, req.semester, req.class_id, sid))
    return dict(ok=True)


@app.delete("/api/students/{sid}")
def delete_student(sid: int, conn=Depends(db), d=Depends(current_department)):
    s = conn.execute("SELECT * FROM student WHERE id=%s", (sid,)).fetchone()
    if not s or s["home_department_id"] != d["id"]:
        raise HTTPException(404, "Student not found.")
    conn.execute("DELETE FROM student WHERE id=%s", (sid,))
    return dict(ok=True)


@app.get("/api/students/{sid}/timetable")
def student_timetable(sid: int, conn=Depends(db), d=Depends(current_department)):
    """Unified Student Timetable: combines regular home-department subjects + enrolled MDC & Minor offerings."""
    st = conn.execute("""
        SELECT s.*, dp.name home_department, coalesce(ic.name, 'Aided') category_name, c.name class_name
        FROM student s
        JOIN department dp ON dp.id=s.home_department_id
        LEFT JOIN institutional_category ic ON ic.id=dp.category_id
        LEFT JOIN class c ON c.id=s.class_id
        WHERE s.id=%s
    """, (sid,)).fetchone()
    if not st:
        raise HTTPException(404, "Student not found.")

    entries = []
    # 1. Regular class timetable
    if st["class_id"]:
        rows = conn.execute("""
            SELECT te.id, te.day, te.period, te.start_min, te.end_min,
                   s.name subject, 'Regular' course_type, c.name class_or_offering,
                   f.name teacher, r.name room, dp.name department
            FROM timetable_entry te
            JOIN teacher_allocation a ON a.id=te.allocation_id
            JOIN subject s ON s.id=a.subject_id
            JOIN class c ON c.id=te.class_id
            JOIN department dp ON dp.id=c.department_id
            LEFT JOIN faculty f ON f.id=te.faculty_id
            LEFT JOIN room r ON r.id=te.room_id
            WHERE te.class_id=%s ORDER BY te.day, te.start_min
        """, (st["class_id"],)).fetchall()
        for r in rows:
            entries.append(dict(id=r["id"], day=r["day"], period=r["period"], start=hm(r["start_min"]), end=hm(r["end_min"]),
                                smin=r["start_min"], emin=r["end_min"], subject=r["subject"], course_type=r["course_type"],
                                class_or_offering=r["class_or_offering"], teacher=r["teacher"], room=r["room"],
                                department=r["department"]))

    # 2. Enrolled course offerings (cross-department MDC / Minor)
    off_rows = conn.execute("""
        SELECT te.id, te.day, te.period, te.start_min, te.end_min,
               crs.course_name subject, crs.course_type, co.offering_code class_or_offering,
               f.name teacher, r.name room, dp.name department
        FROM timetable_entry te
        JOIN course_offering co ON co.id=te.course_offering_id
        JOIN course crs ON crs.id=co.course_id
        JOIN department dp ON dp.id=co.offering_department_id
        LEFT JOIN faculty f ON f.id=te.faculty_id
        LEFT JOIN room r ON r.id=te.room_id
        JOIN course_enrollment ce ON ce.course_offering_id=co.id AND (ce.section_id IS NULL OR te.section_id IS NULL OR ce.section_id=te.section_id)
        WHERE ce.student_id=%s AND ce.enrollment_status='enrolled'
        ORDER BY te.day, te.start_min
    """, (sid,)).fetchall()
    for r in off_rows:
        entries.append(dict(id=r["id"], day=r["day"], period=r["period"], start=hm(r["start_min"]), end=hm(r["end_min"]),
                            smin=r["start_min"], emin=r["end_min"], subject=r["subject"], course_type=r["course_type"],
                            class_or_offering=r["class_or_offering"], teacher=r["teacher"], room=r["room"],
                            department=r["department"]))

    entries.sort(key=lambda x: (x["day"], x["smin"]))
    return dict(student=st, entries=entries)


# ---------- cross-department enrollment management ----------
class EnrollReq(BaseModel):
    student_ids: list[int]
    section_id: int | None = None


class BulkEnrollReq(BaseModel):
    register_numbers: list[str] | str
    section_id: int | None = None


@app.get("/api/offerings/{oid}/enrollments")
def get_offering_enrollments(oid: int, conn=Depends(db), d=Depends(current_department)):
    co = conn.execute("SELECT * FROM course_offering WHERE id=%s", (oid,)).fetchone()
    if not co:
        raise HTTPException(404, "Course offering not found.")
    students = conn.execute("""
        SELECT s.id, s.register_number, s.name, dp.name home_department, dp.code department_code,
               coalesce(ic.name, 'Aided') category_name, ce.section_id, cs.section_name, ce.enrollment_date
        FROM course_enrollment ce
        JOIN student s ON s.id=ce.student_id
        JOIN department dp ON dp.id=s.home_department_id
        LEFT JOIN institutional_category ic ON ic.id=dp.category_id
        LEFT JOIN course_section cs ON cs.id=ce.section_id
        WHERE ce.course_offering_id=%s AND ce.enrollment_status='enrolled'
        ORDER BY dp.name, s.register_number
    """, (oid,)).fetchall()
    by_dept = defaultdict(int)
    for st in students:
        by_dept[st["home_department"]] += 1
    return dict(total_enrolled=len(students), by_department=dict(by_dept), students=students)


@app.post("/api/offerings/{oid}/enroll")
def enroll_students(oid: int, req: EnrollReq, conn=Depends(db), d=Depends(current_department)):
    co = conn.execute("""
        SELECT co.*, crs.course_type, crs.selection_type course_sel_type
        FROM course_offering co
        JOIN course crs ON crs.id=co.course_id
        WHERE co.id=%s
    """, (oid,)).fetchone()
    if not co:
        raise HTTPException(404, "Course offering not found.")

    sel_type = co.get("selection_type") or co.get("course_sel_type")
    if not sel_type:
        sel_type = "STUDENT_SELECTED" if co.get("scheduling_scope") == "college_wide" else "DEPARTMENT_SELECTED"

    # Restriction for Department-Selected courses:
    # Only students belonging to the offering department may enroll. Cross-department enrollment is prohibited.
    if sel_type == "DEPARTMENT_SELECTED":
        cross = conn.execute("""
            SELECT s.register_number, s.name, dp.name dept_name
            FROM student s
            JOIN department dp ON dp.id=s.home_department_id
            WHERE s.id = ANY(%s) AND s.home_department_id <> %s
        """, (req.student_ids, co["offering_department_id"])).fetchall()
        if cross:
            s_list = ", ".join(f"{s['register_number']} ({s['dept_name']})" for s in cross[:3])
            raise HTTPException(400, f"Cross-department enrollment is prohibited for department-selected courses. {s_list} does not belong to the offering department.")

    enrolled_count = conn.execute("SELECT count(*) n FROM course_enrollment WHERE course_offering_id=%s AND enrollment_status='enrolled'", (oid,)).fetchone()["n"]
    cap = co["max_enrollment"]
    if req.section_id:
        sec = conn.execute("SELECT * FROM course_section WHERE id=%s AND course_offering_id=%s", (req.section_id, oid)).fetchone()
        if not sec:
            raise HTTPException(400, "Section not found for this offering.")
        cap = sec["capacity"]
        enrolled_count = conn.execute("SELECT count(*) n FROM course_enrollment WHERE section_id=%s AND enrollment_status='enrolled'", (req.section_id,)).fetchone()["n"]

    added = 0
    with conn.transaction():
        for sid in req.student_ids:
            if conn.execute("SELECT 1 FROM course_enrollment WHERE student_id=%s AND course_offering_id=%s", (sid, oid)).fetchone():
                continue
            if enrolled_count + added >= cap:
                raise HTTPException(409, f"Enrollment capacity ({cap}) exceeded. Add an additional section or increase capacity.")
            conn.execute("""
                INSERT INTO course_enrollment (student_id, course_offering_id, section_id)
                VALUES (%s,%s,%s)
                ON CONFLICT (student_id, course_offering_id) DO UPDATE SET enrollment_status='enrolled', section_id=EXCLUDED.section_id
            """, (sid, oid, req.section_id))
            added += 1
    return dict(enrolled=added, total=enrolled_count + added)


@app.post("/api/offerings/{oid}/bulk-enroll")
def bulk_enroll_students(oid: int, req: BulkEnrollReq, conn=Depends(db), d=Depends(current_department)):
    co = conn.execute("SELECT * FROM course_offering WHERE id=%s", (oid,)).fetchone()
    if not co:
        raise HTTPException(404, "Course offering not found.")
    regs = []
    if isinstance(req.register_numbers, list):
        regs = [r.strip().upper() for r in req.register_numbers if r.strip()]
    elif isinstance(req.register_numbers, str):
        import re as re_mod
        regs = [r.strip().upper() for r in re_mod.split(r"[\n,\s]+", req.register_numbers) if r.strip()]

    students = conn.execute("SELECT id, register_number FROM student WHERE upper(register_number) = ANY(%s)", (regs,)).fetchall()
    found_ids = [s["id"] for s in students]
    if not found_ids:
        raise HTTPException(400, "No matching students found with those register numbers.")
    return enroll_students(oid, EnrollReq(student_ids=found_ids, section_id=req.section_id), conn, d)


@app.delete("/api/offerings/{oid}/enroll/{student_id}")
def unenroll_student(oid: int, student_id: int, conn=Depends(db), d=Depends(current_department)):
    conn.execute("DELETE FROM course_enrollment WHERE course_offering_id=%s AND student_id=%s", (oid, student_id))
    return dict(ok=True)


# ---------- college-wide common course timetable ----------
@app.get("/api/timetables/common-courses")
def college_wide_common_timetable(conn=Depends(db), d=Depends(current_department)):
    """All scheduled college-wide MDC and Minor offerings across departments."""
    rows = conn.execute("""
        SELECT te.id, te.day, te.period, te.start_min, te.end_min,
               crs.course_name subject, crs.course_code, crs.course_type,
               co.offering_code, co.scheduling_scope,
               dp.name department, dp.code department_code,
               coalesce(ic.name, 'Aided') category_name,
               sec.section_name, f.name teacher, r.name room,
               (SELECT count(*) FROM course_enrollment ce WHERE ce.course_offering_id=co.id AND ce.enrollment_status='enrolled') enrolled_count
        FROM timetable_entry te
        JOIN course_offering co ON co.id=te.course_offering_id
        JOIN course crs ON crs.id=co.course_id
        JOIN department dp ON dp.id=co.offering_department_id
        LEFT JOIN institutional_category ic ON ic.id=dp.category_id
        LEFT JOIN course_section sec ON sec.id=te.section_id
        LEFT JOIN faculty f ON f.id=te.faculty_id
        LEFT JOIN room r ON r.id=te.room_id
        WHERE co.scheduling_scope='college_wide'
        ORDER BY te.day, te.start_min, co.offering_code
    """).fetchall()
    return [dict(id=r["id"], day=r["day"], period=r["period"], start=hm(r["start_min"]), end=hm(r["end_min"]),
                 subject=r["subject"], course_code=r["course_code"], course_type=r["course_type"],
                 offering_code=r["offering_code"], department=r["department"], department_code=r["department_code"],
                 category=r["category_name"], section=r["section_name"], teacher=r["teacher"], room=r["room"],
                 enrolled_count=r["enrolled_count"])
            for r in rows]


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
