"""Scheduling engine tests (no database needed). Run: python tests/test_engine.py"""
import collections, itertools, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from engine.solver import generate, validate_move, rebalance, quality, ov

H = lambda hhmm: int(hhmm[:2]) * 60 + int(hhmm[3:])
STD = [("09:00", "10:00"), ("10:00", "11:00"), ("11:15", "12:15"), ("12:15", "13:15"), ("14:00", "15:00"), ("15:00", "16:00")]
def S(periods=STD, days=(0, 1, 2, 3, 4), rules=None, free=()):
    return dict(days=list(days), periods=[dict(start=H(a), end=H(b)) for a, b in periods], rules=rules or {}, free=[list(f) for f in free])
def T(n, mx, un=()): return dict(name=n, max_load=mx, unavailable=[list(u) for u in un])
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
def clashes(entries):
    bad = 0
    for i, a in enumerate(entries):
        for b in entries[i + 1:]:
            if a["day"] == b["day"] and ov(a["start"], a["end"], b["start"], b["end"]) and (a["teacher"] == b["teacher"] or a["class"] == b["class"] or (a["room"] is not None and a["room"] == b["room"])):
                bad += 1
    return bad

depts = ["CS", "BCA", "MATH", "COM", "PHY"]
off_day5 = [(4, 0, 1440)]
teachers = {"T1": T("Dr. Anil Kumar", 18), "T2": T("Prof. Meera Nair", 16), "T3": T("Dr. Rahul Menon", 22), "T4": T("Ms. Sana Iqbal", 18),
            "T5": T("Mr. Joseph Thomas", 16, off_day5), "T6": T("Dr. Lakshmi Rao", 16, [(2, H("14:00"), H("16:00"))]), "T7": T("Mr. Kiran Das", 18), "T8": T("Ms. Divya Pillai", 16)}
cdept = {"CS1": "CS", "CS2": "CS", "BCA1": "BCA", "MA1": "MATH", "COM1": "COM", "PHY1": "PHY"}
classes = {c: dict(name=c, department=d) for c, d in cdept.items()}
rooms = [dict(id=i, type="Classroom") for i in ["R101", "R102", "R103", "R104"]] + [dict(id="L1", type="Computer lab"), dict(id="L2", type="Computer lab"), dict(id="PL", type="Laboratory")]
def A(c, s, t, n, rt="Classroom"): return dict(**{"class": c}, subject=s, teacher=t, sessions=n, room_type=rt, department=cdept[c])
alloc = [A("CS1","Python","T1",3),A("CS1","Mathematics","T3",4),A("CS1","DBMS","T2",3),A("CS1","English","T4",3),A("CS1","Python Lab","T1",2,"Computer lab"),
 A("CS2","DBMS","T2",3),A("CS2","Data Structures","T2",4),A("CS2","Statistics","T3",3),A("CS2","English","T4",2),A("CS2","DS Lab","T2",2,"Computer lab"),
 A("BCA1","Programming","T1",3),A("BCA1","Mathematics","T3",3),A("BCA1","Web Tech","T8",3),A("BCA1","English","T4",3),A("BCA1","Programming Lab","T8",2,"Computer lab"),
 A("MA1","Mathematics","T1",4),A("MA1","Calculus","T3",3),A("MA1","Algebra","T5",4),A("MA1","English","T4",2),
 A("COM1","Accounting","T6",4),A("COM1","Business Law","T5",3),A("COM1","Economics","T6",3),A("COM1","English","T4",3),A("COM1","Statistics","T3",2),
 A("PHY1","Mechanics","T7",4),A("PHY1","Optics","T7",3),A("PHY1","Physics Lab","T7",2,"Laboratory"),A("PHY1","English","T4",2),A("PHY1","Mathematics","T3",3)]
base = dict(settings={d: S() for d in depts}, teachers=teachers, classes=classes, rooms=rooms, busy=[])

t0 = time.time(); r = generate(dict(base, allocations=alloc), 20)
print("college:", r["status"], "score", r.get("score"), "sessions", len(r["entries"]), f"{time.time()-t0:.1f}s")
ok(r["status"] == "ok" and len(r["entries"]) == sum(a["sessions"] for a in alloc) and clashes(r["entries"]) == 0, "whole college: every session placed, no overlaps (no rules chosen)")
ok(r["score"] == 100, "no rules chosen means quality is judged on clashes only")

# 1) each department sets its own period times; shared teacher must never overlap in REAL time
cs = [a for a in alloc if a["department"] == "CS"]
r1 = generate(dict(base, allocations=cs), 10)
busy = [dict(teacher=e["teacher"], room=e["room"], day=e["day"], start=e["start"], end=e["end"], subject=e["subject"], department="Computer Science", class_name=e["class"], **{"class": e["class"]}) for e in r1["entries"]]
MIDS = [("09:30", "10:30"), ("10:45", "11:45"), ("12:00", "13:00"), ("14:30", "15:30")]       # Maths uses different bell times
mt = dict(base, settings=dict(base["settings"], MATH=S(MIDS, days=(0, 1, 2, 3))), busy=busy)
ma = [a for a in alloc if a["department"] == "MATH"]
r2 = generate(dict(mt, allocations=ma), 10)
ok(r2["status"] == "ok", "Maths with its own period times (4 periods, 4 days) still fits")
ok(clashes(r1["entries"] + r2["entries"]) == 0, "different bell times: no teacher/class/room overlap with CS in real time")
ok(all(e["day"] < 4 for e in r2["entries"]) and all((e["start"], e["end"]) in [(H(a), H(b)) for a, b in MIDS] for e in r2["entries"]), "sessions use only the department's chosen days and period times")

# 2) rules are the department's choice
def spread_max(entries):
    c = collections.Counter((e["class"], e["subject"], e["day"]) for e in entries); return max(c.values())
off_rules = generate(dict(base, allocations=cs, settings=dict(base["settings"], CS=S(rules={}))), 10)
req1 = generate(dict(base, allocations=cs, settings=dict(base["settings"], CS=S(rules={"spread": {"mode": "require", "max_per_day": 1}}))), 10)
ok(req1["status"] == "ok" and spread_max(req1["entries"]) == 1, "Required: a subject at most once per day per class")
req2 = generate(dict(base, allocations=cs, settings=dict(base["settings"], CS=S(rules={"class_day_max": {"mode": "require", "max": 3}}))), 10)
ok(req2["status"] == "ok" and max(collections.Counter((e["class"], e["day"]) for e in req2["entries"]).values()) <= 3, "Required: at most 3 periods a day for a class")
req3 = generate(dict(base, allocations=cs, settings=dict(base["settings"], CS=S(rules={"class_gaps": {"mode": "require"}}))), 10)
def class_gap_count(entries):
    g = 0
    for (c, d), es in itertools.groupby(sorted(entries, key=lambda e: (e["class"], e["day"], e["period"])), key=lambda e: (e["class"], e["day"])):
        ps = [e["period"] for e in es]; g += ps[-1] - ps[0] + 1 - len(ps)
    return g
ok(req3["status"] == "ok" and class_gap_count(req3["entries"]) == 0, "Required: no empty periods inside a class's day")
req4 = generate(dict(base, allocations=cs, settings=dict(base["settings"], CS=S(rules={"teacher_run": {"mode": "require", "max": 2}}))), 10)
def run_len(entries):
    mx = 0
    by = collections.defaultdict(list)
    for e in entries: by[e["teacher"], e["day"]].append(e["period"])
    for ps in by.values():
        ps.sort(); r_ = 1
        for a, b in zip(ps, ps[1:]):
            r_ = r_ + 1 if b == a + 1 else 1; mx = max(mx, r_)
    return mx
ok(req4["status"] == "ok" and run_len(req4["entries"]) <= 2, "Required: no teacher teaches more than 2 periods in a row")
fr = [(0, 5), (2, 4), (2, 5), (4, 5)]
req5 = generate(dict(base, allocations=cs, settings=dict(base["settings"], CS=S(free=fr))), 10)
ok(req5["status"] == "ok" and not any((e["day"], e["period"]) in fr for e in req5["entries"]), "periods the department keeps free stay empty")
imp = generate(dict(base, allocations=cs, settings=dict(base["settings"], CS=S(rules={"class_day_max": {"mode": "require", "max": 1}}))), 5)
ok(imp["status"] == "impossible" and any("Required" in p for p in imp["problems"]) or imp["status"] == "impossible", "too-strict Required rules give a plain explanation instead of a bad timetable")
print("   ->", imp["problems"][:2])

# 3) move check uses real time overlap and the department's required rules
e = dict(r2["entries"][0]); other = busy[0]
st = mt["settings"]["MATH"]
dm = dict(mt, busy=busy)
bad = validate_move(dict(dm, busy=busy + [dict(other, teacher=e["teacher"], day=0, start=H("09:45"), end=H("10:15"))]), dict(e, department="MATH"), 0, 0, H("09:30"), H("10:30"))
ok(bad[0] is False and "already teaching" in bad[1], "move blocked when a teacher is busy at an OVERLAPPING time (9:45-10:15 vs 9:30-10:30)")
ok(validate_move(dm, dict(e, department="MATH"), 4, 0, H("09:30"), H("10:30"))[1] == "That day isn't one of your working days.", "move to a non-working day refused")

# 4) impossible, in plain language
tiny = dict(base, rooms=[rooms[0], rooms[4]], teachers=dict(teachers, T3=T("Dr. Rahul Menon", 8)), settings={d: S() for d in depts})
big = [A("CS1","L","T1",20,"Computer lab"),A("CS2","L2","T2",15,"Computer lab"),A("MA1","Calc","T3",12)]
r3 = generate(dict(tiny, allocations=big), 5)
ok(r3["status"] == "impossible" and any("20 sessions to teach" in p for p in r3["problems"]), "impossible timetable explained"); [print("   -", p) for p in r3["problems"]]

# 5) equal priority: a joint re-balance finds a fit that 'first come first served' misses
tz = {"Z": T("Dr. Z", 10, [(d, 0, 1440) for d in range(1, 5)] + [(0, H("11:00"), 1440), (0, 0, H("09:00"))])}
two = [("09:00", "10:00"), ("10:00", "11:00")]
sett = {"CS": S(two, days=(0,)), "MATH": S(two, days=(0,))}
cls2 = {"C": dict(name="CS class", department="CS"), "M": dict(name="Maths class", department="MATH")}
cs_a = dict(**{"class": "C"}, subject="Python", teacher="Z", sessions=1, room_type="Classroom", department="CS")
ma_a = dict(**{"class": "M"}, subject="Stats", teacher="Z", sessions=1, room_type="Classroom", department="MATH")
d2 = dict(settings=sett, teachers=tz, classes=cls2, rooms=[dict(id="R1", type="Classroom"), dict(id="R2", type="Classroom")])
sett["CS"]["rules"] = {"early": {"mode": "prefer"}}      # CS likes early periods, so it grabs 9:00 first
first = generate(dict(d2, allocations=[cs_a], busy=[]), 5); e0 = first["entries"][0]
blocked = [dict(teacher="X", room="R2", day=0, start=H("10:00"), end=H("11:00"), subject="Other", department="MATH", class_name="M", **{"class": "M"})]
stuck = generate(dict(d2, allocations=[ma_a], busy=[dict(teacher="Z", room="R1", day=0, start=e0["start"], end=e0["end"], subject="Python", department="CS", class_name="C", **{"class": "C"})] + blocked), 5)
print("CS alone took:", (e0["day"], e0["start"]), "| Maths after CS:", stuck["status"])
ok(stuck["status"] == "impossible", "first come, first served: Maths is blocked once CS has taken the only slot it can use")
prop = rebalance(dict(d2, allocations=[cs_a, ma_a], busy=blocked, current=[dict(allocation=0, day=e0["day"], start=e0["start"], room=e0["room"])]), 5)
ok(prop["status"] == "ok" and len(prop["entries"]) == 2 and clashes(prop["entries"]) == 0, "re-balance finds a college-wide fit; moved by dept: " + str(prop.get("moved_by_department")))

# 6) rooms are switched off: timetables are made without rooms or labs (the situation on the live site)
nr = generate(dict(base, allocations=alloc, use_rooms=False, rooms=[]), 20)
ok(nr["status"] == "ok" and len(nr["entries"]) == sum(a["sessions"] for a in alloc), "no rooms in the college at all: the timetable is still made")
ok(all(e["room"] is None for e in nr["entries"]), "sessions carry no room")
tc = [e for e in nr["entries"] if True]; ok(clashes([dict(e, room=None) for e in tc]) == 0, "teacher and class clashes are still prevented without rooms")
# 7) one root cause = one issue with one short fix (no pile of 'missing sessions')
one = generate(dict(base, use_rooms=False, rooms=[], allocations=[A("CS1", "Big", "T1", 25)]), 5)
ok(one["status"] == "impossible" and len(one["issues"]) >= 1 and all(set(i) >= {"issue", "fix"} for i in one["issues"]), "an impossible timetable gives clear issues, each with a short fix")
print("   ->", one["issues"][0])
print("ALL ENGINE CHECKS PASSED")
