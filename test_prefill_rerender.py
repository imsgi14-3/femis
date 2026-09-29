"""Pre-fill re-render regression: F1 sub-sector, F2 birth district, F3 checkbox arrays.

Requires the dev server on :5000 (`python femis-web/app.py`) and Playwright +
Chromium. Verifies that saved values re-render after reload AND survive
subsequent saves (no silent overwrite), while intentional clearing still works.

Covers the three defects found in phase 3B.12:
  F1  sub_sector_id re-render race (sector -> sub-sector cascade pending value)
  F2  birth_district_id re-render race (province -> district cascade pending value)
  F3  checkbox arrays (digital_device_type[], disability_types[]) never re-checked
"""
import json
import pathlib
import sqlite3
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from form_payloads import tab1  # noqa: E402  complete tab-1 fixture (mandatory twin)

BASE = "http://127.0.0.1:5000"
DB = pathlib.Path(__file__).resolve().parent / "femis-web" / "instance" / "femis.db"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" - {detail}" if detail else ""))


def q(sql, args=(), one=True):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        con.close()


def dbdelete(name):
    con = sqlite3.connect(str(DB))
    try:
        con.execute("DELETE FROM students WHERE name=?", (name,))
        con.commit()
    finally:
        con.close()


FILL_JS = """
(spec) => {
  const out = {};
  for (const fname of spec.fields) {
    const radios = [...document.querySelectorAll('input[type=radio][name="' + fname + '"]')];
    if (radios.length) {
      if (!radios.some(r => r.checked)) {
        const t = radios[0]; t.checked = true; t.dispatchEvent(new Event('change', {bubbles: true}));
      }
      out[fname] = (radios.find(r => r.checked) || {}).value; continue;
    }
    const sel = document.querySelector('select[name="' + fname + '"]');
    if (sel) {
      if (!sel.value) { const o = [...sel.options].find(o => o.value !== ''); if (o) sel.value = o.value; }
      sel.dispatchEvent(new Event('change', {bubbles: true}));
      out[fname] = sel.value; continue;
    }
    const el = document.querySelector('input:not([type=radio]):not([type=checkbox])[name="' + fname + '"], textarea[name="' + fname + '"]');
    if (el) {
        if (!el.value) {
        if (el.type === 'date') el.value = '2015-01-01';
        else if (el.classList && el.classList.contains('fp-date')) el.value = '01/01/2015';
        else if (fname.indexOf('cnic') >= 0 || fname.indexOf('b_form') >= 0) el.value = '3520212345678';
        else if (fname.indexOf('contact') >= 0 || fname.indexOf('phone') >= 0) el.value = '0300-1234567';
        else if (el.type === 'email') el.value = 'probe@example.com';
        else if (el.type === 'number') el.value = '1';
        else el.value = 'Probe';
      }
      el.dispatchEvent(new Event('input', {bubbles: true}));
      out[fname] = el.value; continue;
    }
    out[fname] = 'NO_CONTROL';
  }
  return out;
}
"""

READ_JS = """
(names) => {
  const out = {};
  for (const name of names) {
    const radios = [...document.querySelectorAll('input[type=radio][name="' + name + '"]')];
    if (radios.length) { const c = radios.find(r => r.checked); out[name] = c ? c.value : ''; continue; }
    const cbs = [...document.querySelectorAll('input[type=checkbox][name="' + name + '"]')];
    if (cbs.length) { out[name] = cbs.filter(c => c.checked).map(c => c.value).join(','); continue; }
    const sel = document.querySelector('select[name="' + name + '"]');
    if (sel) { out[name] = sel.value; continue; }
    const el = document.querySelector('[name="' + name + '"]');
    out[name] = el ? (el.value ?? '') : '__NO_CONTROL__';
  }
  return out;
}
"""

SET_JS = """
(obj) => {
  const out = {};
  for (const name of Object.keys(obj)) {
    const val = String(obj[name]);
    const radios = [...document.querySelectorAll('input[type=radio][name="' + name + '"]')];
    if (radios.length) {
      if (val === '') { radios.forEach(r => { r.checked = false; }); out[name] = 'cleared'; continue; }
      const t = radios.find(r => r.value === val);
      if (!t) { out[name] = 'RADIO_VALUE_MISSING'; continue; }
      radios.forEach(r => { r.checked = false; });
      t.checked = true; t.dispatchEvent(new Event('change', {bubbles: true}));
      out[name] = 'ok'; continue;
    }
    const sel = document.querySelector('select[name="' + name + '"]');
    if (sel) {
      sel.value = val; sel.dispatchEvent(new Event('change', {bubbles: true}));
      out[name] = sel.value === val ? 'ok' : 'SELECT_VALUE_MISSING'; continue;
    }
    const el = document.querySelector('[name="' + name + '"]');
    if (el && el.type !== 'radio' && el.type !== 'checkbox') {
      el.value = val;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      out[name] = 'ok'; continue;
    }
    out[name] = 'NO_CONTROL';
  }
  return out;
}
"""

CLEAR_CHECKBOXES_JS = """
(name) => {
  const cbs = [...document.querySelectorAll('input[type=checkbox][name="' + name + '"]')];
  cbs.forEach(cb => { cb.checked = false; });
  if (cbs[0]) cbs[0].dispatchEvent(new Event('change'));
  return cbs.length;
}
"""

# mandatoryByTab[0] (form.js) minus the fields prefilled from the fixture.
# b_form + present_* are newly mandatory (misalignment report §6-P1.1);
# house/street + present_house/present_street joined them 2026-09-29 (address
# family visibility-gated); the present-address sub-sector needs its own fill
# after the cascade resolves.
TAB1_FILL = ["name", "is_bform_available", "b_form", "gender", "date_of_birth", "nationality",
             "house", "street", "contact_number", "city_id", "religion", "language_id", "email"]
TAB1_PRESENT = ["present_address_type", "present_sector_id", "present_house", "present_street"]
TAB1_PRESENT_SUB = ["present_sub_sector_id"]
# Final submit validates every tab (§8-8.2) — each tab must be filled + saved.
TAB2_FILL = ["father_name", "father_cnic", "is_father_alive", "father_contact",
             "father_qualification", "father_profession", "father_monthly_income",
             "mother_name", "is_mother_alive", "mother_contact", "mother_profession",
             "mother_qualification", "mother_bps", "mother_monthly_income"]
TAB3_FILL = ["class_id", "section_id", "date_of_admission", "class_admitted_id",
             "medium_of_instruction", "mode_of_study", "admission_number", "shift",
             "total_siblings", "school_meal_program_availing",
             "transport_facility", "bus_route", "scholarship", "scholarship_details",
             "cocurricular_activities", "cocurricular_details"]
TAB4_FILL = ["emergency_name", "emergency_contact", "emergency_relation"]
TAB5_FILL = ["is_refugee", "idp_status_id", "is_registered_refugee", "refugee_card_number"]  # UI tab-5 = IDPs (mandatoryByTab[4])
TAB6_FILL = ["has_major_disability", "has_mental_disability", "mental_disability_type",
             "visually_fit", "uses_glasses",
             "has_hearing_difficulties", "uses_hearing_aid", "difficulty_listening",
             "difficulty_walking", "uses_crutches_walker", "difficulty_seeing_board",
             "difficulty_reading_writing", "difficulty_remembering", "difficulty_concentrating"]
TAB7_FILL = ["digital_device_at_home", "internet_at_home"]

PROBE = "P3B13 PREFILL PROBE"


def main():
    try:
        urllib.request.urlopen(BASE + "/login", timeout=5)
    except Exception as e:
        print(f"SKIP: dev server not reachable on {BASE} ({e})")
        sys.exit(2)

    from playwright.sync_api import sync_playwright

    dbdelete(PROBE)
    # Create branch carries a complete tab-1 payload — the server mandatory
    # twin (femis-web/mandatory.py) rejects partial creates with 400; the
    # suite-specific re-render values below override the fixture defaults.
    data = tab1(name=PROBE, class_id="9", section_id="A", roll_no="P3BP",
                sector_id="34", sub_sector_id="I-14/3",
                birth_district_id="Faisalabad",
                date_of_birth="01/01/2015",
                digital_device_type="Mobile Phone,Laptop",
                disability_types="Visual,Hearing")
    req = urllib.request.Request(
        BASE + "/api/save-tab",
        data=json.dumps({"tab": 1, "student_id": None, "data": data}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    sid = json.loads(urllib.request.urlopen(req, timeout=15).read().decode()).get("student_id")
    check("fixture row created", bool(sid), str(sid))
    if not sid:
        sys.exit(1)

    dialogs = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = ctx.new_page()
            page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))

            r = ctx.request.post(BASE + "/login", form={"role": "student", "name": PROBE,
                                                         "class_id": "9", "section": "A",
                                                         "roll_no": "P3BP"})
            check("student login session", r.status in (200, 302), str(r.status))
            page.goto(f"{BASE}/form/{sid}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(900)

            dom = page.evaluate(READ_JS, ["birth_district_id", "sub_sector_id",
                                          "digital_device_type[]", "disability_types[]"])
            check("F2: birth_district_id re-renders ('Faisalabad')",
                  dom.get("birth_district_id") == "Faisalabad", str(dom))
            check("F1: sub_sector_id re-renders ('I-14/3')",
                  dom.get("sub_sector_id") == "I-14/3", str(dom))
            vis = page.evaluate("() => !!document.querySelector('#sub_sector_group').offsetParent")
            check("F1: sub_sector group visible after reload (cascade finished, not hidden)",
                  vis is True, str(vis))
            check("F3: digital_device_type[] re-checked",
                  dom.get("digital_device_type[]") == "Mobile Phone,Laptop", str(dom))
            check("F3: disability_types[] re-checked",
                  dom.get("disability_types[]") == "Visual,Hearing", str(dom))

            # --- tab-1 save: validation passes, stored values preserved ---
            fill = page.evaluate(FILL_JS, {"fields": TAB1_FILL, "set": {}})
            check("tab-1 mandatory filled",
                  all(v not in ("NO_CONTROL", "") for v in fill.values()), str(fill))
            # present-address cascade: address type + sector first, sub-sector
            # only once /api/sub-sectors has resolved
            page.evaluate(FILL_JS, {"fields": TAB1_PRESENT, "set": {}})
            page.wait_for_timeout(700)
            fill_sub = page.evaluate(FILL_JS, {"fields": TAB1_PRESENT_SUB, "set": {}})
            check("tab-1 present sub-sector control reachable after cascade",
                  fill_sub.get("present_sub_sector_id") != "NO_CONTROL", str(fill_sub))
            dialogs.clear()
            with page.expect_response(lambda x: "api/save-tab" in x.url, timeout=20000) as ri:
                page.click("#save-next-btn")
            check("F2: tab-1 save NOT blocked (save-tab fired)",
                  ri.value.json().get("ok") is True, str(ri.value.json()))
            check("no validation alert on tab-1 save", not dialogs, str(dialogs))

            row = q("SELECT birth_district_id, sub_sector_id, digital_device_type, date_of_birth FROM students WHERE id=?", (sid,))
            check("F2: district preserved through save", row["birth_district_id"] == "Faisalabad",
                  repr(row["birth_district_id"]))
            check("F1: sub_sector preserved through save (no silent wipe)",
                  row["sub_sector_id"] == "I-14/3", repr(row["sub_sector_id"]))
            check("control: digital_device untouched by tab-1 save",
                  row["digital_device_type"] == "Mobile Phone,Laptop", repr(row["digital_device_type"]))
            check("date_of_birth posted MM/DD/YYYY stored as ISO",
                  row["date_of_birth"] == "2015-01-01", repr(row["date_of_birth"]))

            # --- tabs 2-6: fill + save each (auto-advance after every save) ---
            # Final submit now validates EVERY tab (§8-8.2), so each must pass
            # its own Save & Next validation first.
            for idx, fields in [(2, TAB2_FILL), (3, TAB3_FILL), (4, TAB4_FILL),
                                (5, TAB5_FILL), (6, TAB6_FILL)]:
                page.wait_for_selector(f"#tab-{idx}.active", timeout=5000)
                fx = page.evaluate(FILL_JS, {"fields": fields, "set": {}})
                check(f"tab-{idx} mandatory filled",
                      all(v not in ("NO_CONTROL", "") for v in fx.values()), str(fx))
                dialogs.clear()
                with page.expect_response(lambda x: "api/save-tab" in x.url, timeout=20000) as ri:
                    page.click("#save-next-btn")
                check(f"tab-{idx} save ok", ri.value.json().get("ok") is True,
                      str(ri.value.json()))
                check(f"no validation alert on tab-{idx} save", not dialogs, str(dialogs))

            # --- tab-7 save (final-submit): validates all tabs, keeps checkbox values ---
            page.wait_for_selector("#tab-7.active", timeout=5000)
            fill7 = page.evaluate(FILL_JS, {"fields": TAB7_FILL, "set": {}})
            check("tab-7 mandatory filled",
                  all(v not in ("NO_CONTROL", "") for v in fill7.values()), str(fill7))
            dialogs.clear()
            with page.expect_response(lambda x: "api/final-submit" in x.url, timeout=20000) as ri:
                page.click("#save-next-btn")
            check("tab-7 save ok (final-submit, all tabs validated)", ri.value.status == 200, str(ri.value.status))
            check("no validation alert on tab-7 save", not dialogs, str(dialogs))

            row = q("SELECT digital_device_type, disability_types, sub_sector_id, birth_district_id "
                    "FROM students WHERE id=?", (sid,))
            check("F3: digital_device_type preserved through tab-7 save (no silent wipe)",
                  row["digital_device_type"] == "Mobile Phone,Laptop", repr(row["digital_device_type"]))
            check("control: disability_types preserved", row["disability_types"] == "Visual,Hearing",
                  repr(row["disability_types"]))
            check("control: sub_sector still intact after tab-7 save",
                  row["sub_sector_id"] == "I-14/3", repr(row["sub_sector_id"]))
            check("control: district still intact after tab-7 save",
                  row["birth_district_id"] == "Faisalabad", repr(row["birth_district_id"]))

            # --- reload after both saves: values still render ---
            page.goto(f"{BASE}/form/{sid}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(900)
            dom = page.evaluate(READ_JS, ["birth_district_id", "sub_sector_id", "digital_device_type[]"])
            check("re-render after tab-1 + tab-7 saves (district/sub-sector/devices)",
                  dom.get("birth_district_id") == "Faisalabad"
                  and dom.get("sub_sector_id") == "I-14/3"
                  and dom.get("digital_device_type[]") == "Mobile Phone,Laptop", str(dom))

            # --- intentional set + clear still works (tab-1: blood_group) ---
            # sub_sector_id is now portal-mandatory while its group is visible,
            # so the clear-probe uses a non-mandatory field instead (§6-P1.1).
            setres = page.evaluate(SET_JS, {"blood_group": "B+"})
            check("blood_group set applied", setres.get("blood_group") == "ok", str(setres))
            dialogs.clear()
            with page.expect_response(lambda x: "api/save-tab" in x.url, timeout=20000) as ri:
                page.click("#save-next-btn")
            check("tab-1 save after set ok", ri.value.json().get("ok") is True,
                  str(ri.value.json()))
            check("no validation alert on set-save", not dialogs, str(dialogs))
            row = q("SELECT blood_group FROM students WHERE id=?", (sid,))
            check("set of blood_group persists", row["blood_group"] == "B+", repr(row["blood_group"]))

            page.click('a[href="#tab-1"]')
            page.wait_for_selector("#tab-1.active", timeout=5000)
            setres = page.evaluate(SET_JS, {"blood_group": ""})
            check("clear blood_group applied", setres.get("blood_group") == "ok", str(setres))
            dialogs.clear()
            with page.expect_response(lambda x: "api/save-tab" in x.url, timeout=20000) as ri:
                page.click("#save-next-btn")
            check("tab-1 save after clear ok", ri.value.json().get("ok") is True)
            check("no validation alert on clear-save", not dialogs, str(dialogs))
            row = q("SELECT blood_group FROM students WHERE id=?", (sid,))
            check("intentional clear of blood_group persists",
                  (row["blood_group"] or "") == "", repr(row["blood_group"]))

            # --- intentional clear of checkbox array (tab-7) ---
            page.click('a[href="#tab-7"]')
            page.wait_for_selector("#tab-7.active", timeout=5000)
            n = page.evaluate(CLEAR_CHECKBOXES_JS, "digital_device_type[]")
            check("unchecked digital_device boxes", n >= 2, str(n))
            dialogs.clear()
            with page.expect_response(lambda x: "api/final-submit" in x.url, timeout=20000) as ri:
                page.click("#save-next-btn")
            check("tab-7 save after clear ok", ri.value.status == 200, str(ri.value.status))
            check("no validation alert on checkbox clear-save", not dialogs, str(dialogs))
            row = q("SELECT digital_device_type FROM students WHERE id=?", (sid,))
            check("intentional clear of digital_device_type persists",
                  (row["digital_device_type"] or "") == "", repr(row["digital_device_type"]))

            browser.close()
    finally:
        dbdelete(PROBE)
        left = q("SELECT count(*) c FROM students WHERE name=?", (PROBE,))["c"]
        ids = [r["id"] for r in q("SELECT id FROM students ORDER BY id", one=False)]
        check("probe deleted, canonical 6 rows remain",
              left == 0 and ids == [3, 4, 6, 8, 9, 10], f"left={left} ids={ids}")

    passed = sum(1 for _, ok in results if ok)
    print("=" * 60)
    print(f"{passed}/{len(results)} checks passed")
    print("=" * 60)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
