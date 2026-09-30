"""Mandatory-field reconciliation test — locks the POST-FIX state.

Audits the ACTUAL current implementation (femis-web/templates/form.html +
femis-web/static/form.js + femis-web/app.py) against the admin-documented FEMIS
requirements — not against any previous phase report.

History: written in Phase 3B.11 as a diagnosis that locked the GAP state; updated
alongside the misalignment-report §6 fixes (visibility-gated validateTab, guardian
gating, hearing-aid parity, mother-income asterisk, all-tabs final submit), then
the 2026-09-29 failed-job fixes (address family + Other-profession conditionals +
email format validation — FEMIS blocked empty address/present_address for
Address Type=Other, empty mother/father/guardian_profession_other for
profession=Other, and email 'Nil' at submit while PA Save & Next let them pass).
2026-09-29 (later): the server-side twin landed in femis-web/mandatory.py —
[X] now locks the save/final-submit/legacy-submit wiring and the exact rule
parity between the client lists and the server spec.
2026-09-30: the is_bform_available yes/no question was removed from the PA
form — the server forces the flag to '1' in _map_form_data, b_form became
unconditional on BOTH sides, and no bot job is queued without a B-Form
number ([Xb] locks it).
2026-09-30 (later): father_bps and guardian_bps became mandatory when the
respective profession is Govt Employee — JS conditional rules + server
RULES + red asterisks, mirroring the existing mother_bps branch ([3c]).
2026-09-30 (later): the 5 name inputs became letters-and-spaces-only on
both sides ("no period no number", [39]) and the Village / Housing
Society labels gained their missing red asterisks ([38]).
2026-09-30 (later): the student email is no longer mandatory ([40]) - it
was dropped from mandatoryByTab[0], ALWAYS[1] and the HTML required attr
+ red asterisk; a filled value must still be @-shaped.
Each requirement is evaluated as MET or GAP; further fixes must consciously
update this file.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
HTML = (ROOT / "femis-web" / "templates" / "form.html").read_text(encoding="utf-8")
JS = (ROOT / "femis-web" / "static" / "form.js").read_text(encoding="utf-8")
APP = (ROOT / "femis-web" / "app.py").read_text(encoding="utf-8")
MAPPING = (ROOT / "config" / "field_mapping.yaml").read_text(encoding="utf-8")

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


# server-side twin of validateTab (femis-web/mandatory.py): wiring inside
# api_save_tab / api_final_submit and the legacy /submit route
save_body = APP[APP.find("def api_save_tab"):APP.find("def api_final_submit")]
submit_body = APP[APP.find("def api_final_submit"):APP.find("def api_upload_file")]
legacy_body = APP[APP.find("def submit("):]

print("=" * 78)
print("MANDATORY-FIELD RECONCILIATION (actual current HTML / JS / server)")
print("=" * 78)

# 1. sector + sub-sector when address uses sector (FIXED: visibility-gated mandatory)
for f in ("sector_id", "sub_sector_id"):
    check(f"[1] {f} JS-mandatory (tab0, visibility-gated)", js_mandatory(f))
check("[1] b_form JS-mandatory (tab0, visibility-gated)", js_mandatory("b_form"))
check("[1] present_* address trio JS-mandatory (tab0, visibility-gated)",
      all(js_mandatory(f) for f in
          ("present_address_type", "present_sector_id", "present_sub_sector_id")))
check("[1] sub-sector group gated on address type = Sector (temp + present)",
      JS.count('if (subSectorDiv) subSectorDiv.style.display = val === "Sector" ? "block" : "none";') == 2,
      "both address_type toggles show #sub_sector_group / #present_sub_sector_group for Sector")
check("[1] red asterisk on all 4 sector/sub-sector labels",
      HTML.count('<label class="form-label">Sector <span class="text-danger">*</span></label>') == 2 and
      HTML.count('<label class="form-label">Sub Sector <span class="text-danger">*</span></label>') == 2,
      "labels visibly marked mandatory when the group is shown")
check("[1] shift JS-mandatory (tab2)", js_mandatory("shift"))
check("[1] validateTab skips hidden fields",
      "isHiddenWithin" in JS and "isHiddenWithin(pane, ctl.els[0])" in JS,
      "hidden-group fields are not enforced")
check("[1] final submit validates every tab",
      'for (var t = 0; t < tabIds.length; t++)' in JS and
      "validateTab(t, document.getElementById(tabIds[t]))" in JS)

# 2-3. father income + qualification
check("[2] father_monthly_income is JS-mandatory (tab1)", js_mandatory("father_monthly_income"))
check("[2] father_monthly_income HTML required", html_required("father_monthly_income") is False,
      "HTML has no required attr; JS tab1 is the enforcement layer (documented)")
check("[3] father_qualification is JS-mandatory (tab1)", js_mandatory("father_qualification"))

# 3b. mother qualification mandatory + mother BPS only for Govt Employee
check("[3b] mother_qualification is JS-mandatory (tab1)", js_mandatory("mother_qualification"))
check("[3b] mother_qualification label carries red asterisk",
      '<label class="form-label">Mother\'s Qualification <span class="text-danger">*</span></label>' in HTML)
check("[3b] mother_bps conditional on mother_profession=Govt Employee",
      cond_rule("mother_bps") == ("mother_profession", ["Govt Employee"]),
      str(cond_rule("mother_bps")))
check("[3b] mother_bps group gated on profession=Govt Employee",
      'id="mother_bps_group"' in HTML and
      'selectToggle("mother_profession", "mother_bps_group", ["Govt Employee"])' in JS)
check("[3b] mother_bps label carries red asterisk (visible only when required)",
      '<label class="form-label">Mother\'s BPS <span class="text-danger">*</span></label>' in HTML)

# 3c. father / guardian BPS mandatory only for Govt Employee (2026-09-30 —
#     same branch as mother_bps; alive-gating rides on group visibility,
#     the server rules carry the is_father_alive / is_mother_alive gate)
check("[3c] father_bps conditional on father_profession=Govt Employee",
      cond_rule("father_bps") == ("father_profession", ["Govt Employee"]),
      str(cond_rule("father_bps")))
check("[3c] father_bps group gated on profession=Govt Employee",
      'id="father_bps_group"' in HTML and
      'getElementById("father_bps_group")' in JS and
      'profSel.value === "Govt Employee" ? "block" : "none"' in JS)
check("[3c] father_bps label carries red asterisk (visible only when required)",
      '<label class="form-label">Father\'s BPS <span class="text-danger">*</span></label>' in HTML)
check("[3c] guardian_bps conditional on guardian_profession=Govt Employee",
      cond_rule("guardian_bps") == ("guardian_profession", ["Govt Employee"]),
      str(cond_rule("guardian_bps")))
check("[3c] guardian_bps label carries red asterisk (visible only when required)",
      '<label class="form-label">Guardian BPS <span class="text-danger">*</span></label>' in HTML)

# 4. orphan type when orphan=yes
check("[4] orphan_type conditional rule exists", cond_rule("orphan_type") == ("is_orphan", ["1"]),
      str(cond_rule("orphan_type")))

# 5. orphan=yes invalid when both parents alive
check("[5] orphan+both-alive guard present in JS",
      "not allowed when both parents are alive" in JS)
check("[5b] orphan=Yes auto-corrected at selection time (both parents alive)",
      'Is Orphan cannot be Yes when both parents are alive.' in JS and
      "input[name=\"is_orphan\"]" in JS,
      "change listener flips orphan back to No + alert")

# 6. guardian name / cnic / relation / whatsapp (FIXED: conditional on father not alive)
for f in ("guardian_name", "guardian_cnic", "guardian_relation", "guardian_contact"):
    check(f"[6] {f} conditional on is_father_alive=no (tab1)",
          cond_rule(f) == ("is_father_alive", ["0"]), str(cond_rule(f)))
    check(f"[6] {f} HTML required", html_required(f))
check("[6] guardian block visibility wired (father not alive)",
      'id="guardian_group"' in HTML and
      'radioToggle("is_father_alive", "guardian_group", ["0"])' in JS)

# 7. guardian profession + income
for f in ("guardian_profession", "guardian_income"):
    check(f"[7] {f} conditional on is_father_alive=no (tab1)",
          cond_rule(f) == ("is_father_alive", ["0"]), str(cond_rule(f)))
check("[7] guardian_bps visibility wired (guardian profession = Govt Employee)",
      'id="guardian_bps_group"' in HTML and
      'selectToggle("guardian_profession", "guardian_bps_group", ["Govt Employee"])' in JS)

# 8. mother income unless housewife (FIXED: asterisk clears + visibility-aware guard)
check("[8] mother-income unless-Housewife rule present", "Housewife" in JS
      and "Mother's Income" in JS)
check("[8] asterisk is conditional (id present, hidden by default)",
      'id="mother_income_required"' in HTML and
      'style="display:none;">*</span>' in HTML)
check("[8] asterisk toggler wired to mother_profession",
      "mother_income_required" in JS and "toggleStar" in JS)
check("[8] guard skips when the mother group is hidden",
      "isHiddenWithin(pane, motherProf)" in JS)

# 9. dates — flatpickr calendar with explicit MM/DD/YYYY display (PA-portal
#    directive: calendar input in the portal's mm/dd/yyyy format to remove
#    day/month ambiguity; storage stays ISO, the server normalizes posts)
date_picker = all(
    re.search(r'<input type="text" class="form-control fp-date" name="%s"' % f, HTML)
    for f in ("date_of_birth", "date_of_admission"))
has_date_format = bool(re.search(r'date_of_admission.*?MM/DD/YYYY', JS, re.S)) and bool(
    re.search(r'\d{2}/\d{2}/\d{4}', JS))
check("[9] date_of_admission is JS-mandatory (presence only)", js_mandatory("date_of_admission"))
check("[9] date_of_birth + date_of_admission render as flatpickr calendars",
      date_picker, "type=text class=fp-date on both inputs")
check("[9] MM/DD/YYYY display format configured in form.js", has_date_format,
      "comment names date_of_admission + MM/DD/YYYY with literal example date")
check("[9] server normalizes posted MM/DD/YYYY -> ISO on save",
      APP.count("_normalize_date_value") >= 3, "_map_form_data + /submit")
gap("9. dates (contract updated)",
    "flatpickr enforces MM/DD/YYYY client-side (calendar + onClose guard); "
    "app.py _normalize_date_value stores ISO; raw strings still pass through "
    "when unparseable, so legacy/API callers keep working")

# 9b. total siblings — number spinner like siblings_same_institution, no 01/02
check("[9b] total_siblings is a number spinner (type=number, min 0, step 1)",
      re.search(r'<input type="number" class="form-control" name="total_siblings" min="0" step="1"',
                HTML) is not None)
check("[9b] total_siblings strips non-digits + leading zeros (only 123, not 01)",
      'input[name="total_siblings"]' in JS and 'replace(/^0+(?=[0-9])/, "")' in JS)

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

# 23-24. hearing block (FIXED: uses_hearing_aid unconditional + always visible)
check("[23] has_hearing_difficulties JS-mandatory (tab5)",
      js_mandatory("has_hearing_difficulties"))
check("[24] uses_hearing_aid JS-mandatory (tab5, unconditional)",
      js_mandatory("uses_hearing_aid"), str(cond_rule("uses_hearing_aid")))
check("[24] uses_hearing_aid group always visible",
      'id="hearing_aid_group"' in HTML and
      not re.search(r'id="hearing_aid_group"[^>]*style="display:none', HTML))
check("[24] hearing_aid_details trigger = has_hearing_difficulties=yes",
      'radioToggle("has_hearing_difficulties", "hearing_aid_details_group", ["1"])' in JS
      and 'radioToggle("uses_hearing_aid", "hearing_aid_details_group"' not in JS)

# 24b. parent-contact conditionals (report §6-P1.5)
check("[24b] father_contact conditional on father alive",
      cond_rule("father_contact") == ("is_father_alive", ["1"]), str(cond_rule("father_contact")))
check("[24b] mother_contact conditional on mother alive",
      cond_rule("mother_contact") == ("is_mother_alive", ["1"]), str(cond_rule("mother_contact")))

# 24c. orphan type group visibility (shows only when is_orphan=yes)
check("[24c] orphan_type_group visibility wired",
      'id="orphan_type_group"' in HTML and
      'radioToggle("is_orphan", "orphan_type_group", ["1"])' in JS)

# 24d. portal visibility parity gates (report §6-P3)
check("[24d] girls_stipend gated on gender=Female",
      'id="girls_stipend_group"' in HTML and
      'selectToggle("gender", "girls_stipend_group", ["Female"])' in JS)
check("[24d] domicile gated on nationality=Pakistani",
      'id="domicile_fields"' in HTML and
      'selectToggle("nationality", "domicile_fields", ["Pakistani"])' in JS)
check("[24d] is_hafiz gated on religion=Muslim",
      'id="hafiz_group"' in HTML and
      'selectToggle("religion", "hafiz_group", ["Muslim"])' in JS)

# 24e. is_hafiz is NOT mandatory (portal required=false in every capture)
_hafiz_req = []
for _hm in re.finditer(r"(?m)^(\s*)is_hafiz:\s*$", MAPPING):
    _req = [l.strip() for l in MAPPING[_hm.end():].splitlines()[:8] if "required" in l]
    _hafiz_req.append(_req)
check("[24e] is_hafiz NOT JS-mandatory and no conditional rule",
      js_mandatory("is_hafiz") is False and cond_rule("is_hafiz") is None,
      str(cond_rule("is_hafiz")))
check("[24e] is_hafiz has no HTML required attr", html_required("is_hafiz") is False)
check("[24e] mapping marks is_hafiz required:false in every entry",
      len(_hafiz_req) >= 9 and all(r == ["required: false"] for r in _hafiz_req),
      str(_hafiz_req))

# 24f. girls_stipend REQUIRED when gender = Female (user first-hand, rev.2g)
check("[24f] girls_stipend conditional on gender=Female",
      cond_rule("girls_stipend") == ("gender", ["Female"]),
      str(cond_rule("girls_stipend")))
check("[24f] girls_stipend label carries red asterisk",
      '<label class="form-label">Girls Stipend <span class="text-danger">*</span></label>' in HTML)
check("[24f] girls_stipend not JS-mandatory when hidden (not in mandatoryByTab)",
      js_mandatory("girls_stipend") is False,
      "enforced via conditionalRequired + hidden-group skip, not tab list")
check("[24f] mapping documents gender=Female condition",
      "Required when gender = Female" in MAPPING)

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

# 31-33. conditional detail fields shown by their Yes/Other triggers (portal labels)
check("[31] scholarship_details conditional on scholarship=yes + group wired + asterisk",
      cond_rule("scholarship_details") == ("scholarship", ["1"]) and
      'id="scholarship_details_group"' in HTML and
      'radioToggle("scholarship", "scholarship_details_group", ["1"])' in JS and
      '<label class="form-label">Scholarship Details <span class="text-danger">*</span></label>' in HTML,
      str(cond_rule("scholarship_details")))
check("[32] achievement (cocurricular) details conditional + group wired + asterisk",
      cond_rule("cocurricular_details") == ("cocurricular_activities", ["1"]) and
      'id="co_curricular_details_group"' in HTML and
      'radioToggle("cocurricular_activities", "co_curricular_details_group", ["1"])' in JS and
      '<label class="form-label">Achievement Details <span class="text-danger">*</span></label>' in HTML,
      str(cond_rule("cocurricular_details")))
check("[33] emergency relation Other/Others -> Specify Relation mandatory + asterisk",
      cond_rule("emergency_relation_other") == ("emergency_relation", ["Other", "Others"]) and
      'selectToggle("emergency_relation", "emergency_relation_other_group", ["Other", "Others"])' in JS and
      'Specify Relation <span class="text-danger">*</span>' in HTML,
      str(cond_rule("emergency_relation_other")))
check("[34] guardian relation Other -> Other Relation mandatory + asterisk",
      cond_rule("guardian_relation_other") == ("guardian_relation", ["Other"]) and
      'selectToggle("guardian_relation", "guardian_relation_other_group", ["Other"])' in JS and
      'Other Relation <span class="text-danger">*</span>' in HTML,
      str(cond_rule("guardian_relation_other")))

# 35. Address detail family — visibility-gated mandatory (2026-09-29 report:
#     FEMIS blocked empty address/present_address for Address Type=Other and
#     empty house/street otherwise while PA Save & Next let them pass)
_addr_family = ("house", "street", "address",
                "present_house", "present_street", "present_address")
check("[35] address family JS-mandatory (tab0, visibility-gated)",
      all(js_mandatory(f) for f in _addr_family),
      f"missing: {[f for f in _addr_family if not js_mandatory(f)]}")
check("[35] address-type toggles wire Other-textarea vs house/street (temp + present)",
      JS.count('if (otherDiv) otherDiv.style.display = isOther ? "block" : "none";') == 2 and
      JS.count('if (houseStreet) houseStreet.style.display = isOther ? "none" : "block";') == 2,
      "both address_type IIFEs show #other_address_group / #house_street_group")
check("[35] address detail labels carry red asterisks (temp + present)",
      '<label class="form-label">Address <span class="text-danger">*</span></label>' in HTML and
      HTML.count('<label class="form-label">House # (Permanent) <span class="text-danger">*</span></label>') == 1 and
      HTML.count('<label class="form-label">Street # (Permanent) <span class="text-danger">*</span></label>') == 1)

# 36. Other-profession specify fields required when profession = Other (FEMIS
#     blocked empty mother_profession_other for Hajra riaz; father/guardian
#     are the same pattern — native required attr toggled with the group)
for _pf, _trig in (("father_profession_other", "father_profession"),
                   ("mother_profession_other", "mother_profession"),
                   ("guardian_profession_other", "guardian_profession")):
    check(f"[36] {_pf} conditional on {_trig}=Other",
          cond_rule(_pf) == (_trig, ["Other"]), str(cond_rule(_pf)))
check("[36] profession-Other groups visibility wired + labels asterisked",
      'id="father_profession_other_group"' in HTML and
      'selectToggle("father_profession", "father_profession_other_group", ["Other"])' in JS and
      'id="mother_profession_other_group"' in HTML and
      'selectToggle("mother_profession", "mother_profession_other_group", ["Other"])' in JS and
      'id="guardian_profession_other_group"' in HTML and
      'selectToggle("guardian_profession", "guardian_profession_other_group", ["Other"])' in JS and
      HTML.count('<label class="form-label">Other Profession <span class="text-danger">*</span></label>') == 3)

# 37. Email format — FEMIS's native type=email rejects 'Nil' (no @) at submit;
#     validateTab must mirror it because the JS submit handler suppresses
#     native validation (2026-09-29: Alisha zulfiqar passed PA with email='Nil')
check("[37] email format validated in validateTab (non-empty must be @-shaped)",
      "/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/" in JS and "(enter a valid email address)" in JS,
      "regex + message live next to the CNIC length guard")

# ---- cross-cutting facts ----
# 2026-09-29: server-side twin of validateTab (femis-web/mandatory.py).
# A save of tab N succeeds only if tab N has no empty mandatory field, and
# final-submit only if no tab does — for EVERY caller (browser, API,
# script).  Scenario behaviour (branches, messages, stored-record gate) is
# exercised by test_server_mandatory_validation.py; this section locks the
# wiring and the exact rule parity with the client.
sys.path.insert(0, str(ROOT / "femis-web"))
import mandatory as server_spec  # noqa: E402

server_wired = ("_mandatory_error(" in save_body
                and "missing_record_fields" in submit_body
                and "missing_record_fields" in legacy_body)
check("[X] server-side mandatory validation wired in save + final-submit + /submit",
      server_wired,
      "femis-web/mandatory.py twin of validateTab gates all three write paths")

# 2026-09-30: the CNIC / Form-B availability question was removed from the
# PA form (always Yes), b_form became unconditional, and the flag is forced
# to '1' inside _map_form_data on every write path.
check("[Xb] is_bform_available radio removed from form.html",
      html_present("is_bform_available") is False,
      "no control renders the yes/no question anymore")
check("[Xb] is_bform_available dropped from JS mandatory + server coverage",
      js_mandatory("is_bform_available") is False
      and "is_bform_available" not in server_spec.coverage(),
      "parity: neither side enforces the removed question")
check("[Xb] b_form unconditional in server ALWAYS[1] (no conditional rule)",
      "b_form" in server_spec.ALWAYS.get(1, [])
      and not any("b_form" in f for _, _, f in server_spec.RULES),
      str(server_spec.ALWAYS.get(1)))
check("[Xb] server forces is_bform_available='1' in _map_form_data",
      'mapped["is_bform_available"] = "1"' in APP)
check("[Xb] CNIC toggle IIFE removed (number group always visible)",
      'input[name="is_bform_available"]' not in JS)

# 38. Village / Housing Society address branches — enforcement existed on
#     both sides already (test_format_validation D1-D9/F3); 2026-09-30
#     added the missing red asterisks on the four labels.
check("[38] village/housing conditional rules on the client",
      cond_rule("village_id") == ("address_type", ["Village"])
      and cond_rule("housing_society_id") == ("address_type", ["Housing Society"])
      and cond_rule("present_village_id") == ("present_address_type", ["Village"])
      and cond_rule("present_housing_society_id") == ("present_address_type", ["Housing Society"]),
      str({f: cond_rule(f) for f in ("village_id", "housing_society_id",
                                     "present_village_id",
                                     "present_housing_society_id")}))
check("[38] Village / Housing Society labels carry red asterisks (temp + present)",
      HTML.count('<label class="form-label">Village <span class="text-danger">*</span></label>') == 2
      and HTML.count('<label class="form-label">Housing Society <span class="text-danger">*</span></label>') == 2,
      "4 labels")
check("[38] server RULES require the matching id per address type",
      any(t == 1 and f == ["village_id"] for t, _, f in server_spec.RULES)
      and any(t == 1 and f == ["housing_society_id"] for t, _, f in server_spec.RULES)
      and any(t == 1 and f == ["present_village_id"] for t, _, f in server_spec.RULES)
      and any(t == 1 and f == ["present_housing_society_id"] for t, _, f in server_spec.RULES),
      "village/housing rules present in mandatory.py RULES")

# 39. name fields: letters + spaces only, no periods, no numbers — the
#     FEMIS name inputs reject digits/periods; twins on both sides.
check("[39] name format validated in validateTab (letters + spaces only)",
      "/^[A-Za-z ]+$/" in JS and "letters and spaces only" in JS,
      "regex + message next to the email/DOB guards")
check("[39] server NAME_FIELDS twin wired in _format_error",
      '_NAME_RE = re.compile(r"^[A-Za-z ]+$")' in APP
      and '("name", "Name")' in APP
      and '"father_name", "Father\'s Name"' in APP
      and "tuple(k for k, _ in NAME_FIELDS)" in APP,
      "app.py NAME_FIELDS + FORMAT_FIELDS + _format_error loop")

# 40. student email is NOT mandatory (directive 2026-09-30): dropped from
#     both required lists plus the HTML required attr/red asterisk; a filled
#     value must still be @-shaped ([37] / FORMAT_FIELDS keep that gate).
check("[40] student email not mandatory (JS list + server ALWAYS + HTML)",
      not js_mandatory("email")
      and "email" not in server_spec.ALWAYS.get(1, [])
      and "email" not in server_spec.coverage()
      and not re.search(r'<input[^>]*\bname="email"[^>]*\brequired', HTML)
      and "Email ID <span class=\"text-danger\">*</span>" not in HTML
      and '("email", "Email")' in APP,
      "required dropped everywhere; format gate kept")

client_fields = set(JS_MAND)
for _cfields, _, _ in COND:
    client_fields.update(_cfields)
client_fields.add("mother_monthly_income")  # bespoke §8 block in validateTab
client_groups = {f for f in client_fields if f.endswith("[]")}
server_fields = server_spec.coverage()
check("[X] server spec covers exactly the client-enforced field set",
      server_fields == (client_fields - client_groups),
      f"server-only: {sorted(server_fields - (client_fields - client_groups))}; "
      f"client-only: {sorted((client_fields - client_groups) - server_fields)}")
check("[X] checkbox-group exception matches the client (rendered == filled)",
      client_groups == {"disability_types[]", "digital_device_type[]"}
      and not (client_groups & server_fields),
      str(sorted(client_groups)))
check("[X] server DB renames stay inside app.FORM_FIELD_MAP",
      all(f'"{k}": "{v}"' in APP for k, v in server_spec.DB_NAME.items()),
      str(server_spec.DB_NAME))

html_only = [n for n, r in sorted(ctrl.items())
             if r["required"] and n not in JS_MAND
             and not any(n in f for f, _, _ in COND)]
check("[X] no HTML-required attribute escapes JS validation (house/street closed)",
      html_only == [],
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
