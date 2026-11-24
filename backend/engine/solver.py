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
    bt, br, bc, off, bs_stu = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for b in data.get("busy", []):
        if b.get("teacher") is not None:
            bt[(b["teacher"], b["day"])].append((b["start"], b["end"]))
        if b.get("room") is not None:
            br[(b["room"], b["day"])].append((b["start"], b["end"]))
        if b.get("class") is not None:
            bc[(b["class"], b["day"])].append((b["start"], b["end"]))
        for sid in b.get("student_ids", []):
            bs_stu[(sid, b["day"])].append((b["start"], b["end"], b.get("subject", "another course")))
    for t, T in data["teachers"].items():
        for d, s, e in T.get("unavailable", []):
            off[(t, d)].append((s, e))
    return bt, br, bc, off, bs_stu


hit = lambda lst, s, e: any(ov(s, e, a, b) for a, b in lst)  # noqa: E731


def slot_matches_common(d, s, e, common_slots, ctype):
    for cs in common_slots:
        if cs["day"] == d and cs["start"] == s and cs["end"] == e:
            if cs.get("course_type") in (ctype, "Both", None):
                return True
    return False


def issues(data):
    """Root causes only, each with ONE short fix. Only reports what is certainly impossible."""
    out = []
    bt, br, bc, off, bs_stu = _indexes(data)
    allocs = data["allocations"]
    use_rooms = data.get("use_rooms", True)
    common_slots = data.get("common_slots", [])
    t_need, c_need, r_need = defaultdict(int), defaultdict(int), defaultdict(int)
    t_depts = defaultdict(set)
    for a in allocs:
        if a.get("teacher") is not None:
            t_need[a["teacher"]] += a["sessions"]
            t_depts[a["teacher"]].add(a["department"])
        if a.get("class") is not None:
            c_need[a["class"]] += a["sessions"]
        if a.get("room_type") is not None:
            r_need[a["room_type"]] += a["sessions"]

        # College-wide common slot check (for Student-Selected MDC/Minor offerings)
        if a.get("scope") == "college_wide" or a.get("selection_type") == "STUDENT_SELECTED":
            ctype = a.get("course_type", "MDC")
            matching = [cs for cs in common_slots if cs.get("course_type") in (ctype, "Both", None)]
            if not matching:
                out.append(dict(
                    issue=f"No college-wide common time slot configured for {ctype} ({a.get('code', a['subject'])}).",
                    fix=f"Ask the College Registry to configure common time slots for {ctype}."
                ))
            elif len(matching) < a["sessions"]:
                out.append(dict(
                    issue=f"Only {len(matching)} common slot(s) exist for {ctype}, but {a.get('code', a['subject'])} requires {a['sessions']} sessions.",
                    fix=f"Add more common {ctype} time slots or reduce required weekly sessions."
                ))

        # Capacity check for course offerings
        if a.get("kind") == "offering":
            cap = a.get("capacity") or a.get("max_enrollment", 60)
            enrolled_count = len(a.get("enrolled_students", []))
            if enrolled_count > cap:
                out.append(dict(
                    issue=f"{a.get('code', a['subject'])} enrollment ({enrolled_count}) exceeds section capacity ({cap}).",
                    fix="Add another course section in Offerings or raise section capacity."
                ))

    def usable(dept, res_ranges):
        free = {tuple(f) for f in data["settings"][dept].get("free", [])}
        return [(d, p, s, e) for d, p, s, e in grid(data, dept) if (d, p) not in free and not res_ranges(d, s, e)]

    for t, need in t_need.items():
        T = data["teachers"][t]
        free = sum(len(usable(dp, lambda d, s, e: hit(off[(t, d)], s, e) or hit(bt[(t, d)], s, e))) for dp in t_depts[t])
        limit = max(T["max_load"] - T.get("existing_load", 0), 0)          # weekly limit minus sessions they already have elsewhere
        if need > min(free, limit):
            if limit < free:
                out.append(dict(issue=f"{T['name']} has {need} sessions to teach but can only teach {limit} more this week (weekly limit {T['max_load']}).",
                                fix="Raise their weekly limit in Faculty, or give some of their subjects to another teacher.",
                                type="teacher_capacity", teacher_id=t, teacher_name=T["name"],
                                faculty_code=T.get("code") or "FAC", can_fix_internally=True))
            else:
                out.append(dict(issue=f"{T['name']} has {need} sessions to teach but only {free} free periods.",
                                fix="Give some subjects to another teacher, mark fewer periods unavailable, or add periods or days in Rules.",
                                type="teacher_capacity", teacher_id=t, teacher_name=T["name"],
                                faculty_code=T.get("code") or "FAC", can_fix_internally=True))
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
    bt, br, bc, off, bs_stu = _indexes(data)
    class_students = data.get("class_students", {})
    common_slots = data.get("common_slots", [])
    m = cp_model.CpModel()
    x, info = {}, {}
    for i, a in enumerate(allocs):
        dept = a["department"]
        free = {tuple(f) for f in data["settings"][dept].get("free", [])}
        scope = a.get("scope")
        ctype = a.get("course_type", "MDC")
        enrolled_stu = set(a.get("enrolled_students", []))
        cls_stu = set(class_students.get(a.get("class"), [])) if a.get("class") is not None else set()
        affected_students = enrolled_stu | cls_stu

        is_common = a.get("scope") == "college_wide" or a.get("selection_type") == "STUDENT_SELECTED"
        ctype = a.get("course_type") or a.get("course_category", "MDC")
        if is_common:
            candidates = []
            pinned = a.get("pinned_slots")
            if pinned:
                for (p_day, p_start, p_end) in pinned:
                    matched_p = next((p for p, per in enumerate(data["settings"][dept]["periods"])
                                      if ov(p_start, p_end, per["start"], per["end"])), 0)
                    candidates.append((p_day, matched_p, p_start, p_end))
            else:
                for cs in common_slots:
                    if cs.get("course_type") in (ctype, "Both", None):
                        matched_p = next((p for p, per in enumerate(data["settings"][dept]["periods"])
                                          if ov(cs["start"], cs["end"], per["start"], per["end"])), 0)
                        candidates.append((cs["day"], matched_p, cs["start"], cs["end"]))
        else:
            candidates = [(d, p, s, e) for d, p, s, e in grid(data, dept) if (d, p) not in free]
            dept_mdc = {tuple(x) for x in data["settings"][dept].get("mdc_slots", [])}
            dept_minor = {tuple(x) for x in data["settings"][dept].get("minor_slots", [])}
            reserved_slots = dept_mdc | dept_minor
            if reserved_slots:
                non_reserved = [(d, p, s, e) for (d, p, s, e) in candidates if (d, p) not in reserved_slots]
                if len(non_reserved) >= a.get("sessions", 1):
                    candidates = non_reserved
            # Avoid placing department-selected offerings inside common periods if normal periods suffice
            if common_slots and (a.get("selection_type") == "DEPARTMENT_SELECTED" or a.get("scope") == "department_specific"):
                non_common = [(d, p, s, e) for (d, p, s, e) in candidates
                              if not any(cs["day"] == d and ov(s, e, cs["start"], cs["end"]) for cs in common_slots)]
                if len(non_common) >= a.get("sessions", 1):
                    candidates = non_common
            cw_students = data.get("cw_students_by_type", {})
            if common_slots and cw_students and affected_students:
                filtered = []
                for (d, p, s, e) in candidates:
                    clash = any(cs["day"] == d and ov(s, e, cs["start"], cs["end"])
                                for cs in common_slots
                                if any(sid in cw_students.get(cs.get("course_type", "MDC"), set())
                                       for sid in affected_students))
                    if not clash:
                        filtered.append((d, p, s, e))
                candidates = filtered

        for d, p, s, e in candidates:
            if a.get("teacher") is not None and (hit(off[(a["teacher"], d)], s, e) or hit(bt[(a["teacher"], d)], s, e)):
                continue
            if a.get("class") is not None and hit(bc[(a["class"], d)], s, e):
                continue
            if any(any(ov(s, e, bs, be) for bs, be, _ in bs_stu[(sid, d)]) for sid in affected_students):
                continue

            for r in rooms:
                if a.get("room") is not None and r["id"] != a.get("room"):
                    continue
                if use_rooms and r["id"] is not None and (r["type"] != a["room_type"] or hit(br[(r["id"], d)], s, e)):
                    continue
                x[i, d, p, r["id"]] = m.NewBoolVar(f"x{i}_{d}_{p}_{r['id']}")
                info[i, d, p, r["id"]] = (s, e)

    A, AD, TS, CS, ov_groups = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for (i, d, p, r), v in x.items():
        a, (s, e) = allocs[i], info[i, d, p, r]
        A[i].append(v)
        AD[i, d].append(v)
        if a.get("teacher") is not None:
            TS[a["teacher"], a["department"], d, p].append(v)
            ov_groups["t", a["teacher"], d].append((s, e, v))
        if a.get("class") is not None:
            CS[a["class"], d, p].append(v)
            ov_groups["c", a["class"], d].append((s, e, v))
        if r is not None:
            ov_groups["r", r, d].append((s, e, v))
        if a.get("section_id") is not None:
            ov_groups["sec", a["section_id"], d].append((s, e, v))
        enrolled_stu = set(a.get("enrolled_students", []))
        cls_stu = set(class_students.get(a.get("class"), [])) if a.get("class") is not None else set()
        for sid in (enrolled_stu | cls_stu):
            ov_groups["student", sid, d].append((s, e, v))

    for i, a in enumerate(allocs):
        if not A[i]:
            cname = data.get("classes", {}).get(a.get("class"), {}).get("name", "")
            target_desc = f"{a['subject']} ({cname})" if cname else a.get("code", a["subject"])
            tid = a.get("teacher")
            T = data.get("teachers", {}).get(tid) if tid is not None else None
            tname = T["name"] if T else "Assigned teacher"
            tcode = T.get("code") or "FAC" if T else ""
            return _impossible([dict(
                issue=f"Teacher conflict: {tname} ({tcode}) has no free period for '{target_desc}' where they and the class are both available.",
                fix=f"Reassign '{a['subject']}' to another teacher, or adjust {tname}'s unavailable periods in Teacher Availability.",
                type="teacher_clash",
                can_fix_internally=True,
                teacher_id=tid,
                teacher_name=tname,
                faculty_code=tcode
            )])

    # ---- Always-on rules ----
    for i, a in enumerate(allocs):
        m.Add(sum(A[i]) == a["sessions"])
    for items in ov_groups.values():
        _atoms(m, items)
    load = defaultdict(list)
    for (i, d, p, r), v in x.items():
        if allocs[i].get("teacher") is not None:
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
        if c is not None:
            class_days[c, d] += vs
    for (c, d), vs in class_days.items():
        if c in data.get("classes", {}):
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

    for c, d in {(k[0], k[1]) for k in CS if k[0] is not None}:
        if c in data.get("classes", {}):
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
        busy_teachers = []
        for a in allocs:
            tid = a.get("teacher")
            if tid is not None and tid in data.get("teachers", {}):
                tname = data["teachers"][tid]["name"]
                tcode = data["teachers"][tid].get("code") or ""
                if data["teachers"][tid].get("existing_load", 0) > 0 or any(hit(bt.get((tid, d), []), 0, 1440) for d in range(7)):
                    if tname not in [bt_item[0] for bt_item in busy_teachers]:
                        busy_teachers.append((tname, tcode, tid))

        if busy_teachers:
            t_names_str = ", ".join(f"{t[0]} ({t[1]})" if t[1] else t[0] for t in busy_teachers)
            first_t = busy_teachers[0]
            return _impossible([dict(
                issue=f"Teacher conflict: {t_names_str} is already scheduled in other departments at overlapping times.",
                fix="Reassign some subjects to another available teacher in your department, or move conflicting sessions.",
                type="teacher_clash",
                can_fix_internally=True,
                teacher_id=first_t[2],
                teacher_name=first_t[0],
                faculty_code=first_t[1],
                alt=True
            )])
        return _impossible([dict(issue="These sessions can't all fit without clashing with other departments' timetables.",
                                 fix="Ask the other department to move a session, or add periods or days in Rules.", alt=True)])
    entries = []
    for (i, d, p, r), v in x.items():
        if sv.Value(v):
            a, (s, e) = allocs[i], info[i, d, p, r]
            entries.append(dict(allocation=i, department=a["department"], day=d, period=p, start=s, end=e, room=r,
                                kind=a.get("kind", "regular"), offering_id=a.get("offering_id"),
                                section_id=a.get("section_id"), code=a.get("code"),
                                subject=a["subject"], teacher=a.get("teacher"),
                                **{"class": a.get("class")}))
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
        if e.get("teacher") is not None:
            by_t[e["teacher"], e["department"], e["day"]].append(e["period"])
        if e.get("class") is not None:
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
    (not the one being moved). `entry` needs: class, teacher, room, subject, department, scope, course_type, enrolled_students."""
    here = [b for b in data["busy"] if b["day"] == day and ov(start, end, b["start"], b["end"])]
    t_id = entry.get("teacher")
    if t_id is not None:
        T = data["teachers"].get(t_id)
        if T:
            for b in here:
                if b.get("teacher") == t_id:
                    return False, f"{T['name']} is already teaching {b.get('department', 'another class')} · {b.get('subject', '')} at that time."
            if any(d == day and ov(start, end, s, e) for d, s, e in T.get("unavailable", [])):
                return False, f"{T['name']} is not available at that time."
    c_id = entry.get("class")
    if c_id is not None:
        for b in here:
            if b.get("class") == c_id:
                return False, "This class already has another subject at that time."
    # Scope check
    is_common = entry.get("scope") == "college_wide" or entry.get("selection_type") == "STUDENT_SELECTED"
    if is_common:
        ctype = entry.get("course_type") or entry.get("course_category", "MDC")
        cslots = data.get("common_slots", [])
        if not any(cs["day"] == day and cs["start"] == start and cs["end"] == end and cs.get("course_type") in (ctype, "Both", None) for cs in cslots):
            return False, f"College-wide {ctype} courses must use a configured common time slot."
    # Student conflict checks
    stu_ids = set(entry.get("enrolled_students", []))
    cls_students = set(data.get("class_students", {}).get(c_id, [])) if c_id is not None else set()
    all_stu = stu_ids | cls_students
    if all_stu:
        students_dict = data.get("students", {})
        for b in here:
            busy_stu = set(b.get("student_ids", []))
            clash = all_stu & busy_stu
            if clash:
                first_sid = next(iter(clash))
                sname = students_dict.get(first_sid, {}).get("name", f"Student {first_sid}")
                return False, f"{sname} is already attending {b.get('subject', 'another course')} at that time."
    st = data.get("settings", {}).get(entry.get("department"))
    if st and not is_common:
        if day not in st["days"]:
            return False, "That day isn't one of your working days."
        if [day, period] in [list(f) for f in st.get("free", [])]:
            return False, "You chose to keep that period free."
        if c_id is not None:
            same_day = [b for b in data["busy"] if b["day"] == day and b.get("class") == c_id]
            mode, mx = rule(data, entry["department"], "spread")
            if mode == "require" and sum(1 for b in same_day if b.get("subject") == entry["subject"]) + 1 > mx:
                return False, f"Your rule allows at most {mx} session(s) of {entry['subject']} per day for a class."
            mode, mx = rule(data, entry["department"], "class_day_max")
            if mode == "require" and len(same_day) + 1 > mx:
                return False, f"Your rule allows at most {mx} periods per day for a class."
    taken = {b["room"] for b in here if b.get("room") is not None}
    if data.get("use_rooms", True) and entry.get("room") in taken:
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
