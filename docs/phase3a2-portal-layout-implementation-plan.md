# Phase 3A.2 — Portal Layout Implementation Plan

**Date:** 2026-09-24  
**Phase:** 3A.2 — **PLAN / DOCUMENTATION ONLY**  
**Status:** AWAITING APPROVAL — do not implement until explicitly approved  

**Source of truth:**  
- `docs/femis-portal-layout-map.md`  
- `docs/femis-field-identity-crosswalk.yaml`  
- FEMIS evidence: `data/output/portal_audit_20260924_183753.json`, `data/logs/audit_tab_*_20260924_183753.png`  
- Current portal structure (inspection only): `femis-web/templates/form.html`, `femis-web/static/form.js` (behavior), `femis-web/static/style.css`

**HARD RULES (this document and any future implementation phase):**  
Do **not** modify bot mappings, bot selectors, canonical DB field names, API behavior, database schema/data, or `name` attributes solely to resemble FEMIS. The bot already fills FEMIS successfully.

---

## 0. Guiding principle

> **A field’s visual location or displayed label may change without changing its underlying field identity.**

Every future layout change must preserve:

| Layer | Must preserve |
|---|---|
| Portal `name` attribute | Yes (unless separately approved) |
| DB column / canonical concept | Yes |
| Bot mapping key (`config/field_mapping.yaml`) | Yes |
| Conditional show/hide wiring (`form.js` container ids) | Yes — move whole field blocks with their wrapper ids |
| Validation (`required`, patterns) | Yes |
| Displayed group heading / label / visual order | **May change** (this phase’s target) |

---

## 1. Target FEMIS structure vs current portal (all 7 tabs)

### TAB 1 — Personal Details

#### A. Target FEMIS structure

| # | Item | Value |
|---|---|---|
| 1 | Tab number | 1 |
| 2 | Tab title | Personal Details |
| 3 | Groups (exact order) | 1. Personal Information *(Basic identity details)* 2. Domicile Information 3. Address *(Temporary Address)* with nested Permanent Address 4. Religion, Language & Other Details |

**FEMIS group → fields (screenshot + extract order):**

1. **Personal Information**  
   `name`, `is_bform_available`, `b_form` *(conditional)*, `gender`, `date_of_birth`, `birth_province_id`, `birth_district_id`
2. **Domicile Information**  
   `nationality`, `nationality_id` *(when Other)*, `domicile_province_id`, `domicile_district_id` *(when Pakistani)*  
   *Note: FEMIS visual places Nationality under Domicile Information; birth province/district appear under Personal Information on the screenshot.*
3. **Address** *(subtitle Temporary Address)* → fields: `address_type`, `sector_id`/`sub_sector_id`/`village_id`/`housing_society_id`/`address` *(mutually exclusive by type)*, `house`, `street`, `contact_number`  
   **Nested Permanent Address:** `same_as_permanent_address`, `city_id`, `present_*` address block
4. **Religion, Language & Other Details**  
   `religion`, `religion_id`, `language_id`, `mother_language_other`, `blood_group`, `email`, `girls_stipend`, `is_hafiz`

#### B. Current portal structure (`form.html`)

| # | Portal group | Fields (order) | Notes |
|---|---|---|---|
| 1 | Student Information | `name`, `is_bform_available`, `b_form`, `gender`, `date_of_birth` | No birth fields |
| 2 | Birthplace & Nationality | `birth_province_id`, `birth_district_id`, `nationality`, `nationality_id` | Split out of FEMIS Personal/Domicile |
| 3 | Domicile | `domicile_province_id`, `domicile_district_id` | Heading differs from FEMIS |
| 4 | Temporary Address | `address_type`, cascade fields, `house`, `street`, `contact_number` | Matches FEMIS Address/Temp concept |
| 5 | Permanent Address | `city_id`, `same_as_permanent_address`, `present_*` | FEMIS nests under Address |
| 6 | Other Information | `religion`…`is_hafiz` | Heading differs from FEMIS |

#### C. Required presentation changes

| Change | Classification | Exact instruction |
|---|---|---|
| “Student Information” → “Personal Information” | `GROUP_RENAME` | Change h6 text only |
| Move `birth_province_id`, `birth_district_id` into Personal Information (after `date_of_birth`) | `FIELD_REORDER` + `GROUP_MERGE` | Move both field columns (with ids) from Birthplace group into Personal Information row; keep `name`s |
| Remove empty “Birthplace & Nationality” heading or leave as no-op | `GROUP_MERGE` | Birthplace group is fully merged away |
| “Domicile” → “Domicile Information”; absorb `nationality`, `nationality_id` | `GROUP_RENAME` + `FIELD_REORDER` | Nationality fields move from Birthplace into Domicile Information |
| “Temporary Address” → “Address” with subtitle “Temporary Address” (or heading “Address (Temporary Address)”) | `GROUP_RENAME` | Heading text only |
| Permanent Address stays under Tab 1; optional nest under Address block | `NO_CHANGE` (preferred) or `GROUP_REORDER` | Nesting is CSS/structure only; do not change field names. Default plan: **keep as sibling group after Address** to reduce risk |
| “Other Information” → “Religion, Language & Other Details” | `GROUP_RENAME` | Heading text only |
| Field order inside each group vs FEMIS | `NO_CHANGE` / `FIELD_REORDER` | Align Personal Information to FEMIS: name, is_bform_available, b_form, gender, date_of_birth, birth_province_id, birth_district_id. Rest of groups already match FEMIS order closely |

**Tab 1 summary:** 3× `GROUP_RENAME`, 1× birth-field merge (`GROUP_MERGE`/`FIELD_REORDER`), nationality move into Domicile, permanent Address optional nest = `NO_CHANGE` default.

---

### TAB 2 — Parents / Guardian

#### A. Target FEMIS structure

| # | Item | Value |
|---|---|---|
| 1 | Tab number | 2 |
| 2 | Tab title | Parents / Guardian |
| 3 | Groups (exact order) | 1. Father Information 2. Mother Information 3. Orphan & Guardian Information |

**FEMIS fields per group (order from extract/screenshot):**

1. **Father Information** — `father_name`, `father_cnic`, `is_father_alive`, then (when alive): `father_contact`, `father_landline`, `father_email`, `father_qualification`, `father_profession`, `father_profession_other`, `father_monthly_income`, `father_bps`, `father_domicile_province_id`, `father_domicile_district_id`
2. **Mother Information** — `mother_name`, `is_mother_alive`, `mother_cnic`, `mother_contact`, `mother_landline`, `mother_email`, `mother_qualification`, `mother_profession`, `mother_profession_other`, `mother_monthly_income`, `mother_bps`
3. **Orphan & Guardian Information** — `is_orphan`, `orphan_type`, `guardian_name`, `guardian_cnic`, `guardian_relation`, `guardian_relation_other`, `guardian_contact`, `guardian_email`, `guardian_profession`, `guardian_profession_other`, `guardian_income`, `guardian_bps`  
   *No `guardian_qualification` on FEMIS (PORTAL_ONLY).*

#### B. Current portal structure

| # | Portal group | Notes |
|---|---|---|
| 1 | Father's Information | Apostrophe form |
| 2 | Mother's Information | Apostrophe form |
| 3 | Orphan / Guardian Information | Slash; includes **`guardian_qualification`** after `guardian_email` |

#### C. Required presentation changes

| Change | Classification | Exact instruction |
|---|---|---|
| “Father's Information” → “Father Information” | `GROUP_RENAME` | Heading only |
| “Mother's Information” → “Mother Information” | `GROUP_RENAME` | Heading only |
| “Orphan / Guardian Information” → “Orphan & Guardian Information” | `GROUP_RENAME` | Heading only |
| Field order within groups | `NO_CHANGE` | Already matches FEMIS sequence closely |
| `guardian_qualification` placement | `PORTAL_ONLY_FIELD` | Keep in Orphan & Guardian group (see §3) |

**Tab 2 summary:** 3× `GROUP_RENAME` only; no field moves.

---

### TAB 3 — Educational Details

#### A. Target FEMIS structure

| # | Item | Value |
|---|---|---|
| 1 | Tab number | 3 |
| 2 | Tab title | Educational Details |
| 3 | Groups (exact order) | 1. Educational Details *(incl. **Siblings Details** subsection)* 2. Transport Facility 3. Scholarship & Co-curricular Activities |

**FEMIS group → fields:**

1. **Educational Details**  
   `class_id`, `section_id`, `class_group_id`, `result_percentage`, `date_of_admission`, `admission_number`, `class_admitted_id`, `shift`, `medium_of_instruction`, `mode_of_study`, `last_fde_institution_id`, `last_other_institution`, `school_meal_program_availing`, `primary_education_completion_years`,  
   **Siblings Details** subheading: `total_siblings`, `siblings_same_institution`, `siblings_other_fde`, `siblings_private`
2. **Transport Facility**  
   `transport_facility` *(radio Institution Bus | Private)* → conditional `bus_route` *(select; distinct field)*
3. **Scholarship & Co-curricular Activities**  
   `scholarship`, `cocurricular_activities`, `scholarship_details`, `cocurricular_details` *(conditionals)*

#### B. Current portal structure

| # | Portal group | Fields (order) |
|---|---|---|
| 1 | Academic Information | `class_id`, `section_id`, `class_group_id`, `result_percentage`, `date_of_admission`, `admission_number`, `last_fde_institution_id`, `class_admitted_id`, `last_other_institution`, `shift`, `medium_of_instruction` |
| 2 | Additional Information | `primary_education_completion_years`, `school_meal_program_availing`, `mode_of_study`, `total_siblings`, `siblings_other_fde`, `siblings_same_institution`, `siblings_private`, `transport_facility`, `bus_route`, `scholarship`, `cocurricular_activities`, `scholarship_details`, `cocurricular_details` |

#### C. Required presentation changes

| Change | Classification | Exact instruction |
|---|---|---|
| “Academic Information” → “Educational Details” | `GROUP_RENAME` | Heading only |
| Move `mode_of_study`, `school_meal_program_availing`, `primary_education_completion_years` from Additional into Educational Details | `FIELD_REORDER` / `GROUP_MERGE` | Place after `medium_of_instruction` / before siblings, matching FEMIS: … medium, mode_of_study, last FDE, last other, meal, primary years, then siblings |
| Optional reorder within Educational Details: `class_admitted_id` before `shift` per FEMIS extract | `FIELD_REORDER` | Swap column order only |
| Add subheading **Siblings Details** above sibling fields inside Educational Details | `GROUP_RENAME` (subsection) | New h6/strong label; not a new data group |
| Extract `transport_facility` + `bus_route` into dedicated group **Transport Facility** | `GROUP_SPLIT` | Split out of Additional Information; keep both field blocks and `bus_route_group` id together |
| Extract scholarship fields into **Scholarship & Co-curricular Activities** | `GROUP_SPLIT` | Remainder of Additional Information |
| Delete empty “Additional Information” heading after split | `GROUP_SPLIT` (cleanup) | Group fully split into Educational Details + 2 FEMIS cards |
| `shift` stays in Educational Details | `NO_CHANGE` | Confirmed EXACT_IDENTITY on FEMIS in this card |
| `transport_facility` ≠ `bus_route` | `NO_CHANGE` (identity) | Never merge; see §4 |

**Tab 3 summary:** 1× `GROUP_RENAME`, 1× `GROUP_SPLIT` (Additional → 3 targets), multiple `FIELD_REORDER`, 1× subsection label.

---

### TAB 4 — Emergency Contact

#### A. Target FEMIS structure

| # | Item | Value |
|---|---|---|
| 1 | Tab number | 4 |
| 2 | Tab title | Emergency Contact |
| 3 | Groups | 1. **Emergency Contact Details** |
| 4 | Fields (order) | `emergency_name`, `emergency_contact`, `emergency_relation`, `emergency_relation_other` |

#### B. Current portal structure

| Group | Fields |
|---|---|
| Emergency Contact Information | `emergency_name`, `emergency_contact`, `emergency_relation`, `emergency_relation_other` |

#### C. Required presentation changes

| Change | Classification | Exact instruction |
|---|---|---|
| “Emergency Contact Information” → “Emergency Contact Details” | `GROUP_RENAME` | Heading only |
| Field order | `NO_CHANGE` | Matches FEMIS |

---

### TAB 5 — IDPs Details

#### A. Target FEMIS structure

| # | Item | Value |
|---|---|---|
| 1 | Tab number | 5 |
| 2 | Tab title | IDPs Details |
| 3 | Groups | 1. **IDPs / Refugee Details** |
| 4 | Fields (order) | `is_refugee`, `idp_status_id`, `is_registered_refugee`, `refugee_card_number` *(conditionals as on FEMIS)* |

#### B. Current portal structure

| Group | Fields |
|---|---|
| Refugee / IDP Information | `is_refugee`, `idp_status_id`, `is_registered_refugee`, `refugee_card_number` |

#### C. Required presentation changes

| Change | Classification | Exact instruction |
|---|---|---|
| “Refugee / IDP Information” → “IDPs / Refugee Details” | `GROUP_RENAME` | Heading only |
| Field order | `NO_CHANGE` | Matches FEMIS |

---

### TAB 6 — Health Details

#### A. Target FEMIS structure

| # | Item | Value |
|---|---|---|
| 1 | Tab number | 6 |
| 2 | Tab title | Health Details |
| 3 | Groups (exact order) | 1. Major Disability 2. Mental Health 3. Other Medical Conditions 4. Vision Details 5. Hearing Details 6. Walking / Mobility 7. Learning Abilities 8. Vaccination Details |

**FEMIS group → fields:**

1. **Major Disability** — `has_major_disability` → *(Yes)* `disability_types[]`, `disability_certificate`
2. **Mental Health** — `has_mental_disability` → `mental_disability_type`, `mental_disability_other`
3. **Other Medical Conditions** — `other_medical_condition`
4. **Vision Details** — `visually_fit`, `uses_glasses`, `glass_prescription`, `difficulty_seeing_board`
5. **Hearing Details** — `has_hearing_difficulties`, `uses_hearing_aid`, `hearing_aid_details`, `difficulty_listening`
6. **Walking / Mobility** — `difficulty_walking`, `uses_crutches_walker`
7. **Learning Abilities** — `difficulty_reading_writing`, `difficulty_remembering`, `difficulty_concentrating`
8. **Vaccination Details** — `basic_vaccination_completed`

#### B. Current portal structure

| # | Portal group | Fields |
|---|---|---|
| 1 | Disability Information | `has_major_disability`, `disability_types[]`, `disability_certificate` |
| 2 | Mental Health | `has_mental_disability`, `mental_disability_type`, `mental_disability_other`, **`other_medical_condition`** |
| 3 | Vision | vision fields |
| 4 | Hearing | hearing fields |
| 5 | Mobility | mobility fields |
| 6 | Learning Difficulties | learning fields |
| 7 | Vaccination | `basic_vaccination_completed` |

#### C. Required presentation changes

| Change | Classification | Exact instruction |
|---|---|---|
| “Disability Information” → “Major Disability” | `GROUP_RENAME` | Heading only |
| “Mental Health” stays; **move `other_medical_condition` out** | `GROUP_SPLIT` | New h6 **Other Medical Conditions** after Mental Health group |
| New group **Other Medical Conditions** | `GROUP_SPLIT` | Single field `other_medical_condition` (move whole column) |
| “Vision” → “Vision Details” | `GROUP_RENAME` | Heading only |
| “Hearing” → “Hearing Details” | `GROUP_RENAME` | Heading only |
| “Mobility” → “Walking / Mobility” | `GROUP_RENAME` | Heading only |
| “Learning Difficulties” → “Learning Abilities” | `GROUP_RENAME` | Heading only |
| “Vaccination” → “Vaccination Details” | `GROUP_RENAME` | Heading only |
| Group order | `NO_CHANGE` | Portal order already matches FEMIS 1–8 after split |
| `disability_certificate` conditional block | `NO_CHANGE` | Stays inside `#disability_fields` with `disability_types[]` |

**Tab 6 summary:** 7× `GROUP_RENAME`, 1× `GROUP_SPLIT` (other_medical_condition).

---

### TAB 7 — Digital Access

#### A. Target FEMIS structure

| # | Item | Value |
|---|---|---|
| 1 | Tab number | 7 |
| 2 | Tab title | Digital Access |
| 3 | Groups | 1. **Digital Access** |
| 4 | Fields (order) | `digital_device_at_home` → `digital_device_type[]` *(when Yes)*, `internet_at_home` |

#### B. Current portal structure

| Group | Fields |
|---|---|
| Digital Access Information | `digital_device_at_home`, `digital_device_type[]`, `internet_at_home` |

#### C. Required presentation changes

| Change | Classification | Exact instruction |
|---|---|---|
| “Digital Access Information” → “Digital Access” | `GROUP_RENAME` | Heading only |
| Field order | `NO_CHANGE` | Matches FEMIS |

---

## 2. Field identity protection (moved / relabeled fields)

**Rule:** Visual move or label text change **must not** change `name`, DB column, or bot key.

| Canonical concept | Portal `name` | DB column | Bot mapping key (YAML path) | FEMIS name/id | Preserve portal `name`? |
|---|---|---|---|---|---|
| Student name | `name` | `name` | `personal_information.name_of_student` | `name` | **YES** |
| Birth province | `birth_province_id` | `birth_province_id` | `personal_information.province_of_birth` / tab maps | `birth_province_id` | **YES** |
| Birth district | `birth_district_id` | `birth_district_id` | district_of_birth | `birth_district_id` | **YES** |
| Nationality | `nationality` | `nationality` | nationality | `nationality` | **YES** |
| Other nationality | `nationality_id` | `nationality_id` | other_nationality | `nationality_id` | **YES** |
| Domicile province/district | `domicile_province_id`, `domicile_district_id` | same | domicile_* | same | **YES** |
| Shift | `shift` | `shift` | `…shift` / portal shift | `shift` | **YES** |
| Mode of study | `mode_of_study` | `mode_of_study` | mode_of_study | `mode_of_study` | **YES** |
| Meal program | `school_meal_program_availing` | same | school_meal_program_availing | same | **YES** |
| Primary years | `primary_education_completion_years` | same | same | same | **YES** |
| Siblings ×4 | `total_siblings`, `siblings_*` | same | same | same | **YES** |
| Transport facility | `transport_facility` | **`transport`** (aliased) | transport_facility | `transport_facility` | **YES** (do not rename to `transport`) |
| Bus route | `bus_route` | `bus_route` | bus_route / transport_facility.bus_route | `bus_route` | **YES** — separate from transport_facility |
| Scholarship / co-curricular | `scholarship`, `cocurricular_activities`, `scholarship_details`, `cocurricular_details` | same | same | same | **YES** |
| Other medical condition | `other_medical_condition` | same | same | same | **YES** |
| Disability certificate | `disability_certificate` | `disability_certificate` | disability_certificate | `disability_certificate` | **YES** |
| Guardian qualification | `guardian_qualification` | `guardian_qualification` | guardian_qualification | *(none on FEMIS)* | **YES** — portal-only |
| All other tab fields | as in form.html | as canonical | as YAML source_field | as audit | **YES** |

**Never** rename portal `name` to “look like” FEMIS. Identity is already established in the crosswalk.

---

## 3. Portal-only fields

### 3.1 `guardian_qualification`

| Attribute | Value |
|---|---|
| Status | **`PORTAL_ONLY`** (high confidence, Phase 3A.1.1) |
| ≠ | **INVALID** — portal-only ≠ remove |
| Current location | Tab 2 → group **Orphan / Guardian Information**, between `guardian_email` and `guardian_profession` (`form.html` ~L592–595) |
| Control | `input type="text" name="guardian_qualification"` |
| DB | column `guardian_qualification` exists |
| Bot | `config/field_mapping.yaml` → `guardian_qualification` (source_field same) |
| FEMIS | Not present in live 36-field extract; father/mother qualification only |
| Alignment action | **KEEP** field in place within (renamed) **Orphan & Guardian Information**. Do not delete. Do not hide solely because FEMIS lacks it. Optional future: mark visually as portal extension — **not required** for FEMIS alignment. |

### 3.2 Other portal-only notes

- Portal option `None` on `transport_facility` (FEMIS has Institution Bus | Private only) — **option-set difference**, not a portal-only field; keep `None` unless separately approved (bot/DB contract already maps Institution Bus).
- No other portal-only named fields on tabs 1–7 beyond the four audited; `guardian_qualification` is the sole remaining PORTAL_ONLY name after 3A.1.1.

---

## 4. Confirmed special cases (do not alter implementation in this phase)

| Concept | Portal `name` | FEMIS | Relationship | Layout-only note |
|---|---|---|---|---|
| Shift | `shift` | radio `shift` (Morning \| Evening) | **EXACT_IDENTITY** | Stays in Educational Details group; may move within card for order only |
| Transport facility | `transport_facility` | radio `transport_facility` (Institution Bus \| Private) | **EXACT_IDENTITY** | Move into dedicated **Transport Facility** group; **do not merge** with bus_route |
| Bus route | `bus_route` | select `bus_route`, conditional on Institution Bus | **EXACT_IDENTITY**, **DIFFERENT concept** from transport_facility | Move **with** transport_facility group; keep `#bus_route_group` and `form.js` `radioToggle("transport_facility", "bus_route_group", …)` unchanged |
| Disability certificate | `disability_certificate` | `input[type=file]` conditional on major disability | **EXACT_IDENTITY** | Stays in Major Disability / `#disability_fields` |
| Guardian qualification | `guardian_qualification` | *(absent)* | **PORTAL_ONLY** | Keep; see §3 |

---

## 5. Field movement matrix

Only rows requiring movement, relabeling, group change, or special handling. Fields with pure `NO_CHANGE` identity and location may still appear when a **group heading** changes.

| Tab | Canonical Concept | Current Portal Group | Target FEMIS Group | Current Order | Target Order | Change Type | Portal `name` preserved? | Bot Mapping Preserved? | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Student identity block | Student Information | Personal Information | 1 | 1 | GROUP_RENAME | YES | YES | Heading only |
| 1 | Birth province/district | Birthplace & Nationality | Personal Information | G2 #1–2 | Personal #6–7 | FIELD_REORDER + GROUP_MERGE | YES | YES | Move both selects with cascade ids |
| 1 | Nationality + other | Birthplace & Nationality | Domicile Information | G2 #3–4 | Domicile #1–2 | FIELD_REORDER + GROUP_MERGE | YES | YES | Aligns FEMIS Nationality under Domicile |
| 1 | Domicile province/district | Domicile | Domicile Information | G3 | Domicile #3–4 | GROUP_RENAME + FIELD_REORDER | YES | YES | After nationality |
| 1 | Temporary address block | Temporary Address | Address (Temporary Address) | G4 | Address | GROUP_RENAME | YES | YES | Heading (+ optional subtitle) |
| 1 | Permanent address block | Permanent Address | Address → nested Permanent (optional) | G5 | After Address | NO_CHANGE (default) | YES | YES | Nesting optional; keep sibling if safer |
| 1 | Religion…is_hafiz | Other Information | Religion, Language & Other Details | G6 | last | GROUP_RENAME | YES | YES | Heading only |
| 2 | Father block | Father's Information | Father Information | G1 | 1 | GROUP_RENAME | YES | YES | Apostrophe removal |
| 2 | Mother block | Mother's Information | Mother Information | G2 | 2 | GROUP_RENAME | YES | YES | |
| 2 | Orphan/guardian block | Orphan / Guardian Information | Orphan & Guardian Information | G3 | 3 | GROUP_RENAME | YES | YES | Slash → ampersand |
| 2 | Guardian qualification | Orphan / Guardian | Orphan & Guardian Information | after email | same relative | PORTAL_ONLY_FIELD | YES | YES | **Keep**; not on FEMIS |
| 3 | Academic core | Academic Information | Educational Details | G1 | 1 | GROUP_RENAME | YES | YES | |
| 3 | Mode of study | Additional Information | Educational Details | Add #3 | after medium_of_instruction | FIELD_REORDER | YES | YES | FEMIS shows in main card |
| 3 | Meal program | Additional Information | Educational Details | Add #2 | before primary years | FIELD_REORDER | YES | YES | |
| 3 | Primary education years | Additional Information | Educational Details | Add #1 | after meal / before siblings | FIELD_REORDER | YES | YES | |
| 3 | Siblings ×4 | Additional Information | Educational Details → Siblings Details | Add #4–7 | end of Educational Details | FIELD_REORDER + subheading | YES | YES | Add “Siblings Details” label |
| 3 | class_admitted vs shift order | Academic | Educational Details | admitted after last_fde; shift later | admitted before shift (FEMIS) | FIELD_REORDER | YES | YES | Optional column swap |
| 3 | Transport facility + bus route | Additional Information | **Transport Facility** | Add #8–9 | group 2 | GROUP_SPLIT | YES | YES | Keep pair + `#bus_route_group` together |
| 3 | Scholarship + co-curricular + details | Additional Information | **Scholarship & Co-curricular Activities** | Add #10–13 | group 3 | GROUP_SPLIT | YES | YES | Conditional detail fields stay with parents |
| 4 | Emergency contact block | Emergency Contact Information | Emergency Contact Details | G1 | 1 | GROUP_RENAME | YES | YES | |
| 5 | IDP block | Refugee / IDP Information | IDPs / Refugee Details | G1 | 1 | GROUP_RENAME | YES | YES | |
| 6 | Major disability + type + certificate | Disability Information | Major Disability | G1 | 1 | GROUP_RENAME | YES | YES | Keep `#disability_fields` intact |
| 6 | Mental disability fields | Mental Health | Mental Health | G2 #1–3 | 2 | NO_CHANGE | YES | YES | |
| 6 | Other medical condition | Mental Health | **Other Medical Conditions** | G2 #4 | 3 | GROUP_SPLIT | YES | YES | New h6; move column only |
| 6 | Vision fields | Vision | Vision Details | G3 | 4 | GROUP_RENAME | YES | YES | |
| 6 | Hearing fields | Hearing | Hearing Details | G4 | 5 | GROUP_RENAME | YES | YES | |
| 6 | Mobility fields | Mobility | Walking / Mobility | G5 | 6 | GROUP_RENAME | YES | YES | |
| 6 | Learning fields | Learning Difficulties | Learning Abilities | G6 | 7 | GROUP_RENAME | YES | YES | |
| 6 | Vaccination | Vaccination | Vaccination Details | G7 | 8 | GROUP_RENAME | YES | YES | |
| 7 | Digital access block | Digital Access Information | Digital Access | G1 | 1 | GROUP_RENAME | YES | YES | |

---

## 6. Implementation boundaries

### 6.1 Safe layout-only changes (eligible for implementation phase after approval)

- Changing `h6` group heading **text** (and optional subtitles)
- Moving existing field **column wrappers** between groups within the same tab
- Reordering fields **within** a group (DOM order of `.col-*` blocks)
- Adding a visual subheading (e.g. “Siblings Details”) without new inputs
- Splitting one visual group into two visual groups by inserting a new `h6` and moving existing blocks
- Changing display `<label>` text (not `name`, not validation messages tied to JS)
- CSS tweaks for group spacing / card look (`style.css`) that do not hide fields

**Constraint:** When moving blocks, move the **entire** wrapper including `id`s used by `form.js` (`#sector_group`, `#bus_route_group`, `#disability_fields`, `#orphan_fields`, `#cnic_number_group`, etc.). Never leave an id behind.

### 6.2 Changes requiring extra review (NOT in layout implementation unless separately approved)

| Change | Why blocked |
|---|---|
| Renaming any `name` attribute | Breaks bot, save-tab, reverseMap, DB |
| Changing DB column or `FORM_FIELD_MAP` | API/contract |
| Changing `form.js` collection, conditionals, validation | Behavior risk |
| Changing bot mappings / selectors (`field_mapping.yaml`, `form_filler.py`, `main.py`) | Bot contract |
| Adding/removing DB columns | Schema |
| Removing `guardian_qualification` or portal option `None` | Data/product decision |
| Merging `transport_facility` with `bus_route` | Different concepts |
| Changing field `required` flags or patterns | Validation behavior |
| Altering API endpoints or success semantics | API behavior |

---

## 7. Proposed future implementation sequence

*(Only after explicit approval of this plan)*

1. **Tab 1** — group renames + birth/nationality regroup (highest structural delta; prove move pattern with cascade ids intact)  
2. **Tab 2** — three group renames (zero field moves; quick win)  
3. **Tab 4** — group rename  
4. **Tab 5** — group rename  
5. **Tab 7** — group rename  
6. **Tab 3** — split Additional Information; reorder Academic/Educational; Transport + Scholarship cards (most complex field moves)  
7. **Tab 6** — renames + extract Other Medical Conditions  
8. **Label alignment pass** — field display labels where FEMIS wording is the target and labels are cosmetic only  
9. **Visual/CSS cleanup** — consistent card/h6 styling (`style.css` only)  
10. **Regression tests** — `test_data_integrity.py`, `test_submission_status.py`, `smoke_test.py`, `smoke_test_bot.py` (expect **53/53**) + manual tab walk + bot fill smoke  

**Rationale:** Simple renames first (2,4,5,7) reduce merge risk; Tab 1 establishes the “move wrapper + keep ids” pattern; Tab 3/6 last because they split groups and move conditionals.

---

## 8. Validation checklist (this plan document)

| # | Check | Result |
|---|---|---|
| 1 | Covers all 7 tabs (A/B/C each) | YES — §1 Tabs 1–7 |
| 2 | FEMIS group headings exact as 3A.1.1 | YES — Personal Information; Domicile Information; Address; Religion, Language & Other Details; Father Information; Mother Information; Orphan & Guardian Information; Educational Details; Transport Facility; Scholarship & Co-curricular Activities; Emergency Contact Details; IDPs / Refugee Details; Major Disability; Mental Health; Other Medical Conditions; Vision Details; Hearing Details; Walking / Mobility; Learning Abilities; Vaccination Details; Digital Access |
| 3 | `guardian_qualification` explicit PORTAL_ONLY | YES — §3.1, matrix, §4 |
| 4 | `shift`, `transport_facility`, `bus_route`, `disability_certificate` distinguished | YES — §4, matrix |
| 5 | No source-code or DB files modified in this phase | YES — docs only (`docs/phase3a2-portal-layout-implementation-plan.md`) |
| 6 | Tests | Run after write — see report below |

---

## 9. Unresolved ambiguity (documented, not blocking plan)

1. **Permanent Address nesting** — FEMIS nests Permanent under Address; plan defaults to **keep portal as sibling group** (`NO_CHANGE`) to minimize structural risk; optional nest = safe layout-only if approved.  
2. **Birth fields visual home** — Screenshot shows province/district of birth under Personal Information; plan moves them there. If product prefers keeping “Birthplace & Nationality”, that would **deviate** from FEMIS visual and should be rejected or re-approved.  
3. **Portal option `None` on transport** — retained; not a layout issue.  
4. **Exact FEMIS field order inside Personal Information** beyond screenshot (e.g. Temporary Student ID widget) — FEMIS_ONLY widget not in portal; ignore for portal layout.

---

*End of Phase 3A.2 plan. No portal layout changes implemented. Awaiting explicit approval before any edit to `form.html` / `form.js` / CSS for layout alignment.*
