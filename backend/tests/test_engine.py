import sys, time, collections
sys.path.insert(0, "..")
from engine.solver import generate, validate_move, rebalance

T = lambda n, mx, un=(): dict(name=n, max_load=mx, unavailable=[list(u) for u in un])
teachers = {"T1": T("Dr. Anil Kumar", 18), "T2": T("Prof. Meera Nair", 16), "T3": T("Dr. Rahul Menon", 22),
            "T4": T("Ms. Sana Iqbal", 18), "T5": T("Mr. Joseph Thomas", 16, [(4, p) for p in range(6)]),
            "T6": T("Dr. Lakshmi Rao", 16, [(2, 4), (2, 5)]), "T7": T("Mr. Kiran Das", 18), "T8": T("Ms. Divya Pillai", 16)}
classes = {c: dict(name=c) for c in ["CS1", "CS2", "BCA1", "MA1", "COM1", "PHY1"]}
rooms = [dict(id=i, type="Classroom") for i in ["R101", "R102", "R103", "R104"]] + \
        [dict(id="L1", type="Computer lab"), dict(id="L2", type="Computer lab"), dict(id="PL", type="Laboratory")]
def A(c, s, t, n, rt="Classroom"): return dict(**{"class": c}, subject=s, teacher=t, sessions=n, room_type=rt)
alloc = [A("CS1","Python","T1",3),A("CS1","Mathematics","T3",4),A("CS1","DBMS","T2",3),A("CS1","English","T4",3),A("CS1","Python Lab","T1",2,"Computer lab"),
 A("CS2","DBMS","T2",3),A("CS2","Data Structures","T2",4),A("CS2","Statistics","T3",3),A("CS2","English","T4",2),A("CS2","DS Lab","T2",2,"Computer lab"),
 A("BCA1","Programming","T1",3),A("BCA1","Mathematics","T3",3),A("BCA1","Web Tech","T8",3),A("BCA1","English","T4",3),A("BCA1","Programming Lab","T8",2,"Computer lab"),
 A("MA1","Mathematics","T1",4),A("MA1","Calculus","T3",3),A("MA1","Algebra","T5",4),A("MA1","English","T4",2),
 A("COM1","Accounting","T6",4),A("COM1","Business Law","T5",3),A("COM1","Economics","T6",3),A("COM1","English","T4",3),A("COM1","Statistics","T3",2),
 A("PHY1","Mechanics","T7",4),A("PHY1","Optics","T7",3),A("PHY1","Physics Lab","T7",2,"Laboratory"),A("PHY1","English","T4",2),A("PHY1","Mathematics","T3",3)]
cfg = dict(days=5, periods=6)
base = dict(config=cfg, teachers=teachers, classes=classes, rooms=rooms, busy=[])

# 1) whole college at once
t0 = time.time(); r = generate(dict(base, allocations=alloc), 20)
print("college:", r["status"], "score", r.get("score"), "sessions", len(r["entries"]), f"{time.time()-t0:.1f}s")
for k in [("teacher","day","period"),("class","day","period"),("room","day","period")]:
    c = collections.Counter(tuple(e[x] for x in k) for e in r["entries"]); assert max(c.values()) == 1, k
assert len(r["entries"]) == sum(a["sessions"] for a in alloc)
print("no overlaps; every required session placed")

# 2) incremental: CS first, then Maths sees CS as busy
cs = [a for a in alloc if a["class"] in ("CS1","CS2")]
r1 = generate(dict(base, allocations=cs), 10)
busy = [dict(teacher=e["teacher"], room=e["room"], **{"class": e["class"]}, day=e["day"], period=e["period"],
             subject=e["subject"], department="Computer Science") for e in r1["entries"]]
ma = [a for a in alloc if a["class"] == "MA1"]
r2 = generate(dict(base, allocations=ma, busy=busy), 10)
used = {(b["teacher"], b["day"], b["period"]) for b in busy}
assert all((e["teacher"], e["day"], e["period"]) not in used for e in r2["entries"]); print("incremental:", r2["status"], r2["score"], "- no clash with CS")

# 3) manual move check
e = dict(r2["entries"][0]); t1 = next(b for b in busy if b["teacher"] == e["teacher"])
print("move:", validate_move(dict(base, busy=busy), e, t1["day"], t1["period"]))

# 4) impossible: Lab 1 only, 3 lab classes needing more lab slots than exist
tiny = dict(base, rooms=[rooms[0], rooms[4]], teachers=dict(teachers, T3=T("Dr. Rahul Menon", 8)))
r3 = generate(dict(tiny, allocations=[A("CS1","L","T1",20,"Computer lab"),A("CS2","L2","T2",15,"Computer lab"),A("MA1","Calc","T3",12)]), 5)
print("impossible:", r3["status"]); [print(" -", p) for p in r3["problems"]]

# 5) equal priority: CS placed first must NOT permanently block Maths. A joint re-balance finds the fit.
tz = {"Z": T("Dr. Z", 10, [(d, p) for d in range(5) for p in range(6) if (d, p) not in [(0, 0), (0, 1)]])}  # free only Mon P1, Mon P2
cfg2 = dict(config=cfg, teachers=tz, rooms=[dict(id="R1", type="Classroom"), dict(id="R2", type="Classroom")])
cls2 = {"C": dict(name="CS class", department="CS"), "M": dict(name="Maths class", department="MATH")}
cs_a = dict(**{"class": "C"}, subject="Python", teacher="Z", sessions=1, room_type="Classroom", department="CS")
ma_a = dict(**{"class": "M"}, subject="Stats", teacher="Z", sessions=1, room_type="Classroom", department="MATH")
first = generate(dict(cfg2, classes=cls2, allocations=[cs_a], busy=[]), 5)
e0 = first["entries"][0]; print("CS alone took:", (e0["day"], e0["period"]))
# Maths class can only attend Mon P1 (its other periods are taken by other sessions that cannot move)
blocked = [dict(teacher="X", room="R2", day=0, period=0, subject="Other", department="MATH", **{"class": "M"})]
stuck = generate(dict(cfg2, classes=cls2, allocations=[ma_a], busy=[dict(teacher="Z", room="R1", day=e0["day"], period=e0["period"], subject="Python", department="CS", **{"class": "C"})] + blocked), 5)
print("Maths after CS:", stuck["status"])
cur = [dict(e0)]
prop = rebalance(dict(cfg2, classes=cls2, allocations=[cs_a, ma_a], busy=blocked, current=cur), 5)
print("re-balance:", prop["status"], "moved by dept:", prop.get("moved_by_department"))
assert prop["status"] == "ok" and len(prop["entries"]) == 2
