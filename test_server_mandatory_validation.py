"""Server-side mandatory-field validation: every write path rejects empty
mandatory fields, per tab, mirroring form.js validateTab.

Locks femis-web/mandatory.py + app.py wiring end to end:
  A. save-tab CREATE with an empty mandatory field -> 400 + field names
   B. tab-1 visibility branches (Sector/Other, same-as-permanent, b-form
      unconditional + flag forced to '1', gender -> girls_stipend)
  C. tab-2 conditional branches (profession Other, father-dead guardians,
     mother income / BPS, father + guardian BPS for Govt Employee, orphan)
  D. tab-3 conditional branch (Institution Bus -> bus_route)
  E. checkbox-group parity: digital_device_type[] is NEVER required
  F. final-submit over the STORED record (the Alisha case: legacy empty
     address blocks submission until filled)
  G. legacy /submit route parity
  I. tab-5 IDP conditional mandatory: is_refugee=Yes -> idp_status_id +
     is_registered_refugee required (and registered=Yes -> card number);
     is_refugee=No -> none of them required

Gate order is part of the contract: CNIC length -> perms/lock -> uniqueness
(409) -> mandatory (400) — that precedence is asserted by
test_cnic_length_validation / test_duplicate_guards.

Run: python test_server_mandatory_validation.py   (exit 0 = all pass)
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import app, db, Student  # noqa: E402
from form_payloads import create_full, form_all, tab1, tab3, tab4  # noqa: E402

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
        s["user_name"] = "mand-guard"
    return c


def post(data, tab=1, student_id=None, client=None):
    c = client or anon()
    r = c.post("/api/save-tab",
               json={"tab": tab, "student_id": student_id, "data": data})
    return r.status_code, (r.get_json() or {})


def mk(**over):
    """Create a fresh tab-1 row for branch scenarios; returns (sid, body)."""
    st, b = post(tab1(**over))
    return (b.get("student_id") if st == 200 else None), b


created = []
con0 = sqlite3.connect(str(DB))
BASELINE_IDS = sorted(r[0] for r in con0.execute("SELECT id FROM students"))
con0.close()

try:
    # ==================================================================
    # A. save-tab create: empty mandatory field -> 400 naming the field
    # ==================================================================
    st, b = post(tab1(name="MandGuard Alpha"))
    sid_a = b.get("student_id")
    created.append(sid_a)
    check("A1 complete tab-1 create -> 200", st == 200 and sid_a, str(b))

    for fld in ("name", "contact_number"):
        data = tab1(name="MandGuard Probe")
        data[fld] = ""
        st, b = post(data)
        err = b.get("error") or ""
        check(f"A2 empty {fld} -> 400 names it (tab 1)",
              st == 400 and "Mandatory fields missing" in err
              and f"tab 1: {fld}" in err, err)

    st, b = post(tab1(name="MandGuard Probe", house=""))
    err = b.get("error") or ""
    check("A3 Sector branch: empty house -> 400 names house only",
          st == 400 and "tab 1: house" in err and "street" not in err, err)

    st, b = post(tab1(name="MandGuard Probe", address_type="Other"))
    err = b.get("error") or ""
    check("A4 Other branch: missing address -> 400 names address "
          "(house/street not required when Other)",
          st == 400 and "tab 1: address" in err
          and "present_address" not in err and "tab 1: house" not in err, err)

    # ==================================================================
    # B. tab-1 visibility branches on creates
    # ==================================================================
    sid_b, b = mk(name="MandGuard SameAs",
                  same_as_permanent_address="1",
                  present_address_type="", present_sector_id="",
                  present_sub_sector_id="", present_house="",
                  present_street="", present_address="")
    check("B1 same-as-permanent: whole present family blanked -> 200",
          sid_b is not None, str(b))
    created.append(sid_b)

    st, b = post(tab1(name="MandGuard PresOther",
                      present_address_type="Other", present_address=""))
    err = b.get("error") or ""
    check("B2 present Other branch: present_address required -> 400, "
          "present_house/street not required",
          st == 400 and "tab 1: present_address" in err
          and "present_house" not in err, err)

    st, b = post(tab1(name="MandGuard Female", gender="Female"))
    err = b.get("error") or ""
    check("B3 gender=Female requires girls_stipend -> 400 names it",
          st == 400 and "tab 1: girls_stipend" in err, err)

    st, b = post(tab1(name="MandGuard NoBform", is_bform_available="0",
                      b_form=""))
    err = b.get("error") or ""
    check("B4 empty b_form rejected even with flag=0 (question removed; "
          "b_form is unconditional)",
          st == 400 and "Mandatory fields missing" in err
          and "b_form" in err, err)

    sid_b4, b = mk(name="MandGuard FlagForced", is_bform_available="0")
    created.append(sid_b4)
    check("B4b flag=0 payload with b_form filled -> 200", sid_b4 is not None, str(b))
    with app.app_context():
        row = Student.query.get(sid_b4) if sid_b4 else None
        check("B4c stored is_bform_available forced to '1' on save",
              row is not None and row.is_bform_available == "1",
              getattr(row, "is_bform_available", None))

    # ==================================================================
    # C. tab-2 branches (updates on one complete record; 400s leave
    #    stored state untouched, so order is: rejects first, passes last)
    # ==================================================================
    st, b = create_full(admin(), name="MandGuard Tab Two")
    sid_t = b.get("student_id")
    created.append(sid_t)
    check("C0 complete record for tab-2 branches -> 200",
          st == 200 and sid_t, str(b))

    st, b = post({"father_profession": ""}, tab=2, student_id=sid_t,
                 client=admin())
    err = b.get("error") or ""
    check("C1 alive father: profession blanked -> 400 names it",
          st == 400 and "tab 2: father_profession" in err, err)

    st, b = post({"father_profession": "Other", "father_profession_other": ""},
                 tab=2, student_id=sid_t, client=admin())
    err = b.get("error") or ""
    check("C2 profession=Other: father_profession_other required -> 400",
          st == 400 and "tab 2: father_profession_other" in err, err)

    st, b = post({"is_father_alive": "0", "father_profession": "",
                  "guardian_name": "", "guardian_cnic": "",
                  "guardian_relation": "", "guardian_contact": "",
                  "guardian_profession": "", "guardian_income": ""},
                 tab=2, student_id=sid_t, client=admin())
    err = b.get("error") or ""
    check("C3 father dead: guardian block required, father block NOT "
          "(hidden) -> 400 names guardian only",
          st == 400 and "tab 2: guardian_name" in err
          and "father_profession" not in err, err)

    st, b = post({"mother_profession": "Business",
                  "mother_monthly_income": ""},
                 tab=2, student_id=sid_t, client=admin())
    err = b.get("error") or ""
    check("C4 mother Business: monthly income required -> 400 names it",
          st == 400 and "tab 2: mother_monthly_income" in err, err)

    st, b = post({"mother_profession": "Govt Employee", "mother_bps": ""},
                 tab=2, student_id=sid_t, client=admin())
    err = b.get("error") or ""
    check("C5 mother Govt Employee: mother_bps required -> 400 names it",
          st == 400 and "tab 2: mother_bps" in err, err)

    st, b = post({"father_profession": "Govt Employee", "father_bps": ""},
                 tab=2, student_id=sid_t, client=admin())
    err = b.get("error") or ""
    check("C5b father Govt Employee: father_bps required -> 400 names it",
          st == 400 and "tab 2: father_bps" in err, err)

    st, b = post({"father_profession": "Govt Employee", "father_bps": "17"},
                 tab=2, student_id=sid_t, client=admin())
    check("C5c father Govt Employee with father_bps filled -> 200",
          st == 200 and b.get("ok"), str(b))

    _guardian_block = {"is_father_alive": "0",
                       "guardian_name": "GUARDIAN PAYLOAD",
                       "guardian_cnic": "35202-7654321-1",
                       "guardian_relation": "Uncle",
                       "guardian_contact": "0300-1234571",
                       "guardian_profession": "Govt Employee",
                       "guardian_income": "Less than 50,000"}
    st, b = post({**_guardian_block, "guardian_bps": ""},
                 tab=2, student_id=sid_t, client=admin())
    err = b.get("error") or ""
    check("C5d father dead + guardian Govt Employee: guardian_bps required "
          "-> 400 names it",
          st == 400 and "tab 2: guardian_bps" in err, err)

    st, b = post({**_guardian_block, "guardian_bps": "17"},
                 tab=2, student_id=sid_t, client=admin())
    check("C5e father dead + guardian Govt Employee with guardian_bps "
          "filled -> 200",
          st == 200 and b.get("ok"), str(b))

    st, b = post({"is_orphan": "1", "orphan_type": ""},
                 tab=2, student_id=sid_t, client=admin())
    err = b.get("error") or ""
    check("C6 orphan=yes: orphan_type required -> 400 names it",
          st == 400 and "tab 2: orphan_type" in err, err)

    st, b = post({"is_father_alive": "1", "father_profession": "Business",
                  "father_profession_other": "",
                  "mother_profession": "Housewife",
                  "mother_monthly_income": "", "mother_bps": "",
                  "is_orphan": "0", "orphan_type": ""},
                 tab=2, student_id=sid_t, client=admin())
    check("C7 pass case: profession Business (no Other text), mother "
          "Housewife (no income), orphan=no -> 200",
          st == 200 and b.get("ok"), str(b))

    # ==================================================================
    # D. tab-3 branch: Institution Bus -> bus_route required
    # ==================================================================
    st, b = post({**tab3(transport_facility="Institution Bus"),
                  "bus_route": ""}, tab=3)
    err = b.get("error") or ""
    check("D1 Institution Bus without bus_route -> 400 names bus_route",
          st == 400 and "tab 3: bus_route" in err, err)

    st, b = post(tab3(transport_facility="Walking"), tab=3)
    check("D2 walking (no bus): bus_route NOT required -> 200 create",
          st == 200 and b.get("ok"), str(b))
    created.append(b.get("student_id"))

    # ==================================================================
    # E. checkbox-group parity: a rendered [] group counts as filled
    # ==================================================================
    st, b = post({"digital_device_at_home": "1",
                  "digital_device_type[]": "",
                  "internet_at_home": "1"}, tab=7, student_id=sid_a,
                 client=admin())
    check("E1 tab-7 save with empty digital_device_type[] -> 200 "
          "(checkbox groups never required server-side)",
          st == 200 and b.get("ok"), str(b))

    # ==================================================================
    # F. final-submit over the STORED record — the Alisha case
    # ==================================================================
    st, b = create_full(admin(), name="MandGuard Alisha",
                        address_type="Other", address="LEGACY PLACEHOLDER",
                        digital_device_at_home="1",
                        **{"digital_device_type[]": ""})
    sid_f = b.get("student_id")
    created.append(sid_f)
    check("F1 complete Other-branch record created (device=yes, [] empty)",
          st == 200 and sid_f, str(b))

    con = sqlite3.connect(str(DB))
    con.execute("UPDATE students SET address='' WHERE id=?", (sid_f,))
    con.commit()
    con.close()

    ac = admin()
    r = ac.post("/api/final-submit", json={"student_id": sid_f, "data": {}})
    err = (r.get_json() or {}).get("error") or ""
    check("F2 stored-empty address blocks final-submit -> 400 "
          "'tab 1: address'",
          r.status_code == 400 and "Mandatory fields missing" in err
          and "tab 1: address" in err, err)
    check("F3 checkbox parity inside the error: no digital_device/"
          "disability tab listed",
          "tab 7" not in err and "digital_device" not in err
          and "disability" not in err, err)

    st, b = post({"address_type": "Other",
                  "address": "House 19 Street 19"},
                 tab=1, student_id=sid_f, client=admin())
    check("F4 address filled via save-tab -> 200", st == 200 and b.get("ok"),
          str(b))

    r = ac.post("/api/final-submit", json={"student_id": sid_f, "data": {}})
    body = r.get_json() or {}
    check("F5 final-submit after fix -> 200 + submitted + redirect",
          r.status_code == 200 and body.get("ok")
          and str(body.get("redirect", "")).startswith("/success/"), str(body))

    # ==================================================================
    # G. legacy /submit route: same rules, flash + redirect instead of 400
    # ==================================================================
    r = anon().post("/submit",
                    data=form_all(name="MandGuard Legacy Bad",
                                  address_type="Other"),
                    follow_redirects=False)
    con = sqlite3.connect(str(DB))
    n_bad = con.execute(
        "SELECT COUNT(*) FROM students WHERE name='MandGuard Legacy Bad'"
    ).fetchone()[0]
    con.close()
    check("G1 legacy /submit incomplete (Other branch) -> rejected, "
          "no row created",
          n_bad == 0 and r.status_code == 302
          and "/success/" not in (r.headers.get("Location") or ""),
          (n_bad, r.status_code, r.headers.get("Location")))

    r = anon().post("/submit", data=form_all(name="MandGuard Legacy"),
                    follow_redirects=False)
    loc = r.headers.get("Location") or ""
    b_id = loc.rsplit("/", 1)[-1] if loc.rsplit("/", 1)[-1].isdigit() else None
    if b_id:
        created.append(int(b_id))
    check("G2 legacy /submit complete payload -> 302 success + row created",
          r.status_code == 302 and b_id is not None, (r.status_code, loc))

    # ==================================================================
    # H. Admin name-only rename bypasses the mandatory gate (roster
    #    spelling fix, 2026-10-03): login-created rows carry only
    #    name/class/section/roll — an admin may rename them; anyone
    #    else (or any other field mix) still hits the gate.
    # ==================================================================
    sid_h, b_h = mk(name="MandGuard Sparse")
    created.append(sid_h)
    con = sqlite3.connect(str(DB))
    con.execute(
        "UPDATE students SET b_form=NULL, gender=NULL, "
        "birth_province_id=NULL, birth_district_id=NULL, "
        "nationality=NULL, class_id='9', section_id='C' WHERE id=?",
        (sid_h,))
    cls_h, sec_h = con.execute(
        "SELECT class_id, section_id FROM students WHERE id=?",
        (sid_h,)).fetchone()
    con.commit()
    con.close()

    tc_h = app.test_client()
    with tc_h.session_transaction() as s:
        s["role"] = "teacher"
        s["user_name"] = "mand-h"
        s["teacher_class"] = cls_h
        s["teacher_section"] = sec_h
    st, b = post({"name": "MandGuard Sparse Renamed"}, student_id=sid_h,
                 client=tc_h)
    check("H1 teacher (owner) name-only save on sparse row still gated -> 400",
          st == 400 and "Mandatory fields missing" in (b.get("error") or ""),
          str(b))

    st, b = post({"name": "MandGuard Sparse Renamed"}, student_id=sid_h,
                 client=admin())
    check("H2 admin name-only rename on sparse row -> 200",
          st == 200 and b.get("ok"), str(b))

    con = sqlite3.connect(str(DB))
    nm_h = con.execute("SELECT name FROM students WHERE id=?",
                       (sid_h,)).fetchone()[0]
    con.close()
    check("H3 rename stored on sparse row",
          nm_h == "MandGuard Sparse Renamed", nm_h)

    st, b = post({"name": "MandGuard Sparse Renamed", "gender": "Female"},
                 student_id=sid_h, client=admin())
    check("H4 admin save with extra fields on sparse row still gated -> 400",
          st == 400 and "Mandatory fields missing" in (b.get("error") or ""),
          str(b))

    # ==================================================================
    # I. tab-5 IDP conditional mandatory (is_refugee=Yes gates
    #    idp_status_id + is_registered_refugee; registered=Yes gates
    #    refugee_card_number).  Radio values: is_refugee/is_registered_
    #    refugee 1|0, idp_status_id = yaml option label.
    # ==================================================================
    sid_i, b = mk(name="MandGuard IDP")
    created.append(sid_i)
    check("I0 baseline row for tab-5 branches -> 200",
          sid_i is not None, str(b))

    st, b = post({"is_refugee": "1", "idp_status_id": "",
                  "is_registered_refugee": ""},
                 tab=5, student_id=sid_i, client=admin())
    err = b.get("error") or ""
    check("I1 refugee=Yes: idp_status_id + is_registered_refugee blank "
          "-> 400 names both",
          st == 400 and "tab 5: idp_status_id" in err
          and "is_registered_refugee" in err, err)

    st, b = post({"is_refugee": "0", "idp_status_id": "",
                  "is_registered_refugee": ""},
                 tab=5, student_id=sid_i, client=admin())
    check("I2 refugee=No: idp_status_id + is_registered_refugee NOT "
          "required -> 200",
          st == 200 and b.get("ok"), str(b))

    st, b = post({"is_refugee": "1", "idp_status_id": "Registered",
                  "is_registered_refugee": "1", "refugee_card_number": ""},
                 tab=5, student_id=sid_i, client=admin())
    err = b.get("error") or ""
    check("I3 registered=Yes: refugee_card_number required -> 400 names it",
          st == 400 and "tab 5: refugee_card_number" in err, err)

    st, b = post({"is_refugee": "1", "idp_status_id": "Registered",
                  "is_registered_refugee": "1",
                  "refugee_card_number": "12345"},
                 tab=5, student_id=sid_i, client=admin())
    check("I4 refugee=Yes with idp_status + registered + card filled "
          "-> 200",
          st == 200 and b.get("ok"), str(b))

finally:
    # ------------------------------------------------------------------
    # Cleanup: every row this run created; baseline must be restored.
    # ------------------------------------------------------------------
    with app.app_context():
        for sid in [s for s in created if s]:
            row = Student.query.get(sid)
            if row:
                db.session.delete(row)
        for nm in ("MandGuard Legacy", "MandGuard Legacy Bad"):
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
