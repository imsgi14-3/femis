"""Format-gate + address-conditional validation (2026-09-29 correction batch).

Server twin of form.js validateTab (app.py _format_error + mandatory.py):
  A. save-tab format gates — mobile 03XX-XXXXXXX, landline 0XX-XXXXXXX,
     email shape, date_of_birth strictly before today (create + partial
     update paths; empty values pass — required-ness is mandatory.py's job)
  B. final-submit over the STORED record (the Eman case: a DOB stored as
     today blocks submission until fixed; stored bad phone likewise)
  C. legacy /submit parity (flash + redirect, no row created)
  D. conditional address rules — Address Type=Village -> village_id,
     Housing Society -> housing_society_id (temp + present), and the
     same-as-permanent branch that turns the present rules off
  E. mother_name is unconditional (dead-mother case: the always-visible
     input stays required; the hidden mother-details group does not)
  F. client-side guard text present in form.js (static parity)

Run: python test_format_validation.py   (exit 0 = all pass)
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import app, db, Student  # noqa: E402
from form_payloads import create_full, form_all, tab1, tab2  # noqa: E402

DB = ROOT / "femis-web" / "instance" / "femis.db"
JS = (ROOT / "femis-web" / "static" / "form.js").read_text(encoding="utf-8")

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


def anon():
    return app.test_client()


def admin():
    c = app.test_client()
    with c.session_transaction() as s:
        s["role"] = "admin"
        s["user_name"] = "fmt-guard"
    return c


def post(data, tab=1, student_id=None, client=None):
    c = client or anon()
    r = c.post("/api/save-tab",
               json={"tab": tab, "student_id": student_id, "data": data})
    return r.status_code, (r.get_json() or {})


def sql(query, params=()):
    con = sqlite3.connect(str(DB))
    try:
        con.execute(query, params)
        con.commit()
    finally:
        con.close()


TODAY = datetime.now().date()


created = []
con0 = sqlite3.connect(str(DB))
BASELINE_IDS = sorted(r[0] for r in con0.execute("SELECT id FROM students"))
con0.close()

try:
    # ==================================================================
    # A. save-tab format gates (create + partial update)
    # ==================================================================
    st, b = post(tab1(name="FmtGuard Probe", contact_number="03001234567"))
    err = b.get("error") or ""
    check("A1 mobile without dash -> 400 names 03XX-XXXXXXX",
          st == 400 and "03XX-XXXXXXX" in err, err)

    st, b = post(tab1(name="FmtGuard Probe", contact_number="0400-1234567"))
    err = b.get("error") or ""
    check("A2 mobile wrong prefix -> 400 (04 not a mobile)",
          st == 400 and "03XX-XXXXXXX" in err, err)

    st, b = post(tab1(name="FmtGuard Probe", email="Nil"))
    err = b.get("error") or ""
    check("A3 email 'Nil' -> 400 names valid email",
          st == 400 and "must be a valid email address" in err, err)

    st, b = post(tab1(name="FmtGuard Probe",
                      date_of_birth=TODAY.isoformat()))
    err = b.get("error") or ""
    check("A4 DOB = today (ISO) -> 400 before today (Eman case)",
          st == 400 and "must be a date before today" in err, err)

    st, b = post(tab1(name="FmtGuard Probe",
                      date_of_birth=TODAY.strftime("%m/%d/%Y")))
    err = b.get("error") or ""
    check("A5 DOB = today (MM/DD/YYYY display) -> 400 before today",
          st == 400 and "must be a date before today" in err, err)

    st, b = post(tab1(name="FmtGuard Probe", date_of_birth="12/31/2099"))
    err = b.get("error") or ""
    check("A6 future DOB -> 400 before today",
          st == 400 and "must be a date before today" in err, err)

    st, b = post(tab1(name="FmtGuard Probe", date_of_birth="13/45/2015"))
    err = b.get("error") or ""
    check("A7 unparseable DOB -> 400 valid date",
          st == 400 and "must be a valid date" in err, err)

    st, b = create_full(admin(), name="FmtGuard Create")
    sid_a = b.get("student_id")
    created.append(sid_a)
    check("A8 complete record (conformant mobile/email/DOB) -> 200",
          st == 200 and sid_a, str(b))

    st, b = post({"father_landline": "211234567"}, tab=2, student_id=sid_a,
                 client=admin())
    err = b.get("error") or ""
    check("A9 landline without dash/0-prefix -> 400 names 0XX-XXXXXXX",
          st == 400 and "0XX-XXXXXXX" in err, err)

    st, b = post({"father_landline": "021-1234567",
                  "mother_landline": "051-1234567"}, tab=2,
                 student_id=sid_a, client=admin())
    check("A10 conformant landlines -> 200", st == 200 and b.get("ok"),
          str(b))

    st, b = post({"father_landline": ""}, tab=2, student_id=sid_a,
                 client=admin())
    check("A11 empty landline passes the format gate (not mandatory)",
          st == 200 and b.get("ok"), str(b))

    st, b = post({"guardian_email": "not-an-email"}, tab=2,
                 student_id=sid_a, client=admin())
    err = b.get("error") or ""
    check("A12 guardian_email bad shape -> 400 names it",
          st == 400 and "Guardian's Email" in err and
          "must be a valid email address" in err, err)

    st, b = post({"emergency_contact": "3001234567"}, tab=4,
                 student_id=sid_a, client=admin())
    err = b.get("error") or ""
    check("A13 emergency_contact digit-only -> 400 (mobile rule on tab 4)",
          st == 400 and "03XX-XXXXXXX" in err, err)

    st, b = post({"emergency_contact": "0300-1234570"}, tab=4,
                 student_id=sid_a, client=admin())
    check("A14 conformant emergency_contact -> 200",
          st == 200 and b.get("ok"), str(b))

    # ==================================================================
    # B. final-submit over the STORED record (merged format gate)
    # ==================================================================
    st, b = create_full(admin(), name="FmtGuard Stale")
    sid_b = b.get("student_id")
    created.append(sid_b)
    check("B0 complete record for the final-submit round-trip -> 200",
          st == 200 and sid_b, str(b))

    sql("UPDATE students SET date_of_birth=? WHERE id=?",
        (TODAY.isoformat(), sid_b))
    r = admin().post("/api/final-submit", json={"student_id": sid_b,
                                                "data": {}})
    err = (r.get_json() or {}).get("error") or ""
    check("B1 stored DOB=today blocks final-submit -> 400 before today",
          r.status_code == 400 and "must be a date before today" in err
          and "Mandatory" not in err, err)

    sql("UPDATE students SET date_of_birth='2015-01-15', "
        "contact_number='03001234567' WHERE id=?", (sid_b,))
    r = admin().post("/api/final-submit", json={"student_id": sid_b,
                                                "data": {}})
    err = (r.get_json() or {}).get("error") or ""
    check("B2 stored dashless mobile blocks final-submit -> 400",
          r.status_code == 400 and "03XX-XXXXXXX" in err, err)

    sql("UPDATE students SET contact_number='0300-1234567' WHERE id=?",
        (sid_b,))
    r = admin().post("/api/final-submit", json={"student_id": sid_b,
                                                "data": {}})
    body = r.get_json() or {}
    check("B3 final-submit after fix -> 200 + submitted + redirect",
          r.status_code == 200 and body.get("ok")
          and str(body.get("redirect", "")).startswith("/success/"),
          str(body))

    # ==================================================================
    # C. legacy /submit parity (flash + redirect, no row)
    # ==================================================================
    r = anon().post("/submit",
                    data=form_all(name="FmtGuard Legacy Bad",
                                  contact_number="03001234567"),
                    follow_redirects=False)
    con = sqlite3.connect(str(DB))
    n_bad = con.execute(
        "SELECT COUNT(*) FROM students WHERE name='FmtGuard Legacy Bad'"
    ).fetchone()[0]
    con.close()
    check("C1 legacy /submit dashless mobile -> rejected, no row",
          n_bad == 0 and r.status_code == 302
          and "/success/" not in (r.headers.get("Location") or ""),
          (n_bad, r.status_code, r.headers.get("Location")))

    r = anon().post("/submit",
                    data=form_all(name="FmtGuard Legacy Bad2", email="Nil"),
                    follow_redirects=False)
    con = sqlite3.connect(str(DB))
    n_bad2 = con.execute(
        "SELECT COUNT(*) FROM students WHERE name='FmtGuard Legacy Bad2'"
    ).fetchone()[0]
    con.close()
    check("C2 legacy /submit email 'Nil' -> rejected, no row",
          n_bad2 == 0 and r.status_code == 302
          and "/success/" not in (r.headers.get("Location") or ""),
          (n_bad2, r.status_code, r.headers.get("Location")))

    r = anon().post("/submit", data=form_all(name="FmtGuard Legacy Good"),
                    follow_redirects=False)
    loc = r.headers.get("Location") or ""
    g_id = loc.rsplit("/", 1)[-1] if loc.rsplit("/", 1)[-1].isdigit() else None
    if g_id:
        created.append(int(g_id))
    check("C3 legacy /submit conformant payload -> 302 success + row",
          r.status_code == 302 and g_id is not None,
          (r.status_code, loc))

    # ==================================================================
    # D. conditional address rules (Village / Housing Society)
    # ==================================================================
    st, b = post(tab1(name="FmtGuard Village", address_type="Village",
                      village_id=""))
    err = b.get("error") or ""
    check("D1 Address Type=Village without village -> 400 names it",
          st == 400 and "tab 1: village_id" in err, err)

    st, b = post(tab1(name="FmtGuard Village", address_type="Village",
                      village_id="5"))
    sid_v = b.get("student_id")
    created.append(sid_v)
    check("D2 Village with village_id -> 200 create",
          st == 200 and sid_v, str(b))

    st, b = post(tab1(name="FmtGuard Housing", address_type="Housing Society",
                      housing_society_id=""))
    err = b.get("error") or ""
    check("D3 Address Type=Housing Society without id -> 400 names it",
          st == 400 and "tab 1: housing_society_id" in err, err)

    st, b = post(tab1(name="FmtGuard Housing", address_type="Housing Society",
                      housing_society_id="3"))
    sid_h = b.get("student_id")
    created.append(sid_h)
    check("D4 Housing Society with housing_society_id -> 200 create",
          st == 200 and sid_h, str(b))

    st, b = post({"present_address_type": "Village", "present_village_id": ""},
                 tab=1, student_id=sid_v, client=admin())
    err = b.get("error") or ""
    check("D5 present=Village without present_village -> 400 names it",
          st == 400 and "tab 1: present_village_id" in err
          and "present_sector_id" not in err, err)

    st, b = post({"present_address_type": "Village", "present_village_id": "4"},
                 tab=1, student_id=sid_v, client=admin())
    check("D6 present=Village with present_village_id -> 200",
          st == 200 and b.get("ok"), str(b))

    st, b = post({"present_address_type": "Housing Society",
                  "present_housing_society_id": ""},
                 tab=1, student_id=sid_h, client=admin())
    err = b.get("error") or ""
    check("D7 present=Housing Society without id -> 400 names it",
          st == 400 and "tab 1: present_housing_society_id" in err, err)

    st, b = post({"present_address_type": "Housing Society",
                  "present_housing_society_id": "7"},
                 tab=1, student_id=sid_h, client=admin())
    check("D8 present=Housing Society with id -> 200",
          st == 200 and b.get("ok"), str(b))

    st, b = post({"same_as_permanent_address": "1",
                  "present_address_type": "", "present_sector_id": "",
                  "present_sub_sector_id": "", "present_house": "",
                  "present_street": "", "present_address": "",
                  "present_village_id": "", "present_housing_society_id": ""},
                 tab=1, student_id=sid_h, client=admin())
    check("D9 same-as-permanent: present family blanked (incl. village/"
          "housing) -> 200 (rules off)",
          st == 200 and b.get("ok"), str(b))

    # ==================================================================
    # E. mother_name unconditional (dead-mother case)
    # ==================================================================
    st, b = create_full(admin(), name="FmtGuard Mother")
    sid_m = b.get("student_id")
    created.append(sid_m)
    check("E0 complete record for the mother branch -> 200",
          st == 200 and sid_m, str(b))

    st, b = post({"is_mother_alive": "0", "mother_name": ""}, tab=2,
                 student_id=sid_m, client=admin())
    err = b.get("error") or ""
    check("E1 mother dead + mother_name empty -> 400 names mother_name",
          st == 400 and "tab 2: mother_name" in err, err)
    check("E2 dead-mother error does NOT demand the hidden details group "
          "(mother_contact/profession/qualification)",
          "mother_contact" not in err and "mother_profession" not in err
          and "mother_qualification" not in err, err)

    st, b = post({"is_mother_alive": "0", "mother_name": "LATE MOTHER"},
                 tab=2, student_id=sid_m, client=admin())
    check("E3 mother dead + mother_name filled -> 200",
          st == 200 and b.get("ok"), str(b))

    # ==================================================================
    # F. client-side guard text present in form.js (static parity)
    # ==================================================================
    check("F1 JS mobile + landline regex guards present",
          "^03\\d{2}-\\d{7}$" in JS and "^0\\d{2}-\\d{7}$" in JS,
          "same patterns as app.py _MOBILE_RE/_LANDLINE_RE")
    check("F2 JS DOB before-today guard present",
          "must be a date before today" in JS, "form.js validateTab")
    check("F3 JS village/housing conditionalRequired entries present",
          '{fields: ["village_id"], trigger: "address_type", '
          'values: ["Village"]}' in JS
          and '{fields: ["housing_society_id"], trigger: "address_type", '
          'values: ["Housing Society"]}' in JS
          and '{fields: ["present_village_id"], trigger: "present_address_type", '
          'values: ["Village"]}' in JS
          and '{fields: ["present_housing_society_id"], '
          'trigger: "present_address_type", values: ["Housing Society"]}' in JS,
          "mirrors mandatory.py RULES")

finally:
    # ------------------------------------------------------------------
    # Cleanup: every row this run created; baseline must be restored.
    # ------------------------------------------------------------------
    with app.app_context():
        for sid in [s for s in created if s]:
            row = Student.query.get(sid)
            if row:
                db.session.delete(row)
        for nm in ("FmtGuard Legacy Bad", "FmtGuard Legacy Bad2",
                   "FmtGuard Legacy Good", "FmtGuard Probe",
                   "FmtGuard Village", "FmtGuard Housing"):
            for row in Student.query.filter(Student.name == nm).all():
                db.session.delete(row)
        db.session.commit()

    con = sqlite3.connect(str(DB))
    ids = sorted(r[0] for r in con.execute("SELECT id FROM students"))
    con.close()
    check("Z1 students baseline restored", ids == BASELINE_IDS, ids)

passed = sum(1 for _, ok in results if ok)
print("=" * 50)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
