"""Tessellate scheduling engine (OR-Tools CP-SAT).

Deterministic and constraint-based: no LLM is involved in scheduling.

Each DEPARTMENT chooses its own days, period times (breaks are simply the gaps) and which optional rules apply.
Teachers, rooms and classes are shared, so clashes are detected by real TIME OVERLAP, not by slot number.
Always on, because without them a timetable would be invalid: no overlaps, every required session placed, teacher
availability, room type, teacher workload limit. Everything else is the department's choice (RULE_DEFS).

data = {
  settings:  {dept: {days:[0..6], periods:[{start,end} in minutes], rules:{name:{mode, <param>}}, free:[[day, period]]}},
  teachers:  {id: {name, max_load, existing_load, unavailable:[[day, start, end]]}},
  classes:   {id: {name, department}},   rooms: [{id, type}],
  allocations: [{class, subject, teacher, sessions, room_type, department}],
  busy:      [{teacher, room, class, day, start, end, subject, department, class_name}]   # sessions that must not move
  current:   [{allocation, day, start, room}]                                             # only used by rebalance()
}
"""
import os
from collections import defaultdict
from ortools.sat.python import cp_model

MODES3 = ["off", "prefer", "require"]
RULE_DEFS = {
    "spread": dict(title="Spread each subject across the week", modes=MODES3,
                   help="Limit how many sessions of one subject a class has on the same day.",
                   param=dict(key="max_per_day", label="Most sessions of one subject per day", default=1, min=1, max=6)),
    "class_day_max": dict(title="Limit a class's periods per day", modes=MODES3,
                          help="Stop any class from having too many periods in one day.",
                          param=dict(key="max", label="Most periods per day", default=6, min=1, max=12)),
    "teacher_run": dict(title="Limit continuous teaching", modes=MODES3,
                        help="Give teachers a free period after several periods in a row.",
                        param=dict(key="max", label="Most periods in a row", default=3, min=1, max=8)),
    "class_gaps": dict(title="No empty periods inside a class's day", modes=MODES3,
                       help="Keep each class's periods together, with no free period in the middle.", param=None),
    "teacher_gaps": dict(title="Reduce free periods between a teacher's classes", modes=MODES3,
                         help="Avoid long waits between a teacher's sessions on the same day.", param=None),
    "teacher_edges": dict(title="Keep teachers out of the first and last period", modes=MODES3,
                          help="Avoid very early starts and late finishes for teachers.", param=None),
    "balance": dict(title="Balance each teacher's load across the week", modes=["off", "prefer"],
                    help="Avoid one very heavy day for a teacher.", param=None),
    "early": dict(title="Fill the earliest periods first", modes=["off", "prefer"],
                  help="Pack sessions into the morning where possible.", param=None),
}
W = dict(fair=4, move=25, class_gap=6, teacher_gap=3, spread=40, class_day=20, teacher_peak=6, early=1, edge=3, teacher_run=8)
SUGGEST = ["Increase available periods", "Add another lab", "Change teacher availability",
           "Assign another faculty member", "Reduce conflicting requirements"]


def ov(a_s, a_e, b_s, b_e):
    return a_s < b_e and b_s < a_e


def rule(data, dept, name):
    r = ((data["settings"].get(dept) or {}).get("rules") or {}).get(name) or {}
    d = RULE_DEFS[name]
    mode = r.get("mode", "off")
    if mode not in d["modes"]:
        mode = "off"
    return mode, (r.get(d["param"]["key"], d["param"]["default"]) if d["param"] else None)


def grid(data, dept):
    st = data["settings"][dept]
    return [(d, p, per["start"], per["end"]) for d in st["days"] for p, per in enumerate(st["periods"])]


def _indexes(data):
    """Busy / unavailable time ranges per (resource, day)."""
    bt, br, bc, off = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for b in data.get("busy", []):
        bt[(b["teacher"], b["day"])].append((b["start"], b["end"]))
        br[(b["room"], b["day"])].append((b["start"], b["end"]))
        bc[(b["class"], b["day"])].append((b["start"], b["end"]))
    for t, T in data["teachers"].items():
        for d, s, e in T.get("unavailable", []):
            off[(t, d)].append((s, e))
    return bt, br, bc, off


hit = lambda lst, s, e: any(ov(s, e, a, b) for a, b in lst)  # noqa: E731


def issues(data):
    """Root causes only, each with ONE short fix. Only reports what is certainly impossible."""
    out = []
    bt, br, bc, off = _indexes(data)
    allocs = data["allocations"]
    use_rooms = data.get("use_rooms", True)
    t_need, c_need, r_need = defaultdict(int), defaultdict(int), defaultdict(int)
    t_depts = defaultdict(set)
    for a in allocs:
        t_need[a["teacher"]] += a["sessions"]
        c_need[a["class"]] += a["sessions"]
        r_need[a["room_type"]] += a["sessions"]
        t_depts[a["teacher"]].add(a["department"])

    def usable(dept, res_ranges):
        free = {tuple(f) for f in data["settings"][dept].get("free", [])}
        return [(d, p, s, e) for d, p, s, e in grid(data, dept) if (d, p) not in free and not res_ranges(d, s, e)]

    for t, need in t_need.items():
        T = data["teachers"][t]
        cap = sum(len(usable(dp, lambda d, s, e: hit(off[(t, d)], s, e) or hit(bt[(t, d)], s, e))) for dp in t_depts[t])
        cap = max(min(cap, T["max_load"] - T.get("existing_load", 0)), 0)
        if need > cap:
            out.append(dict(issue=f"{T['name']} has {need} sessions to teach but only {cap} free periods.",
                            fix="Give some of their subjects to another teacher, or add periods or days in Rules."))
    for c, need in c_need.items():
        dept = data["classes"][c]["department"]
        cap = len(usable(dept, lambda d, s, e: hit(bc[(c, d)], s, e)))
        if need > cap:
            out.append(dict(issue=f"{data['classes'][c]['name']} has {need} sessions a week but only {cap} free periods.",
                            fix="Reduce some weekly sessions, or add periods or days in Rules."))
    if use_rooms:
        for rt, need in r_need.items():
            rs = [r for r in data["rooms"] if r["type"] == rt]
            if not rs:
                out.append(dict(issue=f"No {rt.lower()} exists, but {need} sessions need one.", fix=f"Ask the College Registry to add a {rt.lower()}."))
                continue
            depts = {a["department"] for a in allocs if a["room_type"] == rt}
            cap = sum(len(usable(dp, lambda d, s, e: False)) for dp in depts) * len(rs)   # generous upper bound
            if rt != "Classroom" and need > cap:
                out.append(dict(issue=f"{rt}s are needed for {need} sessions but only about {cap} slots exist.", fix=f"Ask the College Registry to add another {rt.lower()}."))
    return out


def diagnose(data):
    return [i["issue"] for i in issues(data)]


def _impossible(items):
    return dict(status="impossible", entries=[], issues=items, problems=[i["issue"] for i in items],
                suggestions=list(dict.fromkeys(i["fix"] for i in items)))


def _atoms(m, items):
    """At most one of the variables may be used at any moment of time (works when period times differ)."""
    if len(items) < 2:
        return
    cuts = sorted({s for s, e, v in items} | {e for s, e, v in items})
    for a, b in zip(cuts, cuts[1:]):
        cover = [v for s, e, v in items if s <= a and b <= e]
        if len(cover) > 1:
            m.AddAtMostOne(cover)


def generate(data, time_limit=30, workers=None):
    """Return {status, entries, score, problems, suggestions}. Never returns an invalid timetable."""
    workers = workers or int(os.environ.get("SOLVER_WORKERS", "8"))   # set SOLVER_WORKERS=2 on a small server
    found = issues(data)
    if found:
        return _impossible(found)

    use_rooms = data.get("use_rooms", True)
    allocs = data["allocations"]
    rooms = data["rooms"] if use_rooms else [dict(id=None, type=None)]       # no rooms: one imaginary "no room" choice
    bt, br, bc, off = _indexes(data)
    m = cp_model.CpModel()
    x, info = {}, {}
    for i, a in enumerate(allocs):
        dept = a["department"]
        free = {tuple(f) for f in data["settings"][dept].get("free", [])}
        for d, p, s, e in grid(data, dept):
            if (d, p) in free or hit(off[(a["teacher"], d)], s, e) or hit(bt[(a["teacher"], d)], s, e) or hit(bc[(a["class"], d)], s, e):
                continue
            for r in rooms:
                if use_rooms and (r["type"] != a["room_type"] or hit(br[(r["id"], d)], s, e)):
                    continue
                x[i, d, p, r["id"]] = m.NewBoolVar(f"x{i}_{d}_{p}_{r['id']}")
                info[i, d, p, r["id"]] = (s, e)

    A, AD, TS, CS, ov_groups = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for (i, d, p, r), v in x.items():
        a, (s, e) = allocs[i], info[i, d, p, r]
        A[i].append(v)
        AD[i, d].append(v)
        TS[a["teacher"], a["department"], d, p].append(v)
        CS[a["class"], d, p].append(v)
        ov_groups["t", a["teacher"], d].append((s, e, v))
        if r is not None:
            ov_groups["r", r, d].append((s, e, v))
        ov_groups["c", a["class"], d].append((s, e, v))
    for i, a in enumerate(allocs):
        if not A[i]:
            return _impossible([dict(issue=f"{a['subject']} ({data['classes'][a['class']]['name']}) has no period where the teacher and the class are both free.",
                                     fix="Choose another teacher for this subject, or add periods or days in Rules.")])

    # ---- Always-on rules ----
    for i, a in enumerate(allocs):
        m.Add(sum(A[i]) == a["sessions"])
    for items in ov_groups.values():
        _atoms(m, items)
    load = defaultdict(list)
    for (i, d, p, r), v in x.items():
        load[allocs[i]["teacher"]].append(v)
    for t, vs in load.items():
        T = data["teachers"][t]
        m.Add(sum(vs) + T.get("existing_load", 0) <= T["max_load"])

    # ---- Rules the department chose ----
    pen, dpen = [], defaultdict(list)

    def add(expr, dept):
        pen.append(expr)
        dpen[dept].append(expr)

    def limit(vs, mx, mode, weight, dept):           # sum(vs) <= mx, either required or preferred
        if len(vs) <= mx:
            return
        if mode == "require":
            m.Add(sum(vs) <= mx)
        else:
            ex = m.NewIntVar(0, len(vs), "")
            m.Add(ex >= sum(vs) - mx)
            add(weight * ex, dept)

    for (i, d), vs in AD.items():
        dept = allocs[i]["department"]
        mode, mx = rule(data, dept, "spread")
        if mode != "off":
            limit(vs, mx, mode, W["spread"], dept)
    class_days = defaultdict(list)
    for (c, d, p), vs in CS.items():
        class_days[c, d] += vs
    for (c, d), vs in class_days.items():
        dept = data["classes"][c]["department"]
        mode, mx = rule(data, dept, "class_day_max")
        if mode != "off":
            limit(vs, mx, mode, W["class_day"], dept)

    for (t, dept, d) in {(k[0], k[1], k[2]) for k in TS}:
        n = len(data["settings"][dept]["periods"])
        mode, mx = rule(data, dept, "teacher_run")
        if mode != "off":
            for s0 in range(max(n - mx, 0)):
                limit([v for p in range(s0, s0 + mx + 1) for v in TS.get((t, dept, d, p), [])], mx, mode, W["teacher_run"], dept)

    def gaps(occ_of, n, mode, weight, dept):          # idle periods between a day's first and last session
        occ = [sum(occ_of(p)) if occ_of(p) else 0 for p in range(n)]
        if sum(1 for o in occ if not isinstance(o, int)) < 2:
            return
        pre, post = [m.NewBoolVar("") for _ in occ], [m.NewBoolVar("") for _ in occ]
        for q in range(1, n):
            m.Add(pre[q] >= pre[q - 1]); m.Add(pre[q] >= occ[q - 1])
        for q in range(n - 2, -1, -1):
            m.Add(post[q] >= post[q + 1]); m.Add(post[q] >= occ[q + 1])
        for q in range(1, n - 1):
            hole = m.NewBoolVar("")
            m.Add(hole >= pre[q] + post[q] - 1 - occ[q])
            if mode == "require":
                m.Add(hole == 0)
            else:
                add(weight * hole, dept)

    for c, d in {(k[0], k[1]) for k in CS}:
        dept = data["classes"][c]["department"]
        mode, _ = rule(data, dept, "class_gaps")
        if mode != "off":
            gaps(lambda p: CS.get((c, d, p), []), len(data["settings"][dept]["periods"]), mode, W["class_gap"], dept)
    for (t, dept, d) in {(k[0], k[1], k[2]) for k in TS}:
        mode, _ = rule(data, dept, "teacher_gaps")
        if mode != "off":
            gaps(lambda p: TS.get((t, dept, d, p), []), len(data["settings"][dept]["periods"]), mode, W["teacher_gap"], dept)

    peak_vars = defaultdict(list)
    for (i, d, p, r), v in x.items():
        a = allocs[i]; dept = a["department"]; n = len(data["settings"][dept]["periods"])
        mode, _ = rule(data, dept, "teacher_edges")
        if mode != "off" and n > 2 and p in (0, n - 1):
            if mode == "require":
                m.Add(v == 0)
            else:
                add(W["edge"] * v, dept)
        if rule(data, dept, "balance")[0] == "prefer":
            peak_vars[a["teacher"], d].append(v)
        if rule(data, dept, "early")[0] == "prefer":
            add(W["early"] * p * v, dept)
    for t in {k[0] for k in peak_vars}:
        peak = m.NewIntVar(0, 40, "")
        for (t2, d), vs in peak_vars.items():
            if t2 == t:
                m.Add(peak >= sum(vs))
        pen.append(W["teacher_peak"] * peak)

    # ---- Fairness: no department is favoured; minimise the worst department's penalty too ----
    deps = [k for k in dpen if k is not None]
    if len(deps) > 1:
        worst = m.NewIntVar(0, 100_000, "")
        for k in deps:
            m.Add(worst >= sum(dpen[k]))
        pen.append(W["fair"] * worst)
    # ---- Stability (rebalance only): prefer to keep sessions where they are ----
    keep = defaultdict(set)
    for c in data.get("current", []):
        keep[c["allocation"]].add((c["day"], c["start"], c["room"]))
    for i, a in enumerate(allocs):
        if i in keep:
            kept = sum(v for (j, d, p, r), v in x.items() if j == i and (d, info[j, d, p, r][0], r) in keep[i])
            pen.append(W["move"] * (a["sessions"] - kept))

    m.Minimize(sum(pen))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = time_limit
    sv.parameters.random_seed = 1
    sv.parameters.num_workers = workers
    st = sv.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        required = sorted({RULE_DEFS[n]["title"] for dp in {a["department"] for a in allocs} for n in RULE_DEFS if rule(data, dp, n)[0] == "require"})
        if required:
            return _impossible([dict(issue="Your Required rules are too strict, so the sessions can't all fit: " + "; ".join(required) + ".",
                                     fix="Change one of these rules from Always required to Prefer when possible in Rules.")])
        return _impossible([dict(issue="These sessions can't all fit without clashing with other departments' timetables.",
                                 fix="Ask the other department to move a session, or add periods or days in Rules.", alt=True)])
    entries = []
    for (i, d, p, r), v in x.items():
        if sv.Value(v):
            a, (s, e) = allocs[i], info[i, d, p, r]
            entries.append(dict(allocation=i, department=a["department"], day=d, period=p, start=s, end=e, room=r,
                                **{"class": a["class"], "subject": a["subject"], "teacher": a["teacher"]}))
    return dict(status="ok", entries=entries, score=quality(entries, data), problems=[], suggestions=[],
                rules_used=sum(1 for dp in {a["department"] for a in allocs} for n in RULE_DEFS if rule(data, dp, n)[0] != "off"),
                optimal=st == cp_model.OPTIMAL)


def quality(entries, data):
    """0-100, measured only against the rules the department turned on. No rules chosen -> 100 (no clashes)."""
    if not entries:
        return 0
    pen, used = 0.0, False
    by_t, by_c = defaultdict(list), defaultdict(list)
    for e in entries:
        by_t[e["teacher"], e["department"], e["day"]].append(e["period"])
        by_c[e["class"], e["day"]].append(e)
    for (t, dept, d), ps in by_t.items():
        ps.sort()
        n = len(data["settings"][dept]["periods"])
        if rule(data, dept, "teacher_gaps")[0] != "off":
            used = True; pen += (ps[-1] - ps[0] + 1 - len(ps)) * 1.5
        mode, mx = rule(data, dept, "teacher_run")
        if mode != "off":
            used = True; run = 1
            for a, b in zip(ps, ps[1:]):
                run = run + 1 if b == a + 1 else 1
                if run > mx:
                    pen += 4
        if rule(data, dept, "teacher_edges")[0] != "off" and n > 2:
            used = True; pen += sum(1 for p in ps if p in (0, n - 1))
    for (c, d), es in by_c.items():
        dept = es[0]["department"]
        ps = sorted(e["period"] for e in es)
        if rule(data, dept, "class_gaps")[0] != "off":
            used = True; pen += (ps[-1] - ps[0] + 1 - len(ps)) * 3
        mode, mx = rule(data, dept, "spread")
        if mode != "off":
            used = True
            subs = [e["subject"] for e in es]
            pen += sum(1.5 * (subs.count(s) - mx) for s in set(subs) if subs.count(s) > mx)
        mode, mx = rule(data, dept, "class_day_max")
        if mode != "off":
            used = True; pen += max(0, len(es) - mx) * 2
    for e in entries:
        if rule(data, e["department"], "early")[0] != "off":
            used = True; pen += 0.3 * e["period"]
    if not used:
        return 100
    return max(40, min(100, round(100 - pen / len(entries) * 55)))


def validate_move(data, entry, day, period, start, end):
    """Instant check for a manual move. `data['busy']` holds EVERY other placed session in the college
    (not the one being moved). `entry` needs: class, teacher, room, subject, department."""
    here = [b for b in data["busy"] if b["day"] == day and ov(start, end, b["start"], b["end"])]
    T = data["teachers"][entry["teacher"]]
    for b in here:
        if b["teacher"] == entry["teacher"]:
            return False, f"{T['name']} is already teaching {b.get('department', 'another class')} · {b.get('subject', '')} at that time."
    for b in here:
        if b["class"] == entry["class"]:
            return False, "This class already has another subject at that time."
    if any(d == day and ov(start, end, s, e) for d, s, e in T.get("unavailable", [])):
        return False, f"{T['name']} is not available at that time."
    st = data.get("settings", {}).get(entry["department"])
    if st:
        if day not in st["days"]:
            return False, "That day isn't one of your working days."
        if [day, period] in [list(f) for f in st.get("free", [])]:
            return False, "You chose to keep that period free."
        same_day = [b for b in data["busy"] if b["day"] == day and b["class"] == entry["class"]]
        mode, mx = rule(data, entry["department"], "spread")
        if mode == "require" and sum(1 for b in same_day if b["subject"] == entry["subject"]) + 1 > mx:
            return False, f"Your rule allows at most {mx} session(s) of {entry['subject']} per day for a class."
        mode, mx = rule(data, entry["department"], "class_day_max")
        if mode == "require" and len(same_day) + 1 > mx:
            return False, f"Your rule allows at most {mx} periods per day for a class."
    taken = {b["room"] for b in here if b["room"] is not None}
    if data.get("use_rooms", True) and entry["room"] in taken:
        kind = next(r["type"] for r in data["rooms"] if r["id"] == entry["room"])
        if not any(r["type"] == kind and r["id"] not in taken for r in data["rooms"]):
            return False, "Every suitable room is already being used at that time."
    return True, "Move allowed."


def rebalance(data, time_limit=30):
    """Proposal only. Solve ALL departments together (`data['busy']` empty, `data['current']` = what exists now).
    Existing sessions stay put unless moving them lets the whole college fit or score better. Nothing is applied here."""
    r = generate(data, time_limit)
    if r["status"] != "ok":
        return r
    now = {(c["allocation"], c["day"], c["start"]) for c in data.get("current", [])}
    moved = [e for e in r["entries"] if (e["allocation"], e["day"], e["start"]) not in now]
    by_dept = defaultdict(int)
    for e in moved:
        by_dept[data["allocations"][e["allocation"]].get("department")] += 1
    r["moved"], r["moved_by_department"] = moved, dict(by_dept)
    return r
