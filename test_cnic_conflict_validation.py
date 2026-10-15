"""Father/Mother CNIC conflict validation: the two parent CNICs must differ.

Locks `_cnic_conflict_error` in femis-web/app.py across every write path:
save-tab (create + update, touched-only so a legacy conflict never blocks
unrelated tab saves), final-submit (merged stored+payload record), and the
legacy /submit route. Semantics: digits-only compare (dashes/spaces are
display formatting); empty/absent on either side passes (required-ness
belongs to the form); rejected with 400 + a message naming both fields and
echoing the value.

Run: python test_cnic_conflict_validation.py   (exit 0 = all pass)
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import app, db, Student  # noqa: E402
from form_payloads import create_full, tab1  # noqa: E402

DB = ROOT / "femis-web" / "instance" / "femis.db"

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
        s["user_name"] = "cnic-conflict-guard"
    return c


def save(data, student_id=None, as_admin=False):
    c = admin() if as_admin else anon()
    r = c.post("/api/save-tab",
               json={"tab": 1, "student_id": student_id, "data": data})
    return r.status_code, (r.get_json() or {})


def create(data):
    base = tab1(class_id="5", section_id="Z",
                roll_no=data.get("roll_no", "970"),
                name=data.get("name", "CnicConflict"))
    base.update(data)
    return save(base)


created = []
con0 = sqlite3.connect(str(DB))
BASELINE_IDS = sorted(r[0] for r in con0.execute("SELECT id FROM students"))
con0.close()

try:
    # ==================================================================
    # A. create path: equal pair rejected, anything else accepted
    # ==================================================================
    st, b = create({"name": "CnicSame A", "roll_no": "971",
                    "b_form": "88888-8888888-1",
                    "father_cnic": "35202-1234567-1",
                    "mother_cnic": "35202-1234567-1"})
    check("A1 create father==mother (same format) -> 400 conflict",
          st == 400 and "cannot be the same" in (b.get("error") or ""), str(b))

    st, b = create({"name": "CnicSame B", "roll_no": "972",
                    "b_form": "88888-8888888-2",
                    "father_cnic": "3520212345671",
                    "mother_cnic": "35202 1234567 1"})
    err = b.get("error") or ""
    check("A2 digits-only compare (plain vs spaced) -> 400",
          st == 400 and "cannot be the same" in err, err)

    st, b = create({"name": "CnicSame C", "roll_no": "973",
                    "b_form": "88888-8888888-3",
                    "father_cnic": "35202-1234567-1",
                    "mother_cnic": "35202-1234567-2"})
    sid1 = b.get("student_id")
    created.append(sid1)
    check("A3 create with different parent CNICs -> 200",
          st == 200 and b.get("ok") and sid1, str(b))

    st, b = create({"name": "CnicSame D", "roll_no": "974",
                    "b_form": "88888-8888888-4",
                    "father_cnic": "35202-1234567-3", "mother_cnic": ""})
    sid2 = b.get("student_id")
    created.append(sid2)
    check("A4 mother_cnic empty -> 200 (empties pass the conflict gate)",
          st == 200 and b.get("ok") and sid2, str(b))

    # ==================================================================
    # B. update path: touched-only, effective pair = stored + payload
    # ==================================================================
    st, b = save({"father_cnic": "35202-1234567-2"}, student_id=sid1,
                 as_admin=True)
    err = b.get("error") or ""
    check("B1 update father to stored mother's CNIC -> 400",
          st == 400 and "cannot be the same" in err, err)

    st, b = save({"mother_cnic": "35202 1234567 1"}, student_id=sid1,
                 as_admin=True)
    err = b.get("error") or ""
    check("B2 update mother to stored father's CNIC (spaced) -> 400",
          st == 400 and "cannot be the same" in err, err)

    con = sqlite3.connect(str(DB))
    con.execute("UPDATE students SET father_cnic=?, mother_cnic=? WHERE id=?",
                ("37405-1111111-1", "37405-1111111-1", sid1))
    con.commit()
    con.close()

    st, b = save({"contact_number": "0300-1234571"}, student_id=sid1,
                 as_admin=True)
    check("B3 unrelated tab-1 save on a legacy-conflict row -> 200 "
          "(touched-only gate stays out of the way)",
          st == 200 and b.get("ok"), str(b))

    st, b = save({"father_cnic": "37405-2222222-2"}, student_id=sid1,
                 as_admin=True)
    check("B4 save that RESOLVES the conflict -> 200",
          st == 200 and b.get("ok"), str(b))

    # ==================================================================
    # C. final-submit gates the STORED record too (merged pair)
    # ==================================================================
    st, b = create_full(admin(), name="CnicSame Full", roll_no="975")
    sid3 = b.get("student_id")
    created.append(sid3)
    check("C0 full record created for the final-submit round-trip",
          st == 200 and b.get("ok") and sid3, str(b))

    con = sqlite3.connect(str(DB))
    con.execute("UPDATE students SET father_cnic=?, mother_cnic=? WHERE id=?",
                ("37405-3333333-3", "37405-3333333-3", sid3))
    con.commit()
    con.close()

    ac = admin()
    r = ac.post("/api/final-submit",
                json={"student_id": sid3, "data": {}})
    b = r.get_json() or {}
    check("C1 stored equal parent CNICs block final-submit -> 400",
          r.status_code == 400 and "cannot be the same" in (b.get("error") or ""),
          str(b))

    st, b = save({"father_cnic": "37405-4444444-4"}, student_id=sid3,
                 as_admin=True)
    check("C2 fix stored conflict via save-tab -> 200",
          st == 200 and b.get("ok"), str(b))
    r = ac.post("/api/final-submit",
                json={"student_id": sid3, "data": {}})
    b = r.get_json() or {}
    check("C3 final-submit after fix -> 200 + redirect",
          r.status_code == 200 and b.get("ok")
          and str(b.get("redirect", "")).startswith("/success/"), str(b))

    # ==================================================================
    # D. legacy /submit route parity (rejects before creating a row)
    # ==================================================================
    r = anon().post("/submit", data={
        "name": "Legacy CnicSame", "class_id": "7", "section_id": "Z",
        "roll_no": "976", "b_form": "88888-8888888-6",
        "father_cnic": "35202-1234567-1", "mother_cnic": "35202-1234567-1"},
        follow_redirects=False)
    con = sqlite3.connect(str(DB))
    n_legacy = con.execute(
        "SELECT COUNT(*) FROM students WHERE name='Legacy CnicSame'"
    ).fetchone()[0]
    con.close()
    check("D1 legacy /submit equal parent CNICs blocked (no row created)",
          n_legacy == 0 and r.status_code == 302, (n_legacy, r.status_code))

    # ==================================================================
    # E. message quality: both field labels + the offending value
    # ==================================================================
    st, b = create({"name": "CnicSame E", "roll_no": "977",
                    "b_form": "88888-8888888-7",
                    "father_cnic": "35202-1234567-5",
                    "mother_cnic": "35202-1234567-5"})
    err = b.get("error") or ""
    check("E1 error names both fields and echoes the value",
          st == 400 and "Father CNIC" in err and "Mother CNIC" in err
          and "'35202-1234567-5'" in err, err)

finally:
    # ------------------------------------------------------------------
    # Cleanup: every row this run created; baseline must be restored.
    # ------------------------------------------------------------------
    with app.app_context():
        for sid in [s for s in created if s]:
            st_row = Student.query.get(sid)
            if st_row:
                db.session.delete(st_row)
        for nm in ("Legacy CnicSame", "CnicSame E"):
            for st_row in Student.query.filter(Student.name == nm).all():
                db.session.delete(st_row)
        db.session.commit()

    con = sqlite3.connect(str(DB))
    ids = sorted(r[0] for r in con.execute("SELECT id FROM students"))
    con.close()
    check("Z1 students baseline restored", ids == BASELINE_IDS, ids)

passed = sum(1 for _, ok in results if ok)
print("=" * 50)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
