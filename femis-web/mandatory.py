"""Server-side mandatory-field validation for the PA portal (student form).

Twin of femis-web/static/form.js validateTab: the client rules are the
contract, and this module enforces the same rules on the server so that
/api/save-tab, /api/final-submit and the legacy /submit route can never
succeed with an empty mandatory field — for ANY caller (browser form,
API client, script).  A save of tab N validates tab N (progressive save);
final-submit validates tabs 1..7 over the stored record merged with the
payload.

Conventions (kept in lockstep with the client):
- Values are keyed by DB column name.  Form field names translate through
  the same renames the form uses (present_address -> present_address_other,
  digital_device_type[] -> digital_device_type, disability_types[] ->
  disability_types).
- Visibility gating mirrors the DOM: a field that the form only enforces
  inside a toggled group is a RULE with a condition evaluated over the
  SAME trigger values the client's toggles read (address_type, *_alive,
  same_address, profession selects, ...).
- Checkbox groups (names ending in "[]") are skipped on purpose: the
  client's controlValue() treats a rendered checkbox group as filled, so
  requiring non-empty here would make the server stricter than the form
  and break parity (digital_device_type may legitimately save as '').
- Empty means None or a blank/whitespace string.  "0" is a real value
  (radio No = a selection, not emptiness).
- Sub-sector: the client's cascade hides #sub_sector_group when no
  sub-sectors exist for the chosen sector; the server requires a
  sub-sector whenever address_type=Sector and a sector is chosen (every
  seeded sector has sub-sectors — documented assumption).

Kept in sync with form.js by test_mandatory_field_reconciliation.py
(coverage parity) and exercised end-to-end by
test_server_mandatory_validation.py.
"""

# DB-column overrides for form field names.  Must stay a subset of
# app.FORM_FIELD_MAP (asserted by test_mandatory_field_reconciliation).
DB_NAME = {
    "present_address": "present_address_other",
    "digital_device_type[]": "digital_device_type",
    "disability_types[]": "disability_types",
    "transport_facility": "transport",
    "cocurricular_details": "achievement_details",
    "refugee_card_number": "refugee_card",
}

# Unconditional required fields per tab (form.js mandatoryByTab minus the
# entries whose group is visibility-gated — those live in RULES below).
ALWAYS = {
    1: ["name", "b_form", "gender", "date_of_birth",
        "birth_province_id", "birth_district_id", "nationality",
        "address_type", "contact_number", "city_id", "religion",
        "language_id", "email"],
    2: ["father_name", "father_cnic", "is_father_alive", "mother_name",
        "is_mother_alive", "is_orphan"],
    3: ["class_id", "section_id", "date_of_admission", "class_admitted_id",
        "medium_of_instruction", "mode_of_study", "admission_number", "shift",
        "total_siblings", "school_meal_program_availing",
        "transport_facility", "scholarship", "cocurricular_activities"],
    4: ["emergency_name", "emergency_contact", "emergency_relation"],
    5: ["is_refugee"],
    6: ["has_major_disability", "has_mental_disability", "visually_fit",
        "uses_glasses", "has_hearing_difficulties", "difficulty_listening",
        "difficulty_walking", "uses_crutches_walker", "uses_hearing_aid",
        "difficulty_seeing_board", "difficulty_reading_writing",
        "difficulty_remembering", "difficulty_concentrating"],
    7: ["digital_device_at_home", "internet_at_home"],
}


def _db(field):
    return DB_NAME.get(field, field)


def _val(values, field):
    raw = values.get(_db(field))
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw)


def _empty(values, field):
    raw = values.get(_db(field))
    if raw is None:
        return True
    if isinstance(raw, str):
        return raw.strip() == ""
    return False


def _c(field, *vals):
    return lambda v: _val(v, field) in vals


def _not(field, *vals):
    return lambda v: _val(v, field) not in vals


def _filled(field):
    return lambda v: not _empty(v, field)


def _and(*conds):
    return lambda v: all(c(v) for c in conds)


# Visibility-gated / conditional required rules: (tab, condition, fields).
# condition is None = always (kept here so every rule has one home).
RULES = [
    # --- tab 1: personal + address family ---
    # b_form is UNCONDITIONAL (2026-09-30): the is_bform_available yes/no
    # question was removed from the form and the server forces it to "1",
    # so every student must supply a B-Form / CNIC number.
    (1, _c("address_type", "Sector"), ["sector_id"]),
    (1, _and(_c("address_type", "Sector"), _filled("sector_id")),
     ["sub_sector_id"]),
    (1, _c("address_type", "Village"), ["village_id"]),
    (1, _c("address_type", "Housing Society"), ["housing_society_id"]),
    (1, _not("address_type", "Other"), ["house", "street"]),
    (1, _c("address_type", "Other"), ["address"]),
    (1, _not("same_address", "1"), ["present_address_type"]),
    (1, _and(_not("same_address", "1"), _c("present_address_type", "Sector")),
     ["present_sector_id"]),
    (1, _and(_not("same_address", "1"), _c("present_address_type", "Sector"),
             _filled("present_sector_id")),
     ["present_sub_sector_id"]),
    (1, _and(_not("same_address", "1"), _c("present_address_type", "Village")),
     ["present_village_id"]),
    (1, _and(_not("same_address", "1"),
             _c("present_address_type", "Housing Society")),
     ["present_housing_society_id"]),
    (1, _and(_not("same_address", "1"), _c("present_address_type", "Other")),
     ["present_address"]),
    (1, _and(_not("same_address", "1"), _not("present_address_type", "Other")),
     ["present_house", "present_street"]),
    (1, _c("gender", "Female"), ["girls_stipend"]),
    # --- tab 2: parents / guardian ---
    # father_name / father_cnic / mother_name sit OUTSIDE the details groups
    # in form.html (always visible -> always required); the rest of each
    # parent's block is inside #father_details_group / #mother_details_group
    # (shown only when that parent is alive).
    (2, _c("is_father_alive", "1"),
     ["father_profession", "father_qualification", "father_monthly_income",
      "father_contact"]),
    (2, _and(_c("is_father_alive", "1"), _c("father_profession", "Other")),
     ["father_profession_other"]),
    (2, _c("is_mother_alive", "1"),
     ["mother_profession", "mother_qualification", "mother_contact"]),
    (2, _and(_c("is_mother_alive", "1"), _c("mother_profession", "Other")),
     ["mother_profession_other"]),
    (2, _and(_c("is_mother_alive", "1"),
             _c("mother_profession", "Govt Employee")),
     ["mother_bps"]),
    (2, _c("is_father_alive", "0"),
     ["guardian_name", "guardian_cnic", "guardian_relation",
      "guardian_contact", "guardian_profession", "guardian_income"]),
    (2, _and(_c("is_father_alive", "0"), _c("guardian_relation", "Other")),
     ["guardian_relation_other"]),
    (2, _and(_c("is_father_alive", "0"), _c("guardian_profession", "Other")),
     ["guardian_profession_other"]),
    (2, _c("is_orphan", "1"), ["orphan_type"]),
    # --- tab 3: academics ---
    (3, _c("scholarship", "1"), ["scholarship_details"]),
    (3, _c("cocurricular_activities", "1"), ["cocurricular_details"]),
    # effective client visibility: #bus_route_group is shown for
    # "Institution Bus" only (legacy "Bus" trigger kept in the JS list)
    (3, _c("transport_facility", "Institution Bus"), ["bus_route"]),
    # --- tab 4: emergency contact ---
    (4, _c("emergency_relation", "Other", "Others"), ["emergency_relation_other"]),
    # --- tab 5: IDPs / refugees ---
    (5, _c("is_refugee", "1"), ["idp_status_id", "is_registered_refugee"]),
    (5, _and(_c("is_refugee", "1"), _c("is_registered_refugee", "1")),
     ["refugee_card_number"]),
    # --- tab 6: medical / disability ---
    (6, _c("has_mental_disability", "1"), ["mental_disability_type"]),
    (6, _c("visually_fit", "0"), ["glass_prescription"]),
    # --- tab 7: digital access (digital_device_type[] is a checkbox group,
    #     skipped per client parity) ---
]


def _mother_income_required(values):
    """Mother's income mandatory unless profession = Housewife (rule §8).

    Client guard skips when either control's group is hidden — i.e. when
    the mother's details block is not shown (mother not alive).
    """
    if _val(values, "is_mother_alive") != "1":
        return False
    prof = _val(values, "mother_profession")
    return bool(prof) and prof.lower() != "housewife"


# Bespoke form.js blocks that are neither in mandatoryByTab nor in
# conditionalRequired: (tab, fields, condition).
SPECIALS = [
    (2, ["mother_monthly_income"], _mother_income_required),
]


def _tab_numbers():
    tabs = set(ALWAYS)
    tabs.update(t for t, _, _ in RULES)
    tabs.update(t for t, _, _ in SPECIALS)
    return sorted(tabs)


def missing_fields(tab, values):
    """Field names (form.js naming) whose mandatory value is empty for `tab`.

    `values` is a dict keyed by DB column name (stored record merged with
    the payload overrides).  Unknown/invalid tab numbers validate nothing.
    """
    try:
        tab = int(tab)
    except (TypeError, ValueError):
        return []
    missing = []

    def want(fields):
        for f in fields:
            if f.endswith("[]"):
                continue  # checkbox groups: rendered == filled (client parity)
            if f in missing:
                continue
            if _empty(values, f):
                missing.append(f)

    for f in ALWAYS.get(tab, []):
        want([f])
    for t, cond, fields in RULES:
        if t == tab and cond(values):
            want(fields)
    for t, fields, cond in SPECIALS:
        if t == tab and cond(values):
            want(fields)
    return missing


def missing_record_fields(values):
    """[(tab, missing_fields)] for every tab 1..7 — the final-submit gate."""
    out = []
    for tab in _tab_numbers():
        m = missing_fields(tab, values)
        if m:
            out.append((tab, m))
    return out


def error_message(per_tab):
    """Human-readable rejection shared by every write path."""
    parts = [f"tab {tab}: {', '.join(fields)}" for tab, fields in per_tab]
    return "Mandatory fields missing — " + "; ".join(parts)


def coverage():
    """Every field name this module can enforce (used by the governance test)."""
    cov = set()
    for fields in ALWAYS.values():
        cov.update(fields)
    for _, _, fields in RULES:
        cov.update(fields)
    for _, fields, _ in SPECIALS:
        cov.update(fields)
    return cov
