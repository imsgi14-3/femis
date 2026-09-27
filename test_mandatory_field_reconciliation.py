"""Phase 3B.11 — mandatory-field reconciliation test (diagnosis, characterization).

Audits the ACTUAL current implementation (femis-web/templates/form.html +
femis-web/static/form.js + femis-web/app.py) against the admin-documented FEMIS
requirements — not against any previous phase report.

Each requirement is evaluated as MET or GAP. The assertions lock the CURRENT state,
so a future fix must consciously update this file. Discrepancies are reported here,
NOT fixed (Phase 3B.11 stops after diagnosis).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
HTML = (ROOT / "femis-web" / "templates" / "form.html").read_text(encoding="utf-8")
JS = (ROOT / "femis-web" / "static" / "form.js").read_text(encoding="utf-8")
APP = (ROOT / "femis-web" / "app.py").read_text(encoding="utf-8")

results = []
discrepancies = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


def gap(req, detail):
    discrepancies.append((req, detail))
    print(f"GAP  [{req}] {detail}")


# ---------- parse HTML controls ----------
ctrl = {}
for m in re.finditer(r"<(input|select|textarea)\b([^>]*)>", HTML):
    tag, attrs = m.group(1), m.group(2)
    nm = re.search(r'name="([^"]+)"', attrs)
    if not nm:
        continue
    name = nm.group(1)
    rec = ctrl.setdefault(name, {"required": False, "values": []})
    if re.search(r"\brequired\b", attrs):
        rec["required"] = True
    v = re.search(r'value="([^"]*)"', attrs)
    if v:
        rec["values"].append(v.group(1))


def html_present(name):
    return name in ctrl


def html_required(name):
    return ctrl.get(name, {}).get("required", False)


# ---------- parse JS rules ----------
_mt = re.search(r"var mandatoryByTab = \{(.*?)\n    \};", JS, re.S)
JS_MAND = set()
for _tm in re.finditer(r"(\d+):\s*\[(.*?)\]", _mt.group(1), re.S):
    JS_MAND.update(re.findall(r'"([^"]+)"', _tm.group(2)))

COND = []
for line in JS.splitlines():
    m = re.search(r'\{fields:\s*\[(?P<f>.*?)\],\s*trigger:\s*"(?P<t>[^"]+)",\s*values:\s*\[(?P<v>.*?)\]\}', line)
    if m:
        COND.append((re.findall(r'"([^"]+)"', m.group("f")),
                     m.group("t"), re.findall(r'"([^"]+)"', m.group("v"))))


def cond_rule(field):
    for fields, trig, vals in COND:
        if field in fields:
            return trig, vals
    return None


def js_mandatory(name):
    return name in JS_MAND


# server-side mandatory validation inside api_save_tab / api_final_submit
save_body = APP[APP.find("def api_save_tab"):APP.find("def api_final_submit")]
submit_body = APP[APP.find("def api_final_submit"):APP.find("def api_upload_file")]
server_mandatory = bool(re.search(r"missing|required_fields|mandatory", save_body + submit_body))

print("=" * 78)
print("MANDATORY-FIELD RECONCILIATION (actual current HTML / JS / server)")
print("=" * 78)

# 1. sector + sub-sector when address uses sector
for f in ("sector_id", "sub_sector_id"):
    enforced = js_mandatory(f) or cond_rule(f) is not None or html_required(f)
    check(f"[1] {f}: enforcement state as diagnosed", enforced is False,
          "not required in HTML, not in mandatoryByTab, no conditional rule")
if not (js_mandatory("sector_id") or cond_rule("sector_id")):
    gap("1. sector/sub-sector when address=Sector",
        "address_type=Sector does not make sector_id/sub_sector_id required in JS; "
        "HTML controls have no required attribute")

# 2-3. father income + qualification
check("[2] father_monthly_income is JS-mandatory (tab1)", js_mandatory("father_monthly_income"))
check("[2] father_monthly_income HTML required", html_required("father_monthly_income") is False,
      "HTML has no required attr; JS tab1 is the enforcement layer (documented)")
check("[3] father_qualification is JS-mandatory (tab1)", js_mandatory("father_qualification"))

# 4. orphan type when orphan=yes
check("[4] orphan_type conditional rule exists", cond_rule("orphan_type") == ("is_orphan", ["1"]),
      str(cond_rule("orphan_type")))

# 5. orphan=yes invalid when both parents alive
check("[5] orphan+both-alive guard present in JS",
      "not allowed when both parents are alive" in JS)

# 6. guardian name / cnic / relation / whatsapp
for f in ("guardian_name", "guardian_cnic", "guardian_relation", "guardian_contact"):
    check(f"[6] {f} JS-mandatory (tab1)", js_mandatory(f))
    check(f"[6] {f} HTML required", html_required(f))

# 7. guardian profession + income
for f in ("guardian_profession", "guardian_income"):
    check(f"[7] {f} JS-mandatory (tab1)", js_mandatory(f))

# 8. mother income unless housewife
check("[8] mother-income unless-Housewife rule present", "Housewife" in JS
      and "Mother's Income" in JS)

# 9. date of admission MM/DD/YYYY
has_date_format = bool(re.search(
    r'date_of_admission.*?(\d\{2\}/\d\{2\}/\d\{4\}|MM/DD/YYYY|Date\.parse|isValidDate)',
    JS, re.S)) and bool(re.search(r'\d\{2\}/\d\{2\}/\d\{4\}', JS))
check("[9] date_of_admission is JS-mandatory (presence only)", js_mandatory("date_of_admission"))
check("[9] MM/DD/YYYY format rule absent (as diagnosed)", has_date_format is False,
      "no format/regex validation found for date_of_admission")
if not has_date_format:
    gap("9. date of admission MM/DD/YYYY",
        "presence-only validation; any date string accepted, format never checked "
        "in HTML (no pattern attr) or JS or server")

# 10. class admitted ranges 1-5 / 6-10
check("[10] class-admitted range logic 1-5 / 6-10 present",
      "var lo = classNum <= 5 ? 1 : 6;" in JS and "var hi = classNum <= 5 ? 5 : 10;" in JS)
check("[10] generated class-admitted radios are required", 'input.required = true;' in JS)
check("[10] class_admitted_id is JS-mandatory (tab2)", js_mandatory("class_admitted_id"))

# 11. Primary Education Completion NOT mandatory
check("[11] primary_education_completion_years not HTML-required",
      html_required("primary_education_completion_years") is False)
check("[11] primary_education_completion_years not JS-mandatory",
      js_mandatory("primary_education_completion_years") is False)

# 12. meal program
check("[12] school_meal_program_availing JS-mandatory (tab2)",
      js_mandatory("school_meal_program_availing"))
check("[12] school_meal_program_availing HTML present", html_present("school_meal_program_availing"))

# 13-14. transport facility + Bus renamed to Institution Bus
check("[13] transport_facility JS-mandatory (tab2)", js_mandatory("transport_facility"))
check("[13] transport_facility HTML present", html_required("transport_facility"))
vals = ctrl.get("transport_facility", {}).get("values", [])
check("[14] transport values include 'Institution Bus'", "Institution Bus" in vals, str(vals))
check("[14] no radio value='Bus' remains (renamed)", "Bus" not in vals, str(vals))
check("[14] JS still tolerates legacy 'Bus' trigger for bus_route",
      cond_rule("bus_route") == ("transport_facility", ["Bus", "Institution Bus"]),
      str(cond_rule("bus_route")))

# 15-16. scholarship + co-curricular
check("[15] scholarship JS-mandatory (tab2)", js_mandatory("scholarship"))
check("[15] scholarship_details conditional on scholarship=yes",
      cond_rule("scholarship_details") == ("scholarship", ["1"]))
check("[16] cocurricular_activities JS-mandatory (tab2)", js_mandatory("cocurricular_activities"))
check("[16] cocurricular_details conditional on activity=yes",
      cond_rule("cocurricular_details") == ("cocurricular_activities", ["1"]))

# 17. IDP / refugee status when applicable
check("[17] is_refugee JS-mandatory (tab4)", js_mandatory("is_refugee"))
check("[17] idp_status_id conditional on is_refugee=yes",
      cond_rule("idp_status_id") == ("is_refugee", ["1"]))
check("[17] is_registered_refugee conditional on is_refugee=yes",
      cond_rule("is_registered_refugee") == ("is_refugee", ["1"]))
check("[17] refugee_card_number conditional on registered=yes",
      cond_rule("refugee_card_number") == ("is_registered_refugee", ["1"]))

# 18-19. major / mental disability
check("[18] has_major_disability JS-mandatory (tab5)", js_mandatory("has_major_disability"))
check("[18] disability_types conditional on major=yes",
      cond_rule("disability_types[]") == ("has_major_disability", ["1"]),
      str(cond_rule("disability_types[]")))
check("[19] has_mental_disability JS-mandatory (tab5)", js_mandatory("has_mental_disability"))
check("[19] mental_disability_type conditional on mental=yes",
      cond_rule("mental_disability_type") == ("has_mental_disability", ["1"]))

# 20-22. vision block
check("[20] visually_fit JS-mandatory (tab5)", js_mandatory("visually_fit"))
check("[21] uses_glasses JS-mandatory (tab5)", js_mandatory("uses_glasses"))
check("[22] glass_prescription conditional on visually_fit=no",
      cond_rule("glass_prescription") == ("visually_fit", ["0"]),
      str(cond_rule("glass_prescription")))

# 23-24. hearing block
check("[23] has_hearing_difficulties JS-mandatory (tab5)",
      js_mandatory("has_hearing_difficulties"))
check("[24] uses_hearing_aid conditional on hearing difficulty=yes",
      cond_rule("uses_hearing_aid") == ("has_hearing_difficulties", ["1"]),
      str(cond_rule("uses_hearing_aid")))

# 25-27. walking / listening / aids
check("[25] difficulty_listening JS-mandatory (tab5)", js_mandatory("difficulty_listening"))
check("[26] difficulty_walking JS-mandatory (tab5)", js_mandatory("difficulty_walking"))
check("[27] uses_crutches_walker JS-mandatory (tab5)", js_mandatory("uses_crutches_walker"))

# 28-30. digital block
check("[28] digital_device_at_home JS-mandatory (tab6)",
      js_mandatory("digital_device_at_home"))
check("[29] digital_device_type[] conditional on device access=yes",
      cond_rule("digital_device_type[]") == ("digital_device_at_home", ["1"]),
      str(cond_rule("digital_device_type[]")))
check("[30] internet_at_home JS-mandatory (tab6)", js_mandatory("internet_at_home"))

# ---- cross-cutting facts ----
check("[X] no server-side mandatory validation in save/submit routes",
      server_mandatory is False,
      "only B-Form uniqueness is enforced server-side")
if not server_mandatory:
    gap("X. server-side validation",
        "every mandatory rule is client-side only; /api/save-tab and /api/final-submit "
        "accept arbitrary partial payloads (bot/API clients bypass HTML+JS entirely)")

html_only = [n for n, r in sorted(ctrl.items())
             if r["required"] and n not in JS_MAND
             and not any(n in f for f, _, _ in COND)]
check("[X] HTML-required-but-not-JS list captured",
      set(html_only) >= {"b_form", "house", "street"},
      f"html-only required: {html_only}")
if html_only:
    gap("X. HTML-only required attributes",
        f"{html_only} carry required= but are not in JS validateTab, and the JS "
        "intercepts submit (preventDefault) so native validation never runs")

print()
print("=" * 78)
print(f"DISCREPANCIES FOUND: {len(discrepancies)}")
for req, detail in discrepancies:
    print(f"  - {req}: {detail}")
print("=" * 78)

passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
