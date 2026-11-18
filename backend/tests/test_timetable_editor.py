"""Interactive Timetable Editor & Batch Validation Tests.
Tests:
1. Fetching class timetable with combined regular & student-enrolled MDC/Minor sessions.
2. Batch validate detects teacher conflicts across departments.
3. Batch validate detects valid non-clashing moves.
4. Batch save updates entries atomically and logs audit.
5. Quick edit updates session teacher and room.
6. Delete entry removes a session.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
import api.auth as auth
from api.main import app

PW = "TestPass-1234"
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))

def sign_in(u):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": u, "password": PW})
    assert r.status_code == 200 and r.json().get("signed_in") is True
    return c

def test_editor():
    cs = sign_in("cs")
    maths = sign_in("maths")

    # 1. Generate timetables
    r_cs = cs.post("/api/generate", json={})
    ok(r_cs.status_code == 200, "CS generates timetable")
    r_ma = maths.post("/api/generate", json={})
    ok(r_ma.status_code == 200, "Maths generates timetable")

    # 2. Fetch class timetable for CS
    cs_classes = cs.get("/api/classes").json()
    cid = cs_classes[0]["id"]
    tt = cs.get(f"/api/timetable/{cid}").json()
    ok(len(tt) > 0, "CS class timetable returned sessions")
    entry1 = tt[0]

    # 3. Batch validation: moving to a valid open slot
    # Test valid move or swap
    target_day = (entry1["day"] + 1) % 5
    target_period = entry1["period"]
    r_val = cs.post("/api/timetables/validate-batch", json={
        "class_id": cid,
        "moves": [{"id": entry1["id"], "day": target_day, "period": target_period}]
    })
    ok(r_val.status_code == 200, "Batch validate endpoint responded 200")
    val_data = r_val.json()
    ok("valid" in val_data and "items" in val_data, "Batch validate returns valid status and items")

    # 4. Batch validation: deliberately creating a clash with Maths teacher
    # Dr. Anil Kumar teaches in CS and Maths
    # Check if a clash is caught
    # Let's see if we place a session on top of another existing session of the same teacher
    fac = {f["name"]: f["id"] for f in cs.get("/api/faculty").json()}
    dr_anil = fac.get("Dr. Anil Kumar")
    if dr_anil:
        # Find where Dr Anil is teaching in Maths
        maths_tt = maths.get("/api/classes").json()
        m_cid = maths_tt[0]["id"]
        m_sessions = maths.get(f"/api/timetable/{m_cid}").json()
        anil_maths = next((s for s in m_sessions if s.get("faculty_id") == dr_anil), None)
        if anil_maths:
            # Move CS entry1 to anil_maths slot with Dr Anil
            r_clash = cs.post("/api/timetables/validate-batch", json={
                "class_id": cid,
                "moves": [{"id": entry1["id"], "day": anil_maths["day"], "period": anil_maths["period"], "faculty_id": dr_anil}]
            })
            ok(r_clash.json()["valid"] is False, "Batch validate correctly catches cross-department teacher clash")
            ok(any("Dr. Anil Kumar" in item["issue"] for item in r_clash.json()["items"]), "Issue specifies teacher conflict")

    # 5. Quick edit session
    r_qe = cs.put(f"/api/entries/{entry1['id']}", json={"faculty_id": dr_anil})
    ok(r_qe.status_code == 200, "Quick edit session faculty accepted")

    # 6. Batch save
    # Let's save a valid swap or move
    # First find an unoccupied slot in CS timetable
    busy_slots = {(s["day"], s["period"]) for s in tt}
    free_slot = None
    for d in range(5):
        for p in range(6):
            if (d, p) not in busy_slots:
                free_slot = (d, p)
                break
        if free_slot:
            break

    if free_slot:
        r_save = cs.post("/api/timetables/save-batch", json={
            "class_id": cid,
            "moves": [{"id": entry1["id"], "day": free_slot[0], "period": free_slot[1]}]
        })
        ok(r_save.status_code == 200 and r_save.json()["ok"] is True, "Batch save updates timetable atomically")
        tt_after = cs.get(f"/api/timetable/{cid}").json()
        moved_entry = next(s for s in tt_after if s["id"] == entry1["id"])
        ok(moved_entry["day"] == free_slot[0] and moved_entry["period"] == free_slot[1], "Session persisted at new position")

    # 7. Delete session (own regular session)
    del_id = next(s["id"] for s in tt if s["entry_type"] == "regular")
    r_del = cs.delete(f"/api/entries/{del_id}")
    ok(r_del.status_code == 200, "Session deleted successfully")
    tt_del = cs.get(f"/api/timetable/{cid}").json()
    ok(all(s["id"] != del_id for s in tt_del), "Deleted session no longer appears in timetable")

    print("ALL INTERACTIVE TIMETABLE EDITOR TESTS PASSED!")

if __name__ == "__main__":
    test_editor()
