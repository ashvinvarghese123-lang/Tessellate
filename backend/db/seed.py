"""Loads the sample college into the database. Safe to run again (it clears the sample data first).
Usage: python db/seed.py        (uses DATABASE_URL or the docker-compose default)
"""
import os, secrets, sys
import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api.auth import hash_password   # noqa: E402

DSN = os.environ.get("DATABASE_URL", "postgresql://tess:tess@localhost:5432/tessellate")
TIMES = [("09:00", "10:00"), ("10:00", "11:00"), ("11:15", "12:15"),
         ("12:15", "13:15"), ("14:00", "15:00"), ("15:00", "16:00")]   # breaks/lunch are not slots
DEPTS = [("DEPT-CS", "Computer Science"), ("DEPT-BCA", "BCA"), ("DEPT-MATH", "Mathematics"),
         ("DEPT-COM", "Commerce"), ("DEPT-PHY", "Physics")]
USERNAMES = {"DEPT-CS": "cs", "DEPT-BCA": "bca", "DEPT-MATH": "maths", "DEPT-COM": "commerce", "DEPT-PHY": "physics"}
# code, name, home dept, designation, max sessions, unavailable (day, period) list
FACULTY = [("FAC-001", "Dr. Anil Kumar", "DEPT-CS", "Associate Professor", 18, []),
           ("FAC-002", "Prof. Meera Nair", "DEPT-CS", "Professor", 16, []),
           ("FAC-003", "Dr. Rahul Menon", "DEPT-MATH", "Professor", 22, []),
           ("FAC-004", "Ms. Sana Iqbal", "DEPT-COM", "Assistant Professor", 18, []),
           ("FAC-005", "Mr. Joseph Thomas", "DEPT-MATH", "Assistant Professor", 16, [(4, p) for p in range(6)]),
           ("FAC-006", "Dr. Lakshmi Rao", "DEPT-COM", "Associate Professor", 16, [(2, 4), (2, 5)]),
           ("FAC-007", "Mr. Kiran Das", "DEPT-PHY", "Assistant Professor", 18, []),
           ("FAC-008", "Ms. Divya Pillai", "DEPT-BCA", "Assistant Professor", 16, [])]
ROOMS = [("Room 101", "Classroom", 70), ("Room 102", "Classroom", 70), ("Room 103", "Classroom", 50),
         ("Room 104", "Classroom", 40), ("Lab 1", "Computer lab", 40), ("Lab 2", "Computer lab", 40),
         ("Physics Lab", "Laboratory", 30)]
# name, dept, semester, students, home room
CLASSES = [("BSc CS · Sem 1 · A", "DEPT-CS", 1, 58, "Room 101"), ("BSc CS · Sem 2 · A", "DEPT-CS", 2, 52, "Room 102"),
           ("BCA · Sem 1 · A", "DEPT-BCA", 1, 60, "Room 101"), ("BSc Maths · Sem 1 · A", "DEPT-MATH", 1, 40, "Room 103"),
           ("BCom · Sem 1 · A", "DEPT-COM", 1, 64, "Room 102"), ("BSc Physics · Sem 1 · A", "DEPT-PHY", 1, 36, "Room 103")]
C = "Classroom"; L = "Computer lab"; P = "Laboratory"
# class, subject, faculty code, sessions per week, room type
ALLOC = [("BSc CS · Sem 1 · A", "Python", "FAC-001", 3, C), ("BSc CS · Sem 1 · A", "Mathematics", "FAC-003", 4, C),
 ("BSc CS · Sem 1 · A", "DBMS", "FAC-002", 3, C), ("BSc CS · Sem 1 · A", "English", "FAC-004", 3, C),
 ("BSc CS · Sem 1 · A", "Python Lab", "FAC-001", 2, L),
 ("BSc CS · Sem 2 · A", "DBMS", "FAC-002", 3, C), ("BSc CS · Sem 2 · A", "Data Structures", "FAC-002", 4, C),
 ("BSc CS · Sem 2 · A", "Statistics", "FAC-003", 3, C), ("BSc CS · Sem 2 · A", "English", "FAC-004", 2, C),
 ("BSc CS · Sem 2 · A", "DS Lab", "FAC-002", 2, L),
 ("BCA · Sem 1 · A", "Programming", "FAC-001", 3, C), ("BCA · Sem 1 · A", "Mathematics", "FAC-003", 3, C),
 ("BCA · Sem 1 · A", "Web Tech", "FAC-008", 3, C), ("BCA · Sem 1 · A", "English", "FAC-004", 3, C),
 ("BCA · Sem 1 · A", "Programming Lab", "FAC-008", 2, L),
 ("BSc Maths · Sem 1 · A", "Mathematics", "FAC-001", 4, C), ("BSc Maths · Sem 1 · A", "Calculus", "FAC-003", 3, C),
 ("BSc Maths · Sem 1 · A", "Algebra", "FAC-005", 4, C), ("BSc Maths · Sem 1 · A", "English", "FAC-004", 2, C),
 ("BCom · Sem 1 · A", "Accounting", "FAC-006", 4, C), ("BCom · Sem 1 · A", "Business Law", "FAC-005", 3, C),
 ("BCom · Sem 1 · A", "Economics", "FAC-006", 3, C), ("BCom · Sem 1 · A", "English", "FAC-004", 3, C),
 ("BCom · Sem 1 · A", "Statistics", "FAC-003", 2, C),
 ("BSc Physics · Sem 1 · A", "Mechanics", "FAC-007", 4, C), ("BSc Physics · Sem 1 · A", "Optics", "FAC-007", 3, C),
 ("BSc Physics · Sem 1 · A", "Physics Lab", "FAC-007", 2, P), ("BSc Physics · Sem 1 · A", "English", "FAC-004", 2, C),
 ("BSc Physics · Sem 1 · A", "Mathematics", "FAC-003", 3, C)]


def main():
    with psycopg.connect(DSN) as c:
        c.execute("""TRUNCATE college, department, academic_year, time_slot, faculty, room, class, subject,
                     teacher_allocation, timetable, timetable_entry, generation_run, audit_log, department_account, registry_account RESTART IDENTITY CASCADE""")
        c.execute("INSERT INTO college (name, days, periods) VALUES ('Northfield Arts & Science College', 5, 6)")
        c.execute("INSERT INTO academic_year (label) VALUES ('2026-27')")
        year = c.execute("SELECT id FROM academic_year").fetchone()[0]
        for d in range(5):
            for p, (a, b) in enumerate(TIMES):
                c.execute("INSERT INTO time_slot (day, period, starts, ends) VALUES (%s,%s,%s,%s)", (d, p, a, b))
        dept = {code: c.execute("INSERT INTO department (code, name) VALUES (%s,%s) RETURNING id", (code, n)).fetchone()[0]
                for code, n in DEPTS}
        # One secure account per department. Passwords are random and shown ONCE; change them after first login.
        print("\nDepartment accounts (save these now):")
        for code, n in DEPTS:
            u = USERNAMES[code]
            pw = os.environ.get("SEED_PASSWORD") or secrets.token_urlsafe(9) + "7"
            c.execute("INSERT INTO department_account (department_id, username, email, password_hash) VALUES (%s,%s,%s,%s)",
                      (dept[code], u, f"{u}@college.edu", hash_password(pw)))
            print(f"  {n:<18} username: {u:<9} password: {pw}")
        rpw = os.environ.get("SEED_PASSWORD") or secrets.token_urlsafe(9) + "7"
        c.execute("INSERT INTO registry_account (username, email, password_hash) VALUES ('registry','registry@college.edu',%s)", (hash_password(rpw),))
        print(f"  {'College Registry':<18} username: registry  password: {rpw}   (data only: departments, faculty, classes, rooms)")
        room = {n: c.execute("INSERT INTO room (name, room_type, capacity) VALUES (%s,%s,%s) RETURNING id", (n, t, cap)).fetchone()[0]
                for n, t, cap in ROOMS}
        fac = {}
        for code, n, d, dg, mx, un in FACULTY:
            fid = c.execute("""INSERT INTO faculty (faculty_code, name, home_department_id, designation, max_weekly_sessions)
                               VALUES (%s,%s,%s,%s,%s) RETURNING id""", (code, n, dept[d], dg, mx)).fetchone()[0]
            fac[code] = fid
            for day, per in un:
                c.execute("""INSERT INTO faculty_availability (faculty_id, time_slot_id)
                             SELECT %s, id FROM time_slot WHERE day=%s AND period=%s""", (fid, day, per))
        cls = {}
        for n, d, sem, stu, hr in CLASSES:
            cid = c.execute("""INSERT INTO class (department_id, academic_year_id, semester, section, name, students, home_room_id)
                               VALUES (%s,%s,%s,'A',%s,%s,%s) RETURNING id""", (dept[d], year, sem, n, stu, room[hr])).fetchone()[0]
            cls[n] = (cid, dept[d])
            c.execute("INSERT INTO timetable (class_id, department_id) VALUES (%s,%s)", (cid, dept[d]))
        for cn, sub, fcode, n, rt in ALLOC:
            cid, did = cls[cn]
            sid = c.execute("""INSERT INTO subject (name, department_id, kind, required_room_type)
                               VALUES (%s,%s,%s,%s) RETURNING id""", (sub, did, "Lecture" if rt == C else "Lab", rt)).fetchone()[0]
            c.execute("""INSERT INTO teacher_allocation (class_id, subject_id, faculty_id, sessions_per_week)
                         VALUES (%s,%s,%s,%s)""", (cid, sid, fac[fcode], n))
    print("Seeded:", len(DEPTS), "departments,", len(FACULTY), "faculty,", len(CLASSES), "classes,", len(ALLOC), "subjects.")


if __name__ == "__main__":
    main()
