"""CNIC length validation: 13 digits, dashes/spaces are display formatting.

Locks `_cnic_length_error` in femis-web/app.py across every write path:
save-tab (create + update), final-submit (payload AND stored record), and the
legacy /submit route. Semantics: digits-only count must be exactly 13 for any
present value (b_form, father_cnic, mother_cnic, guardian_cnic); empty/absent
passes (required-ness belongs to the form); rejected with 400 + field label.

Run: python test_cnic_length_validation.py   (exit 0 = all pass)
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
        s["user_name"] = "cnic-guard"
    return c


def save(data, student_id=None, as_admin=False):
    c = admin() if as_admin else anon()
    r = c.post("/api/save-tab",
               json={"tab": 1, "student_id": student_id, "data": data})
    return r.status_code, (r.get_json() or {})


def create(data):
    base = tab1(class_id="5", section_id="Z",
                roll_no=data.get("roll_no", "950"),
                name=data.get("name", "CnicGuard"))
    base.update(data)
    return save(base)


created = []
con0 = sqlite3.connect(str(DB))
BASELINE_IDS = sorted(r[0] for r in con0.execute("SELECT id FROM students"))
con0.close()

try:
    # ==================================================================
    # A. save-tab create path: short/long CNIC rejected, valid accepted
    # ==================================================================
    st, b = create({"name": "CnicGuard A", "roll_no": "951",
                    "b_form": "12345"})
    check("A1 short b_form (5 digits) -> 400",
          st == 400 and "13 digits" in (b.get("error") or ""), str(b))

    st, b = create({"name": "CnicGuard B", "roll_no": "952",
                    "father_cnic": "35202-123456"})
    check("A2 father_cnic 12 digits -> 400",
          st == 400 and "Father CNIC" in (b.get("error") or ""), str(b))

    st, b = create({"name": "CnicGuard C", "roll_no": "953",
                    "mother_cnic": "35202123456712"})
    check("A3 mother_cnic 14 digits -> 400",
          st == 400 and "Mother CNIC" in (b.get("error") or ""), str(b))

    st, b = create({"name": "CnicGuard D", "roll_no": "954",
                    "guardian_cnic": "11111"})
    check("A4 guardian_cnic short -> 400",
          st == 400 and "Guardian CNIC" in (b.get("error") or ""), str(b))

    st, b = create({"name": "CnicGuard E", "roll_no": "955",
                    "b_form": "88888-8888888-8",
                    "father_cnic": "35202 1234567 1"})
    sid1 = b.get("student_id")
    created.append(sid1)
    check("A5 valid formatted + spaced 13-digit CNICs -> 200 create",
          st == 200 and b.get("ok") and sid1, str(b))

    st, b = create({"name": "CnicGuard F", "roll_no": "956",
                    "is_bform_available": "0",
                    "b_form": "", "father_cnic": "",
                    "mother_cnic": "", "guardian_cnic": ""})
    err = b.get("error") or ""
    check("A6 empty b_form with B-Form=no -> 400 mandatory (the removed "
          "flag no longer exempts b_form; empties otherwise pass the "
          "length gate)",
          st == 400 and "Mandatory fields missing" in err
          and "b_form" in err and "13 digits" not in err, err)

    st, b = create({"name": "CnicGuard H", "roll_no": "960",
                    "b_form": ""})
    err = b.get("error") or ""
    check("A7 empty b_form with B-Form=yes -> 400 mandatory names b_form "
          "(not a length message)",
          st == 400 and "Mandatory fields missing" in err
          and "b_form" in err and "13 digits" not in err, err)

    # ==================================================================
    # B. save-tab update path
    # ==================================================================
    st, b = save({"b_form": "99999"}, student_id=sid1, as_admin=True)
    check("B1 update with short b_form -> 400",
          st == 400 and "B-Form/CNIC" in (b.get("error") or ""), str(b))
    st, b = save({"b_form": "77777-7777777-7"}, student_id=sid1, as_admin=True)
    check("B2 update with valid 13-digit b_form -> 200",
          st == 200 and b.get("ok"), str(b))
    st, b = save({"b_form": "88888-8888888-8"}, student_id=sid1, as_admin=True)
    check("B3 restore original b_form -> 200", st == 200 and b.get("ok"), str(b))

    # ==================================================================
    # C. final-submit gates the STORED record too (legacy junk blocks).
    #    C3 expects 200, so the carrier must be a COMPLETE record (every
    #    tab filled) — the mandatory twin rejects incomplete finals.
    # ==================================================================
    st, b = create_full(admin(), name="CnicGuard C2", roll_no="961")
    sid3 = b.get("student_id")
    created.append(sid3)
    check("C0 full record created for the final-submit round-trip",
          st == 200 and b.get("ok") and sid3, str(b))

    con = sqlite3.connect(str(DB))
    con.execute("UPDATE students SET father_cnic='1234567890' WHERE id=?",
                (sid3,))
    con.commit()
    con.close()

    ac = admin()
    r = ac.post("/api/final-submit",
                json={"student_id": sid3, "data": {}})
    b = r.get_json() or {}
    check("C1 stored short father_cnic blocks final-submit -> 400",
          r.status_code == 400 and "Father CNIC" in (b.get("error") or ""),
          str(b))

    st, b = save({"father_cnic": "35202-1234567-1"}, student_id=sid3,
                 as_admin=True)
    check("C2 fix stored CNIC via save-tab -> 200",
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
        "name": "Legacy Cnic", "class_id": "7", "section_id": "Z",
        "roll_no": "957", "b_form": "12345"},
        follow_redirects=False)
    con = sqlite3.connect(str(DB))
    n_legacy = con.execute(
        "SELECT COUNT(*) FROM students WHERE name='Legacy Cnic'").fetchone()[0]
    con.close()
    check("D1 legacy /submit short b_form blocked (no row created)",
          n_legacy == 0 and r.status_code == 302, (n_legacy, r.status_code))

    # ==================================================================
    # E. message quality: field label + example format
    # ==================================================================
    st, b = create({"name": "CnicGuard G", "roll_no": "958",
                    "b_form": "352021234567"})
    err = b.get("error") or ""
    check("E1 error names the field and shows the expected format",
          st == 400 and "B-Form/CNIC" in err and "12345-1234567-1" in err
          and "'352021234567'" in err, err)

finally:
    # ------------------------------------------------------------------
    # Cleanup: every row this run created; baseline must be restored.
    # ------------------------------------------------------------------
    with app.app_context():
        for sid in [s for s in created if s]:
            st_row = Student.query.get(sid)
            if st_row:
                db.session.delete(st_row)
        for nm in ("Legacy Cnic", "CnicGuard G"):
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
