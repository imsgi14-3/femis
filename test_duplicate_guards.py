"""Duplicate guards: b_form (student CNIC), admission_number, and the
Class+Section+Roll triple uniqueness (user directive 2026-10-01).

Locks `_uniqueness_error` in femis-web/app.py across every write path:
save-tab (create + update), final-submit, IntegrityError fallback, and the
legacy /submit route. Semantics: digits-only CNIC compare, whitespace/case
-insensitive admission compare, case/whitespace-insensitive roll-triple
compare (class+section+roll all present required; empty/None never
conflicts), own-row value allowed on update (exclude_id).

Also locks the student-login auto-create gate: a name typo at login must
flash an "already belongs" error instead of creating a second row for a
taken roll, an ilike-matching name logs into the existing row, and the
startup migration's guarded uq_students_class_section_roll index exists
(baseline has no duplicate groups).

Run: python test_duplicate_guards.py   (exit 0 = all pass)
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import app, db, Student  # noqa: E402
from form_payloads import create_full, tab1  # noqa: E402

DB = ROOT / "femis-web" / "instance" / "femis.db"
BASELINE_IDS = [3, 4, 6, 8, 9, 10]

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


def anon():
    return app.test_client()


def admin():
    c = app.test_client()
    with c.session_transaction() as s:
        s["role"] = "admin"
        s["user_name"] = "dup-guard"
    return c


def save(data, student_id=None, as_admin=False):
    if student_id is None:
        # complete tab-1 payload (server mandatory twin); explicit keys win
        data = {**tab1(), **data}
    c = admin() if as_admin else anon()
    r = c.post("/api/save-tab",
               json={"tab": 1, "student_id": student_id, "data": data})
    return r.status_code, (r.get_json() or {})


created = []

try:
    # ==================================================================
    # A. b_form create-path duplicates (digits-only normalization)
    # ==================================================================
    st, b = save({"name": "DupGuard A", "class_id": "5", "section_id": "Z",
                  "roll_no": "901", "b_form": "36302-9876543-2"})
    sid1 = b.get("student_id")
    created.append(sid1)
    check("A1 first b_form create ok", st == 200 and b.get("ok") and sid1, str(b))

    st, b = save({"name": "DupGuard B", "class_id": "5", "section_id": "Z",
                  "roll_no": "902", "b_form": "3630298765432"})
    check("A2 digits-only duplicate b_form -> 409",
          st == 409 and "already used" in (b.get("error") or ""), str(b))

    st, b = save({"name": "DupGuard C", "class_id": "5", "section_id": "Z",
                  "roll_no": "903", "b_form": " 36302 9876543 2 "})
    check("A3 spaced duplicate b_form -> 409",
          st == 409 and "already used" in (b.get("error") or ""), str(b))

    st, b = save({"name": "DupGuard D", "class_id": "5", "section_id": "Z",
                  "roll_no": "904", "b_form": "",
                  "is_bform_available": "0"})
    err = b.get("error") or ""
    check("A4 empty b_form create -> 400 mandatory, NOT 409 (flag no "
          "longer exempts; empties never conflict)",
          st == 400 and "Mandatory fields missing" in err
          and "b_form" in err and "already used" not in err, err)
    st, b = save({"name": "DupGuard E", "class_id": "5", "section_id": "Z",
                  "roll_no": "905", "b_form": "",
                  "is_bform_available": "0"})
    err = b.get("error") or ""
    check("A5 second empty b_form -> 400 mandatory again (empties may "
          "repeat — a conflict would surface as 409)",
          st == 400 and "Mandatory fields missing" in err
          and "b_form" in err and "already used" not in err, err)
    st, b = save({"name": "DupGuard D", "class_id": "5", "section_id": "Z",
                  "roll_no": "904", "b_form": "36302-1111111-1"})
    sid4 = b.get("student_id")
    created.append(sid4)
    check("A4b row created with a b_form for the update-path checks",
          st == 200 and sid4, str(b))
    st, b = save({"name": "DupGuard E", "class_id": "5", "section_id": "Z",
                  "roll_no": "905", "b_form": "36302-2222222-1"})
    sid5 = b.get("student_id")
    created.append(sid5)
    check("A5b second row created for exclude_id / own-value checks",
          st == 200 and sid5, str(b))

    # ==================================================================
    # B. b_form update-path + exclude_id (own value allowed)
    # ==================================================================
    st, b = save({"b_form": "6111111111111"}, student_id=sid4, as_admin=True)
    check("B1 update sets own b_form", st == 200 and b.get("ok"), str(b))
    st, b = save({"b_form": "6111111111111"}, student_id=sid4, as_admin=True)
    check("B2 own unchanged b_form on update -> ok (exclude self)",
          st == 200 and b.get("ok"), str(b))
    st, b = save({"b_form": "36302-9876543-2"}, student_id=sid5, as_admin=True)
    check("B3 update to another row's b_form -> 409",
          st == 409 and "DupGuard A" in (b.get("error") or ""), str(b))

    # ==================================================================
    # C. admission_number create/update duplicates (case+space-insensitive)
    # ==================================================================
    st, b = save({"name": "AdmGuard A", "class_id": "6", "section_id": "Z",
                  "roll_no": "906", "admission_number": "ADM-2026-001"})
    sid6 = b.get("student_id")
    created.append(sid6)
    check("C1 first admission create ok", st == 200 and sid6, str(b))

    st, b = save({"name": "AdmGuard B", "class_id": "6", "section_id": "Z",
                  "roll_no": "907", "admission_number": "ADM-2026-001"})
    check("C2 exact duplicate admission -> 409",
          st == 409 and "Admission Number" in (b.get("error") or ""), str(b))

    st, b = save({"name": "AdmGuard C", "class_id": "6", "section_id": "Z",
                  "roll_no": "908", "admission_number": "  adm-2026-001 "})
    check("C3 case/space duplicate admission -> 409",
          st == 409 and "AdmGuard A" in (b.get("error") or ""), str(b))

    st, b = save({"admission_number": "ADM-2026-001"}, student_id=sid6, as_admin=True)
    check("C4 own unchanged admission on update -> ok",
          st == 200 and b.get("ok"), str(b))
    st, b = save({"admission_number": "ADM-2026-002"}, student_id=sid6, as_admin=True)
    check("C5 update to distinct admission -> ok",
          st == 200 and b.get("ok"), str(b))
    st, b = save({"admission_number": "ADM-2026-002"}, student_id=sid5, as_admin=True)
    check("C6 update to another row's admission -> 409",
          st == 409 and "AdmGuard A" in (b.get("error") or ""), str(b))
    st, b = save({"name": "AdmGuard D", "class_id": "6", "section_id": "Z",
                  "roll_no": "909"})
    sid8 = b.get("student_id")
    created.append(sid8)
    check("C7 create without admission ok", st == 200 and sid8, str(b))
    st, b = save({"name": "AdmGuard E", "class_id": "6", "section_id": "Z",
                  "roll_no": "910"})
    sid9 = b.get("student_id")
    created.append(sid9)
    check("C8 second empty admission ok (empties may repeat)",
          st == 200 and sid9, str(b))

    # ==================================================================
    # D. final-submit path (admin session; data included in payload).
    #    D3 expects 200, so the carrier must be a COMPLETE record (the
    #    mandatory twin rejects incomplete finals).
    # ==================================================================
    st, b = create_full(admin(), name="AdmGuard F", roll_no="914")
    sid10 = b.get("student_id")
    created.append(sid10)
    check("D0 full record created for the final-submit round-trip",
          st == 200 and b.get("ok") and sid10, str(b))

    ac = admin()
    r = ac.post("/api/final-submit",
                json={"student_id": sid10,
                      "data": {"admission_number": "ADM-2026-002"}})
    b = r.get_json() or {}
    check("D1 final-submit duplicate admission -> 409",
          r.status_code == 409 and "already used" in (b.get("error") or ""),
          str(b))

    r = ac.post("/api/final-submit",
                json={"student_id": sid10,
                      "data": {"admission_number": "ADM-2026-003",
                               "b_form": "36302-9876543-2"}})
    b = r.get_json() or {}
    check("D2 final-submit duplicate b_form -> 409",
          r.status_code == 409 and "B-Form/CNIC" in (b.get("error") or ""),
          str(b))

    r = ac.post("/api/final-submit",
                json={"student_id": sid10,
                      "data": {"admission_number": "ADM-2026-003",
                               "b_form": "7777777777777"}})
    b = r.get_json() or {}
    check("D3 final-submit distinct values -> ok + redirect key",
          r.status_code == 200 and b.get("ok")
          and str(b.get("redirect", "")).startswith("/success/"), str(b))

    # ==================================================================
    # E. legacy /submit route parity
    # ==================================================================
    r = anon().post("/submit", data={
        "name": "Legacy Dup", "class_id": "7", "section_id": "Z",
        "roll_no": "911", "admission_number": "ADM-2026-002"},
        follow_redirects=False)
    # legacy route flashes + redirects on conflict (never creates)
    con = sqlite3.connect(str(DB))
    n_legacy = con.execute(
        "SELECT COUNT(*) FROM students WHERE name='Legacy Dup'").fetchone()[0]
    con.close()
    check("E1 legacy /submit duplicate admission blocked (no row created)",
          n_legacy == 0 and r.status_code == 302, (n_legacy, r.status_code))

    # ==================================================================
    # F. message quality: names holder + id
    # ==================================================================
    st, b = save({"name": "Msg Probe", "class_id": "5", "section_id": "Z",
                  "roll_no": "912", "b_form": "36302-9876543-2"})
    err = b.get("error") or ""
    check("F1 b_form error names holder and id",
          st == 409 and "'DupGuard A'" in err and "(id" in err, err)
    st, b = save({"name": "Msg Probe Two", "class_id": "6", "section_id": "Z",
                  "roll_no": "913", "admission_number": "ADM-2026-002"})
    err = b.get("error") or ""
    check("F2 admission error names holder and id",
          st == 409 and "'AdmGuard A'" in err and "(id" in err, err)

    # ==================================================================
    # G. Class+Section+Roll uniqueness (save-tab create + update)
    # ==================================================================
    st, b = save({"name": "RollGuard A", "class_id": "8", "section_id": "XX",
                  "roll_no": "951"})
    sidg = b.get("student_id")
    created.append(sidg)
    check("G1 first roll create ok", st == 200 and sidg, str(b))
    st, b = save({"name": "RollGuard B", "class_id": "8", "section_id": "XX",
                  "roll_no": "951"})
    err = b.get("error") or ""
    check("G2 same class/section/roll with a different name -> 409",
          st == 409 and "already belongs" in err and "'RollGuard A'" in err, err)
    st, b = save({"name": "rollguard a", "class_id": " 8 ",
                  "section_id": "xx", "roll_no": "951"})
    err = b.get("error") or ""
    check("G3 roll conflict is case/space-insensitive -> 409",
          st == 409 and "already belongs" in err, err)
    st, b = save({"name": "RollGuard A", "class_id": "8",
                  "section_id": "XX", "roll_no": "951"},
                 student_id=sidg, as_admin=True)
    check("G4 own unchanged triple on update -> ok (exclude self)",
          st == 200 and b.get("ok"), str(b))
    st, b = save({"class_id": "8", "section_id": "XX", "roll_no": "951"},
                 student_id=sid5, as_admin=True)
    err = b.get("error") or ""
    check("G5 moving another row onto a taken triple -> 409",
          st == 409 and "'RollGuard A'" in err, err)

    # ==================================================================
    # H. student login: a name typo never creates a second row
    # ==================================================================
    def login_as(nm, cls, sec, roll):
        c = anon()
        r = c.post("/login", data={"role": "student", "name": nm,
                                   "class_id": cls, "section": sec,
                                   "roll_no": roll}, follow_redirects=False)
        return c, r

    c1, r1 = login_as("RollKid A", "9", "YY", "961")
    with c1.session_transaction() as s:
        sidh = s.get("student_id")
    created.append(sidh)
    check("H1 first login with a fresh roll creates the row",
          r1.status_code == 302 and sidh
          and "student-dashboard" in r1.headers.get("Location", ""),
          (r1.status_code, r1.headers.get("Location"), sidh))

    c2, r2 = login_as("RollKid Typo", "9", "YY", "961")
    page = c2.get("/login").data.decode("utf-8", "replace")
    with app.app_context():
        n_rollkid = Student.query.filter(Student.name.like("RollKid%")).count()
    check("H2 same roll + different name -> rejected, NO second row",
          r2.status_code == 302
          and str(r2.headers.get("Location", "")).endswith("/login")
          and n_rollkid == 1 and "already belongs" in page,
          (r2.headers.get("Location"), n_rollkid))

    c3, r3 = login_as("rollkid a", "9", "yy", " 961 ")
    with c3.session_transaction() as s:
        sid3 = s.get("student_id")
    with app.app_context():
        n_rollkid = Student.query.filter(Student.name.like("RollKid%")).count()
    check("H3 same roll + matching name (ilike) logs into the existing row",
          sid3 == sidh and n_rollkid == 1, (sid3, sidh, n_rollkid))

    # ==================================================================
    # I. source locks: login gate + guarded startup index + /submit keys
    # ==================================================================
    app_src = (ROOT / "femis-web" / "app.py").read_text(encoding="utf-8")
    check("I1 login asks the roll owner before auto-creating",
          "holder = _roll_conflict(class_id, section, roll_no)" in app_src
          and "ask the admin to correct it instead of" in app_src)
    check("I2 _uniqueness_error checks the full class/section/roll triple",
          'all(k in mapped for k in ("class_id", "section_id", "roll_no"))'
          in app_src)
    check("I3 legacy /submit passes class/section/roll through uniq",
          '"class_id", "section_id", "roll_no"' in app_src)
    check("I4 startup index is guarded by a duplicate-groups count",
          "uq_students_class_section_roll" in app_src
          and "class/section/roll group(s) remain" in app_src)

    # ==================================================================
    # J. the unique index itself (baseline is clean, so migration created it)
    # ==================================================================
    con = sqlite3.connect(str(DB))
    idx = [r[1] for r in con.execute("PRAGMA index_list(students)")]
    dup_now = con.execute(
        "SELECT COUNT(*) FROM ("
        " SELECT LOWER(class_id), LOWER(section_id), LOWER(roll_no)"
        " FROM students WHERE class_id IS NOT NULL AND section_id IS NOT NULL"
        "   AND roll_no IS NOT NULL AND roll_no <> ''"
        " GROUP BY 1, 2, 3 HAVING COUNT(*) > 1)").fetchone()[0]
    con.close()
    check("J1 uq_students_class_section_roll exists (baseline has no dupes)",
          "uq_students_class_section_roll" in idx and dup_now == 0,
          (idx, dup_now))

finally:
    # ------------------------------------------------------------------
    # Cleanup: every row this run created; baseline must be restored.
    # ------------------------------------------------------------------
    with app.app_context():
        for sid in [s for s in created if s]:
            st_row = Student.query.get(sid)
            if st_row:
                db.session.delete(st_row)
        for nm in ("Legacy Dup", "Msg Probe Two", "Msg Probe",
                   "RollGuard A", "RollGuard B", "RollKid Typo", "RollKid A"):
            for st_row in Student.query.filter(Student.name == nm).all():
                db.session.delete(st_row)
        db.session.commit()

    con = sqlite3.connect(str(DB))
    ids = [r[0] for r in con.execute("SELECT id FROM students ORDER BY id")]
    con.close()
    check("Z1 students baseline restored", ids == BASELINE_IDS, ids)

passed = sum(1 for _, ok in results if ok)
print("=" * 50)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
