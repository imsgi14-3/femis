# Phase 3A.4 — Rendered Portal Layout Verification

**Date:** 2026-09-24  
**Phase:** 3A.4 — **READ-ONLY verification** (no application code changes)  
**Status:** COMPLETE — STOP (await separate approval for any next phase)

---

## 1. Method

| Step | Detail |
|---|---|
| Portal launch | Fresh local Flask instance on `http://127.0.0.1:5010` (`femis-web/app.py`, debug off) so current `form.html` is served |
| Session | Student login → `/form/10` (Portal Verify Student) |
| Tab activation | Forced `active`/`show` on each `.tab-pane` / nav pill (avoids Tab-1 validation blocking pill clicks; no form submit) |
| Conditionals | Representative radios toggled in-browser only (`is_bform_available`, major/mental/hearing disability, refugee, digital device, transport Institution Bus, scholarship, co-curricular, parent alive, orphan, etc.) — **no saves** |
| Structure extract | DOM tree walk: `h6` headings → fields under each heading (name, label, required, hidden) |
| Screenshots | Full-page per tab |
| Baseline | `docs/femis-portal-layout-map.md`, `docs/femis-field-identity-crosswalk.yaml`, `docs/phase3a2-portal-layout-implementation-plan.md`, FEMIS extract `data/output/portal_audit_20260924_183753.json` |
| Static identity | Direct read of `femis-web/templates/form.html` (names, ids, required tokens, special cases) |
| Tests | Full 4-suite regression |
| Git | `status` / `diff --stat` / `diff form.html` |

**FEMIS bot files were not executed or modified** (`src/form_filler.py`, `src/main.py`, `config/field_mapping.yaml` untouched this phase).

---

## 2. Rendered structure (all 7 tabs)

Evidence: `data/output/local_rendered_20260924_193537.json`  
Screenshots: `data/logs/local_render_tab_{1-7}_20260924_193537.png`

```text
TAB 1  (Personal Details)
  Personal Information
    name, is_bform_available, b_form, gender, date_of_birth
  Birthplace & Nationality
    birth_province_id, birth_district_id, nationality, nationality_id
  Domicile Information
    domicile_province_id, domicile_district_id
  Address (Temporary Address)
    address_type, sector_id, sub_sector_id, village_id, housing_society_id, address, house, street, contact_number
  Permanent Address
    city_id, same_as_permanent_address, present_address_type, present_sector_id, present_sub_sector_id, present_village_id, present_housing_society_id, present_address, present_house, present_street
  Religion, Language & Other Details
    religion, religion_id, language_id, mother_language_other, blood_group, email, girls_stipend, is_hafiz

TAB 2  (Parents / Guardian)
  Father Information
    father_name, father_cnic, is_father_alive, father_contact, father_landline, father_email, father_qualification, father_profession, father_profession_other, father_monthly_income, father_bps, father_domicile_province_id, father_domicile_district_id
  Mother Information
    mother_name, is_mother_alive, mother_cnic, mother_contact, mother_landline, mother_email, mother_qualification, mother_profession, mother_profession_other, mother_monthly_income, mother_bps
  Orphan & Guardian Information
    is_orphan, orphan_type, guardian_name, guardian_cnic, guardian_relation, guardian_relation_other, guardian_contact, guardian_email, guardian_qualification, guardian_profession, guardian_profession_other, guardian_income, guardian_bps

TAB 3  (Educational Details)
  Educational Details
    class_id, section_id, class_group_id, result_percentage, date_of_admission, admission_number, class_admitted_id, shift, medium_of_instruction, mode_of_study, last_fde_institution_id, last_other_institution, school_meal_program_availing, primary_education_completion_years
    [Siblings Details]
    total_siblings, siblings_same_institution, siblings_other_fde, siblings_private
  Transport Facility
    transport_facility, bus_route
  Scholarship & Co-curricular Activities
    scholarship, cocurricular_activities, scholarship_details, cocurricular_details

TAB 4  (Emergency Contact)
  Emergency Contact Details
    emergency_name, emergency_contact, emergency_relation, emergency_relation_other

TAB 5  (IDPs Details)
  IDPs / Refugee Details
    is_refugee, idp_status_id, is_registered_refugee, refugee_card_number

TAB 6  (Health Details)
  Major Disability
    has_major_disability, disability_types[], disability_certificate
  Mental Health
    has_mental_disability, mental_disability_type, mental_disability_other
  Other Medical Conditions
    other_medical_condition
  Vision Details
    visually_fit, uses_glasses, glass_prescription, difficulty_seeing_board
  Hearing Details
    has_hearing_difficulties, uses_hearing_aid, hearing_aid_details, difficulty_listening
  Walking / Mobility
    difficulty_walking, uses_crutches_walker
  Learning Abilities
    difficulty_reading_writing, difficulty_remembering, difficulty_concentrating
  Vaccination Details
    basic_vaccination_completed

TAB 7  (Digital Access)
  Digital Access
    digital_device_at_home, digital_device_type[], internet_at_home
```

**Rendered heading counts:** Tab1=6, Tab2=3, Tab3=3, Tab4=1, Tab5=1, Tab6=8, Tab7=1  
**Rendered unique field `name`s:** 132 (matches static unique count)

---

## 3. FEMIS vs portal comparison

### 3.1 Group headings (order)

| Tab | FEMIS groups (3A.1.1 / layout map) | Rendered portal | Classification |
|---|---|---|---|
| 1 | Personal Information; Domicile Information; Address (Temporary Address) [+ Permanent]; Religion, Language & Other Details | Personal Information; **Birthplace & Nationality**; Domicile Information; Address (Temporary Address); Permanent Address; Religion, Language & Other Details | See §3.2 (approved ambiguities) |
| 2 | Father Information; Mother Information; Orphan & Guardian Information | **Exact match** | `PASS` |
| 3 | Educational Details; Transport Facility; Scholarship & Co-curricular Activities | **Exact match** (+ Siblings Details sublabel) | `PASS` |
| 4 | Emergency Contact Details | **Exact match** | `PASS` |
| 5 | IDPs / Refugee Details | **Exact match** | `PASS` |
| 6 | Major Disability; Mental Health; Other Medical Conditions; Vision Details; Hearing Details; Walking / Mobility; Learning Abilities; Vaccination Details | **Exact match** | `PASS` |
| 7 | Digital Access | **Exact match** | `PASS` |

### 3.2 Tab 1 grouping (approved decisions preserved)

| Item | FEMIS visual | Rendered portal | Classification | Decision |
|---|---|---|---|---|
| Birth province/district (and nationality block) | Under Personal Information / Domicile Information cards | Separate **Birthplace & Nationality** group after Personal Information | `GROUP_DIFFERENCE` | **Approved deferred** — do not relocate until evidence explicitly establishes FEMIS grouping |
| Permanent Address | Nested under Address | **Sibling group** after Address (Temporary Address) | `GROUP_DIFFERENCE` | **Approved** — remain sibling for now |
| Field names in birth/domicile/address | Same concepts | Same `name`s | `PASS` (identity) | No rename |

### 3.3 Field membership (FEMIS extract names vs rendered portal names)

| Tab | FEMIS-only | Portal-only | Classification |
|---|---|---|---|
| 1 | `Temporary Student ID` (FEMIS_ONLY widget, empty name — crosswalk) | — | `MISSING_FIELD` vs FEMIS extract only; **expected** — crosswalk `FEMIS_ONLY`, not on portal by design; not an identity regression |
| 2 | — | `guardian_qualification` | `PASS` — **PORTAL_ONLY**, keep; not reported as missing FEMIS field |
| 3–5, 6, 7 | — (label aliases “Disability Type”/“Device Type” map to `disability_types[]` / `digital_device_type[]`) | — | `PASS` |
| 6 | — | — | Field sets align after name mapping |
| 7 | — | — | `PASS` |

No `DUPLICATE_FIELD` found (no field `name` rendered twice in one tab).  
No `IDENTITY_REGRESSION`.

### 3.4 Label notes (informational only)

| Field | FEMIS extract label | Portal label | Classification |
|---|---|---|---|
| Various (layout map § label rows) | e.g. “Total Number of Siblings” | “Total Siblings” | `VISUAL_DIFFERENCE` — **not changed** this phase; plan only required group/structure alignment unless plan called for a label change |
| Radio group extract labels | Often first option (“Yes”) | Full question text | `VISUAL_DIFFERENCE` — known extract artifact; trust `name` |

---

## 4. Special-case verification

| Case | Result |
|---|---|
| **`guardian_qualification`** | Present once (`name` count=1). Location: Tab 2 → **Orphan & Guardian Information**, after `guardian_email`. Status **PORTAL_ONLY** — not missing from FEMIS. |
| **`transport_facility`** | Present; group **Transport Facility**; separate from bus route. |
| **`bus_route`** | Present as distinct `name`; container `#bus_route_group` present; conditional still driven by `form.js` `radioToggle("transport_facility", "bus_route_group", …)` (file untouched). |
| **`disability_certificate`** | `type=file`, inside `#disability_fields` with `disability_types[]`, under **Major Disability**; tied to `has_major_disability` flow. |
| **`disability_types[]`** | Present once; same block as certificate. |
| **Tab 7** | `digital_device_at_home`, `digital_device_type[]`, `internet_at_home` all present under **Digital Access**. |
| **`refugee_card_number`** | Present on Tab 5; Phase 2 map `refugee_card_number → refugee_card` still in `app.py` (untouched this phase). |
| **Birthplace** | Group retained with birth fields + nationality as approved. |
| **Permanent Address** | Sibling `h6` after Temporary Address. |

---

## 5. Field-identity preservation (static + rendered)

| Check | Static `form.html` | Rendered DOM | Result |
|---|---|---|---|
| Unique `name` attrs | **132** | **132** | `PASS` |
| `name` token count | 159 (radios/checkboxes multi) | 201 (DOM counts each control; uniqueness matches) | Unique set `PASS` |
| Nav tabs | `tab-1`…`tab-7` | 7 panes | `PASS` |
| Key conditional ids | `bus_route_group`, `disability_fields`, `orphan_fields`, `device_type_group`, `cnic_number_group`, scholarship/co-curricular groups, `mental_disability_type_group`, `refugee_card_group`, `idp_fields` | present | `PASS` |
| Specials list (all 10) | all present | all present | `PASS` |
| `required` word tokens in template | **56** | DOM `[required]` **70** | `PASS` for layout: template `required` count unchanged by 3A.3; higher live count is **pre-existing `form.js` validation** adding required at runtime — not introduced by layout edits |
| Duplicates / deletions | none vs pre-3A.3 identity baseline | none | `PASS` |

**Bot mappings:** `config/field_mapping.yaml`, `src/form_filler.py`, `src/main.py` — **not modified in 3A.4** (and 3A.3 did not modify them either).

---

## 6. Test results

| Suite | Result |
|---|---|
| `test_data_integrity.py` | **24/24** |
| `test_submission_status.py` | **12/12** |
| `smoke_test.py` | **14/14** (includes 122 field_mapping labels present in portal) |
| `smoke_test_bot.py` | **3/3** |
| **Total** | **53/53** |

No failures; no layout-related regression.

---

## 7. Git status / diff summary

```
git status (relevant):
  modified: femis-web/templates/form.html     ← Phase 3A.1–3A.3 layout (expected)
  modified: audit_portal.py                   ← Phase 3A.1.1 tooling (prior)
  modified: config/field_mapping.yaml         ← Phase 2 (prior)
  modified: femis-web/app.py                  ← Phase 2 (prior)
  modified: femis-web/static/form.js          ← Phase 2 (prior)
  modified: smoke_test.py                     ← Phase 2 (prior)
  modified: src/data_sources/webform_handler.py, src/form_filler.py, src/main.py  ← Phase 2 (prior)
  untracked: docs/, smoke_test_bot.py, test_data_integrity.py, test_submission_status.py

git diff --stat:
  9 files changed, 256 insertions(+), 132 deletions(-)   # whole working tree, not only 3A.4

git diff --numstat form.html:
  63  52  femis-web/templates/form.html   # cumulative Tab1–7 layout from 0da8bad
```

**3A.4 application-code changes:** **none**.  
**Expected layout implementation file:** `femis-web/templates/form.html` only (from 3A.1–3A.3).  
Phase 2 / 3A.1.1 diffs remain separate on their original files; 3A.4 did not touch them.

---

## 8. Screenshots / audit evidence

| Evidence | Path |
|---|---|
| Local portal Tab 1–7 screenshots (3A.4) | `data/logs/local_render_tab_1..7_20260924_193537.png` |
| Local structure + identity JSON | `data/output/local_rendered_20260924_193537.json` |
| Earlier local pass (same day) | `data/logs/local_render_tab_*_20260924_193451.png`, `data/output/local_rendered_20260924_193451.json` |
| FEMIS screenshots (baseline) | `data/logs/audit_tab_*_20260924_183753.png` |
| FEMIS field/heading extract (baseline) | `data/output/portal_audit_20260924_183753.json` |

---

## 9. Discrepancy register

| # | Tab | Issue | Class | Action |
|---|---|---|---|---|
| 1 | 1 | Portal keeps **Birthplace & Nationality** group (FEMIS merges birth into Personal/Domicile cards) | `GROUP_DIFFERENCE` | **Approved deferred** — no fix until explicit evidence + approval |
| 2 | 1 | Permanent Address is **sibling**, not nested under Address | `GROUP_DIFFERENCE` | **Approved** — keep sibling |
| 3 | 1 | FEMIS **Temporary Student ID** widget absent on portal | `MISSING_FIELD` vs FEMIS only | Expected (`FEMIS_ONLY` in crosswalk); not a portal regression |
| 4 | various | Visible label wording differs from some FEMIS labels | `VISUAL_DIFFERENCE` | Out of scope unless plan called for label change; no identity impact |
| — | 2–7 headings | Group titles and order | `PASS` | — |
| — | specials | transport/bus_route/certificate/tab7/guardian_qual | `PASS` | — |
| — | identity | names/ids/required structure | `PASS` | — |
| — | tests | 53/53 | `PASS` | — |

**No `IDENTITY_REGRESSION`, no `DUPLICATE_FIELD`, no silent fixes applied.**

---

## 10. STOP

Phase 3A.4 complete. Nothing further implemented. Next phase (if any) requires separate approval.
