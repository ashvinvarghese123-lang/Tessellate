"""Tessellate scheduling engine (OR-Tools CP-SAT).

Deterministic and constraint-based: no LLM is involved in scheduling.
Input/output are plain dicts so the engine can run behind any API.

Incremental generation: pass `busy` (sessions already placed by OTHER
departments, or kept from this one). They block teachers, rooms and classes
but are never changed.
"""
from collections import defaultdict
from ortools.sat.python import cp_model

# Soft-constraint weights: higher = more important.
W = dict(fair=4, move=25, class_gap=6, teacher_gap=3, same_day=40, teacher_peak=6, late=1, edge=3, teacher_run=8)


def _slots(cfg):
    return [(d, p) for d in range(cfg["days"]) for p in range(cfg["periods"])]


def diagnose(data):
    """Plain-language reasons a timetable cannot exist (cheap necessary checks)."""
    cfg, out = data["config"], []
    slots = _slots(cfg)
    busy = defaultdict(set)
    for b in data.get("busy", []):
        busy[("t", b["teacher"])].add((b["day"], b["period"]))
        busy[("r", b["room"])].add((b["day"], b["period"]))
        busy[("c", b["class"])].add((b["day"], b["period"]))
    t_dem, c_dem, r_dem = defaultdict(int), defaultdict(int), defaultdict(int)
    for a in data["allocations"]:
        t_dem[a["teacher"]] += a["sessions"]
        c_dem[a["class"]] += a["sessions"]
        if a.get("room_type") != "Classroom":
            r_dem[a["room_type"]] += a["sessions"]
    for t, need in t_dem.items():
        T = data["teachers"][t]
        free = [s for s in slots if s not in set(map(tuple, T.get("unavailable", []))) and s not in busy[("t", t)]]
        cap = min(len(free), T["max_load"] - T.get("existing_load", 0))
        if need > cap:
            out.append(f"{T['name']} needs {need} sessions, but only {cap} suitable periods are available.")
    for c, need in c_dem.items():
        free = len([s for s in slots if s not in busy[("c", c)]])
        if need > free:
            out.append(f"{data['classes'][c]['name']} needs {need} sessions but has only {free} free periods.")
    for rt, need in r_dem.items():
        n = len([r for r in data["rooms"] if r["type"] == rt])
        cap = n * len(slots) - sum(len(v) for k, v in busy.items() if k[0] == "r" and
                                   any(r["id"] == k[1] and r["type"] == rt for r in data["rooms"]))
        if need > cap:
            out.append(f"{rt}s are needed for {need} sessions but only {cap} slots exist. Add another {rt.lower()}.")
    return out


def generate(data, time_limit=30, workers=None):
    """Return {status, entries, score, problems}. Never returns an invalid timetable."""
    workers = workers or int(__import__("os").environ.get("SOLVER_WORKERS", "8"))   # set SOLVER_WORKERS=2 on a small server
    cfg = data["config"]
    slots = _slots(cfg)
    probs = diagnose(data)
    if probs:
        return dict(status="impossible", entries=[], problems=probs, suggestions=SUGGEST)

    m = cp_model.CpModel()
    rooms = data["rooms"]
    busy_t, busy_r, busy_c = set(), set(), set()
    for b in data.get("busy", []):
        busy_t.add((b["teacher"], b["day"], b["period"]))
        busy_r.add((b["room"], b["day"], b["period"]))
        busy_c.add((b["class"], b["day"], b["period"]))

    x = {}  # (alloc idx, day, period, room) -> BoolVar
    for i, a in enumerate(data["allocations"]):
        T = data["teachers"][a["teacher"]]
        off = set(map(tuple, T.get("unavailable", [])))
        for d, p in slots:
            if (d, p) in off or (a["teacher"], d, p) in busy_t or (a["class"], d, p) in busy_c:
                continue
            for r in rooms:
                if r["type"] != a["room_type"] and not (a["room_type"] == "Classroom" and r["type"] == "Classroom"):
                    continue
                if (r["id"], d, p) in busy_r:
                    continue
                x[i, d, p, r["id"]] = m.NewBoolVar(f"x{i}_{d}_{p}_{r['id']}")

    A, TS, CS, RS = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for (i, d, p, r), v in x.items():
        a = data["allocations"][i]
        A[i].append(v)
        TS[a["teacher"], d, p].append(v)
        CS[a["class"], d, p].append(v)
        RS[r, d, p].append(v)

    # ---- Hard constraints ----
    for i, a in enumerate(data["allocations"]):
        m.Add(sum(A[i]) == a["sessions"])          # exactly the required sessions
    for g in (TS, CS, RS):
        for vs in g.values():
            m.AddAtMostOne(vs)                     # no teacher / class / room overlap
    load = defaultdict(list)
    for (t, d, p), vs in TS.items():
        load[t] += vs
    for t, vs in load.items():                     # workload limit, counting other departments
        T = data["teachers"][t]
        m.Add(sum(vs) + T.get("existing_load", 0) <= T["max_load"])

    # ---- Soft constraints ----
    pen = []
    dpen = defaultdict(list)   # penalty per department, used for fairness
    # same subject at most once a day
    for i, a in enumerate(data["allocations"]):
        for d in range(cfg["days"]):
            vs = [v for (j, dd, p, r), v in x.items() if j == i and dd == d]
            if vs:
                ex = m.NewIntVar(0, a["sessions"], "")
                m.Add(ex >= sum(vs) - 1)
                pen.append(W["same_day"] * ex)
                dpen[a.get("department")].append(W["same_day"] * ex)
    # teacher: balance days, avoid first/last period, avoid long runs
    for t in {a["teacher"] for a in data["allocations"]}:
        peak = m.NewIntVar(0, cfg["periods"], "")
        for d in range(cfg["days"]):
            day = [v for p in range(cfg["periods"]) for v in TS.get((t, d, p), [])]
            if day:
                m.Add(peak >= sum(day))
            for s in range(cfg["periods"] - 3):    # 4 consecutive periods = too long
                w = [v for p in range(s, s + 4) for v in TS.get((t, d, p), [])]
                if len(w) > 3:
                    ex = m.NewIntVar(0, 1, "")
                    m.Add(sum(w) <= 3 + ex)
                    pen.append(W["teacher_run"] * ex)
            for p in (0, cfg["periods"] - 1):
                pen.extend(W["edge"] * v for v in TS.get((t, d, p), []))
        pen.append(W["teacher_peak"] * peak)
    # gaps (idle periods between first and last session) for classes and teachers
    gap_groups = [(CS, W["class_gap"]), (TS, W["teacher_gap"])]
    for g, w in gap_groups:
        for ent in {k[0] for k in g}:
            for d in range(cfg["days"]):
                occ = [sum(g.get((ent, d, p), [])) for p in range(cfg["periods"])]
                pre = [m.NewBoolVar("") for _ in occ]
                post = [m.NewBoolVar("") for _ in occ]
                for q in range(1, len(occ)):
                    m.Add(pre[q] >= pre[q - 1]); m.Add(pre[q] >= occ[q - 1])
                for q in range(len(occ) - 2, -1, -1):
                    m.Add(post[q] >= post[q + 1]); m.Add(post[q] >= occ[q + 1])
                for q in range(1, len(occ) - 1):
                    hole = m.NewBoolVar("")
                    m.Add(hole >= pre[q] + post[q] - 1 - occ[q])
                    pen.append(w * hole)
                    if g is CS:
                        dpen[data["classes"][ent].get("department")].append(w * hole)
    # students: compact days (later periods cost slightly more)
    for (i, d, p, r), v in x.items():
        pen.append(W["late"] * p * v)
        dpen[data["allocations"][i].get("department")].append(W["late"] * p * v)

    # Fairness: no department is favoured. Minimise the WORST department's penalty as well as the total.
    deps = [k for k in dpen if k is not None]
    if len(deps) > 1:
        worst = m.NewIntVar(0, 10_000, "")
        for k in deps:
            m.Add(worst >= sum(dpen[k]))
        pen.append(W["fair"] * worst)
    # Stability (used when re-balancing): prefer to keep sessions where they already are.
    keep_pos = defaultdict(set)
    for c in data.get("current", []):
        keep_pos[c["allocation"]].add((c["day"], c["period"], c["room"]))
    for i, a in enumerate(data["allocations"]):
        if i in keep_pos:
            kept = sum(v for (j, d, p, r), v in x.items() if j == i and (d, p, r) in keep_pos[i])
            pen.append(W["move"] * (a["sessions"] - kept))
    m.Minimize(sum(pen))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.random_seed = 1                   # deterministic
    s.parameters.num_workers = workers  # use workers=1 for bit-for-bit reproducible runs
    st = s.Solve(m)

    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return dict(status="impossible", entries=[], problems=[
            "We couldn't fit every required session without a clash with the current settings."],
            suggestions=SUGGEST)
    entries = [dict(allocation=i, **{k: data["allocations"][i][k] for k in ("class", "subject", "teacher")},
                    day=d, period=p, room=r)
               for (i, d, p, r), v in x.items() if s.Value(v)]
    return dict(status="ok", entries=entries, score=quality(entries, data), problems=[], suggestions=[],
                optimal=st == cp_model.OPTIMAL)


def quality(entries, data):
    """0-100 score from the same soft criteria, measured on the finished timetable."""
    if not entries:
        return 0
    pen = 0
    by = defaultdict(list)
    for e in entries:
        by[("t", e["teacher"], e["day"])].append(e["period"])
        by[("c", e["class"], e["day"])].append((e["period"], e["subject"]))
    for k, v in by.items():
        if k[0] == "t":
            ps = sorted(v)
            pen += (ps[-1] - ps[0] + 1 - len(ps)) * 1.5 if len(ps) > 1 else 0
        else:
            ps = sorted(p for p, _ in v)
            pen += (ps[-1] - ps[0] + 1 - len(ps)) * 3 if len(ps) > 1 else 0
            subs = [s for _, s in v]
            pen += sum(1.5 for s in subs if subs.count(s) > 1)
    return max(60, min(99, round(100 - pen / len(entries) * 55)))


def validate_move(data, entry, day, period):
    """Instant check for a manual drag/drop.
    `data['busy']` must hold EVERY other placed session in the college (not the one being moved).
    `entry` needs: class, teacher, room."""
    here = [b for b in data["busy"] if b["day"] == day and b["period"] == period]
    name = data["teachers"][entry["teacher"]]["name"]
    for b in here:
        if b["teacher"] == entry["teacher"]:
            return False, f"{name} is already teaching {b.get('department', 'another class')} · {b.get('subject', '')} at that time."
    for b in here:
        if b["class"] == entry["class"]:
            return False, "This class already has another subject at that time."
    if [day, period] in data["teachers"][entry["teacher"]].get("unavailable", []):
        return False, f"{name} is not available at that time."
    taken = {b["room"] for b in here}
    if entry["room"] in taken:
        kind = next(r["type"] for r in data["rooms"] if r["id"] == entry["room"])
        if not any(r["type"] == kind and r["id"] not in taken for r in data["rooms"]):
            return False, "Every suitable room is already being used at that time."
    return True, "Move allowed."


SUGGEST = ["Increase available periods", "Add another lab", "Change teacher availability",
           "Assign another faculty member", "Reduce conflicting requirements"]


def rebalance(data, time_limit=30):
    """Proposal only. Solve ALL departments together (`data['busy']` empty, `data['current']` = what exists now).
    Existing sessions stay put unless moving them lets the whole college fit or score better.
    Nothing is applied here: every department must see the proposal first."""
    r = generate(data, time_limit)
    if r["status"] != "ok":
        return r
    now = {(c["allocation"], c["day"], c["period"]) for c in data.get("current", [])}
    moved = [e for e in r["entries"] if (e["allocation"], e["day"], e["period"]) not in now]
    by_dept = defaultdict(int)
    for e in moved:
        by_dept[data["allocations"][e["allocation"]].get("department")] += 1
    r["moved"], r["moved_by_department"] = moved, dict(by_dept)
    return r
