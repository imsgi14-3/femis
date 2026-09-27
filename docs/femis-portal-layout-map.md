# FEMIS Portal Layout Map — READ-ONLY Audit

**Date:** 2026-09-24  
**Phase:** 3A.1 / 3A.1.1 — STRICTLY READ-ONLY (app code)  
**Scope:** Compare real FEMIS 7-tab structure vs Student Portal; field-identity crosswalk (identity vs location vs implementation).

**Rules honored:** No application code, bot mapping (`config/field_mapping.yaml`, `src/form_filler.py`, `src/main.py`), DB, portal HTML/JS modified. Deliverables: this document + `docs/femis-field-identity-crosswalk.yaml`. Auditor tooling (`audit_portal.py`) fixed for panel IDs / file inputs / force-panel screenshot only.

---

## 0. Evidence Sources

| Source | Role | Authority |
|---|---|---|
| `data/output/portal_audit_20260924_183753.json` | Per-tab FEMIS field extract + **group headings** + panel_active | **Primary FEMIS field list (3A.1.1)** |
| `data/output/portal_audit_20260921_222600.json` | Prior per-tab FEMIS field extract | Supporting (pre-repair) |
| `data/logs/audit_tab_*_20260924_183753.png` | Visual group headings, **correct tab active 7/7** | **Primary FEMIS visual** |
| `data/output/dom_structure.json` | FEMIS tab nav ids + childInputs | Primary FEMIS nav |
| `data/output/form_questions_list.txt` (UTF-16) | 100 questions in 7 `=== SECTION ===` blocks | Supporting FEMIS order |
| `data/output/audit_discrepancies_20260924_183753.json` | Name-level diffs vs portal form | Supporting |
| `config/field_mapping.yaml` | Bot tab→group→field contract | Bot implementation (fill targets) |
| `femis-web/templates/form.html` | Portal tabs + h6 groups + input names | Portal implementation |
| `data/output/portal_fields.json` | Full-form DOM dump (122 fields repeated per tab) | Supporting only — **not tab-scoped** |
| `data/output/femis_form.json` | **NOT FEMIS** — our Google-form artifact | **Excluded** |

### 0.1 Screenshot caveat — RESOLVED (3A.1.1)

Prior sets (`*_20260921_*`, first attempt `*_181515_*`) all showed Personal Details active. **Re-capture `*_20260924_183753.png` shows the correct active tab for all seven screenshots.** Tab-nav click is blocked by Tab-1 required-field validation; the auditor force-activates the target panel’s CSS classes for capture only (no Save & Next, no record created).

**FEMIS group titles (screenshot-confirmed + headings extract):**

| Tab | FEMIS group headings (in order) |
|---|---|
| 1 | Personal Information *(Basic identity details)*; Domicile Information; Address *(Temporary Address)* + nested Permanent Address; Religion, Language & Other Details |
| 2 | Father Information; Mother Information; Orphan & Guardian Information |
| 3 | Educational Details *(incl. Siblings Details subsection)*; Transport Facility; Scholarship & Co-curricular Activities |
| 4 | Emergency Contact Details |
| 5 | IDPs / Refugee Details |
| 6 | Major Disability; Mental Health; Other Medical Conditions; Vision Details; Hearing Details; Walking / Mobility; Learning Abilities; Vaccination Details |
| 7 | Digital Access |

---

## 1. Tab-Level Comparison

| # | FEMIS tab (nav) | Portal tab (pill) | FEMIS id | Portal id | Status | Notes |
|---|---|---|---|---|---|---|
| 1 | Personal Details | Personal Details | tab-nav-personal / tab-personal | tab-1 | MATCH | Title + order identical |
| 2 | Parents / Guardian | Parents / Guardian | tab-nav-parents / tab-parents | tab-2 | MATCH | Title + order identical |
| 3 | Educational Details | Educational Details | tab-nav-education / tab-education | tab-3 | MATCH | Title + order identical |
| 4 | Emergency Contact | Emergency Contact | tab-nav-emergency / tab-emergency | tab-4 | MATCH | Title + order identical |
| 5 | IDPs Details | IDPs Details | tab-nav-idps / tab-idps | tab-5 | MATCH | Title + order identical |
| 6 | Health Details | Health Details | tab-nav-health / tab-health | tab-6 | MATCH | Title + order identical |
| 7 | Digital Access | Digital Access | tab-nav-digital / tab-digital | tab-7 | MATCH | Title + order identical |

**Tab order:** FEMIS 1→7 identical to Portal 1→7. **No TAB_DIFFERENCE.**

**FEMIS childInputs vs Portal unique `name` attrs (radios counted once):**

| Tab | FEMIS childInputs | Portal unique names | Δ (FEMIS−Portal) |
|---|---|---|---|
| tab-1 | 42 | 38 | +4 |
| tab-2 | 39 | 37 | +2 |
| tab-3 | 30 | 24 | +6 |
| tab-4 | 4 | 4 | 0 |
| tab-5 | 6 | 4 | +2 |
| tab-6 | 33 | 21 | +12 |
| tab-7 | 6 | 3 | +3 |

---

## 2. Group (Section) Structure Comparison

### 2.1 Side-by-side

| Tab | FEMIS groups (screenshot-confirmed) | YAML bot groups | Portal h6 groups | Status |
|---|---|---|---|---|
| tab-1 | Personal Information; Domicile Information; Address (Temp) + Permanent Address; Religion, Language & Other Details | personal_information; domicile_information; address_temporary; address_permanent; religion_language_other | Student Information; Birthplace & Nationality; Domicile; Temporary Address; Permanent Address; Other Information | **GROUP_DIFFERENCE** (rename + portal splits birth out of personal/domicile) |
| tab-2 | Father Information; Mother Information; Orphan & Guardian Information | fathers_information; mothers_information; orphan_guardian_information | Father's Information; Mother's Information; Orphan / Guardian Information | **GROUP_DIFFERENCE** (apostrophe / & vs / renames only) |
| tab-3 | Educational Details (+ Siblings Details); Transport Facility; Scholarship & Co-curricular Activities | class_section; sibling_details; transport_facility; scholarships_and_co_curricular | Academic Information; Additional Information | **GROUP_DIFFERENCE** (YAML/portal structure differs; FEMIS has 3 named cards) |
| tab-4 | Emergency Contact Details | **FLAT** (7 field keys, no group map) | Emergency Contact Information | **GROUP_DIFFERENCE** (name) single section both |
| tab-5 | IDPs / Refugee Details | **FLAT** (7 field keys) | Refugee / IDP Information | **GROUP_DIFFERENCE** (name) single section both |
| tab-6 | Major Disability; Mental Health; Other Medical Conditions; Vision Details; Hearing Details; Walking / Mobility; Learning Abilities; Vaccination Details | **FLAT** (32 field keys) | Disability Information; Mental Health; Vision; Hearing; Mobility; Learning Difficulties; Vaccination | **GROUP_DIFFERENCE** (YAML flat → FEMIS 8 / Portal 7; portal nests other_medical_condition under Mental Health) |
| tab-7 | Digital Access | **FLAT** (5 field keys) | Digital Access Information | **GROUP_DIFFERENCE** (name) single section both |

### 2.2 YAML structure note (confirmed)

- **tab_1–tab_3:** real group maps (`group → field → {label,type,...}`).
- **tab_4–tab_7:** **flat** field maps (`tab → field → {label,type,...}`) — not group maps. Earlier misparse risk resolved.

### 2.3 Group-name renames (identity preserved, label differs)

| Tab | YAML group | Portal h6 | FEMIS (screenshot-confirmed) | Relationship |
|---|---|---|---|---|
| tab-1 | personal_information | Student Information | **Personal Information** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-1 | domicile_information | Birthplace & Nationality + Domicile | Birth fields inside Personal; Nationality in Domicile | ONE_TO_MANY (portal split) |
| tab-1 | address_temporary | Temporary Address | Address / Temporary Address | SAME_CONCEPT_DIFFERENT_NAME |
| tab-1 | address_permanent | Permanent Address | Permanent Address | EXACT_IDENTITY |
| tab-1 | religion_language_other | Other Information | Religion, Language & Other Details | SAME_CONCEPT_DIFFERENT_NAME |
| tab-2 | fathers_information | Father's Information | **Father Information** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-2 | mothers_information | Mother's Information | **Mother Information** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-2 | orphan_guardian_information | Orphan / Guardian Information | **Orphan & Guardian Information** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-3 | class_section + sibling_details | Academic Information | **Educational Details** (+ Siblings Details) | MANY_TO_ONE / rename |
| tab-3 | transport_facility | Additional Information | **Transport Facility** (dedicated card) | SAME_CONCEPT_DIFFERENT_LOCATION |
| tab-3 | scholarships_and_co_curricular | Additional Information | **Scholarship & Co-curricular Activities** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-4 | (flat) | Emergency Contact Information | **Emergency Contact Details** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-5 | (flat) | Refugee / IDP Information | **IDPs / Refugee Details** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-6 | (flat) | Disability Information | **Major Disability** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-6 | (flat) | Mental Health | **Mental Health** + **Other Medical Conditions** | EXACT_IDENTITY + portal nests other_medical |
| tab-6 | (flat) | Vision | **Vision Details** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-6 | (flat) | Hearing | **Hearing Details** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-6 | (flat) | Mobility | **Walking / Mobility** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-6 | (flat) | Learning Difficulties | **Learning Abilities** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-6 | (flat) | Vaccination | **Vaccination Details** | SAME_CONCEPT_DIFFERENT_NAME |
| tab-7 | (flat) | Digital Access Information | **Digital Access** | SAME_CONCEPT_DIFFERENT_NAME |

### 2.4 Group ORDER

- Portal h6 order follows FEMIS `portal_audit` field sequence and `form_questions_list` SECTION order for tabs where questions are listed.
- **Resolved (screenshot Tab 1):** FEMIS House/Street sit under **Address (Temporary Address)**, not early with DOB — early audit-list order was DOM extract order, not visual. Portal Temporary Address grouping **MATCH** visual FEMIS.
- **Resolved (3A.1.1):** FEMIS tab-3 visual order = Educational Details card → Transport Facility card → Scholarship & Co-curricular Activities card. Portal collapses latter two into Additional Information → **GROUP_DIFFERENCE** (FEMIS 3 named cards vs portal 2 h6).
- Portal tab-6: 7 h6 vs FEMIS 8 cards (portal merges Other Medical Conditions into Mental Health) → **GROUP_DIFFERENCE**.

---

## 3. Field-Level Comparison (by tab)

Classification: `MATCH` | `GROUP_DIFFERENCE` | `GROUP_ORDER_DIFFERENCE` | `FIELD_ORDER_DIFFERENCE` | `LABEL_DIFFERENCE` | `TAB_DIFFERENCE` | `MISSING_FROM_PORTAL` | `PORTAL_ONLY` | `AMBIGUOUS`.

### 3.1 tab-1 — FEMIS "Personal Details" (39 fields)

| # | FEMIS name | FEMIS label | Portal name | Portal label | Class |
|---|---|---|---|---|---|
| 1 | `name` | Name of Student | `name` | Name of Student | MATCH |
| 2 | `b_form` | CNIC/Form-B No. | `b_form` | CNIC / Form-B No. | LABEL_DIFFERENCE |
| 3 | (empty) | Temporary Student ID | — | — | AMBIGUOUS |
| 4 | `date_of_birth` | Date of Birth | `date_of_birth` | Date of Birth | MATCH |
| 5 | `house` | House # | `house` | House # (Temporary) | LABEL_DIFFERENCE |
| 6 | `street` | Street # | `street` | Street # (Temporary) | LABEL_DIFFERENCE |
| 7 | `address` | Address | `address` | Address | MATCH |
| 8 | `contact_number` | Contact Number / WhatsApp | `contact_number` | Contact Number / WhatsApp | MATCH |
| 9 | `present_house` | House # | `present_house` | House # (Permanent) | LABEL_DIFFERENCE |
| 10 | `present_street` | Street # | `present_street` | Street # (Permanent) | LABEL_DIFFERENCE |
| 11 | `present_address` | Address | `present_address` | Address | MATCH |
| 12 | `mother_language_other` | Specify Language | `mother_language_other` | Other Language | LABEL_DIFFERENCE |
| 13 | `email` | Email ID | `email` | Email ID | MATCH |
| 14 | `gender` | Gender | `gender` | Gender | MATCH |
| 15 | `birth_province_id` | Province of Birth | `birth_province_id` | Province of Birth | MATCH |
| 16 | `birth_district_id` | District of Birth | `birth_district_id` | District of Birth | MATCH |
| 17 | `nationality` | Nationality | `nationality` | Nationality | MATCH |
| 18 | `nationality_id` | Other Nationality | `nationality_id` | Other Nationality | MATCH |
| 19 | `domicile_province_id` | Student Domicile — Province | `domicile_province_id` | Student Domicile — Province | MATCH |
| 20 | `domicile_district_id` | Student Domicile — District | `domicile_district_id` | Student Domicile — District | MATCH |
| 21 | `address_type` | Address Type | `address_type` | Address Type | MATCH |
| 22 | `sector_id` | Sector | `sector_id` | Sector | MATCH |
| 23 | `sub_sector_id` | Sub Sector | `sub_sector_id` | Sub Sector | MATCH |
| 24 | `village_id` | Village | `village_id` | Village | MATCH |
| 25 | `housing_society_id` | Housing Society | `housing_society_id` | Housing Society | MATCH |
| 26 | `city_id` | City | `city_id` | City | MATCH |
| 27 | `present_address_type` | Address Type | `present_address_type` | Address Type | MATCH |
| 28 | `present_sector_id` | Sector | `present_sector_id` | Sector | MATCH |
| 29 | `present_sub_sector_id` | Sub Sector | `present_sub_sector_id` | Sub Sector | MATCH |
| 30 | `present_village_id` | Village | `present_village_id` | Village | MATCH |
| 31 | `present_housing_society_id` | Housing Society | `present_housing_society_id` | Housing Society | MATCH |
| 32 | `religion` | Religion | `religion` | Religion | MATCH |
| 33 | `religion_id` | Other Religion | `religion_id` | Other Religion | MATCH |
| 34 | `language_id` | Mother Language | `language_id` | Mother Language | MATCH |
| 35 | `blood_group` | Blood Group | `blood_group` | Blood Group | MATCH |
| 36 | `is_bform_available` | Yes *(radio group)* | `is_bform_available` | Is CNIC / Form-B Available? | LABEL_DIFFERENCE |
| 37 | `girls_stipend` | Yes | `girls_stipend` | Girls Stipend | LABEL_DIFFERENCE |
| 38 | `is_hafiz` | Yes | `is_hafiz` | Is Hafiz-e-Quran? | LABEL_DIFFERENCE |
| 39 | `same_as_permanent_address` | Same as Temporary Address | `same_as_permanent_address` | Same as Temporary Address | MATCH |

**Portal-only on this tab:** (none)

### 3.2 tab-2 — FEMIS "Parents / Guardian" (36 fields)

| # | FEMIS name | FEMIS label | Portal name | Portal label | Class |
|---|---|---|---|---|---|
| 1 | `father_name` | Father's Name | `father_name` | Father's Name | MATCH |
| 2 | `father_cnic` | Father's CNIC | `father_cnic` | Father's CNIC | MATCH |
| 3 | `father_contact` | Contact Number / Whatsapp number | `father_contact` | Father's Contact Number / WhatsApp | LABEL_DIFFERENCE |
| 4 | `father_landline` | Landline Number | `father_landline` | Father's Landline Number | LABEL_DIFFERENCE |
| 5 | `father_email` | Email | `father_email` | Father's Email | LABEL_DIFFERENCE |
| 6 | `father_profession_other` | Other Profession | `father_profession_other` | Other Profession | MATCH |
| 7 | `mother_name` | Mother's Name | `mother_name` | Mother's Name | MATCH |
| 8 | `mother_cnic` | Mother's CNIC | `mother_cnic` | Mother's CNIC | MATCH |
| 9 | `mother_contact` | Contact Number / Whatsapp Number | `mother_contact` | Mother's Contact Number / WhatsApp | LABEL_DIFFERENCE |
| 10 | `mother_landline` | Landline Number | `mother_landline` | Mother's Landline Number | LABEL_DIFFERENCE |
| 11 | `mother_email` | Email | `mother_email` | Mother's Email | LABEL_DIFFERENCE |
| 12 | `mother_profession_other` | Other Profession | `mother_profession_other` | Other Profession | MATCH |
| 13 | `guardian_name` | Guardian Name | `guardian_name` | Guardian Name | MATCH |
| 14 | `guardian_cnic` | Guardian CNIC | `guardian_cnic` | Guardian CNIC | MATCH |
| 15 | `guardian_relation_other` | Specify Relation | `guardian_relation_other` | Other Relation | LABEL_DIFFERENCE |
| 16 | `guardian_contact` | Contact Number / Whatsapp Number | `guardian_contact` | Guardian Contact / WhatsApp | LABEL_DIFFERENCE |
| 17 | `guardian_email` | Email | `guardian_email` | Guardian Email | LABEL_DIFFERENCE |
| 18 | `guardian_profession_other` | Other Profession | `guardian_profession_other` | Other Profession | MATCH |
| 19 | `father_domicile_province_id` | Father Domicile — Province | `father_domicile_province_id` | Father Domicile — Province | MATCH |
| 20 | `father_domicile_district_id` | Father Domicile — District | `father_domicile_district_id` | Father Domicile — District | MATCH |
| 21 | `father_qualification` | Qualification | `father_qualification` | Father's Qualification | LABEL_DIFFERENCE |
| 22 | `father_profession` | Profession | `father_profession` | Father's Profession | LABEL_DIFFERENCE |
| 23 | `father_monthly_income` | Income (per month) | `father_monthly_income` | Father's Income (per month) | LABEL_DIFFERENCE |
| 24 | `father_bps` | BPS | `father_bps` | Father's BPS | LABEL_DIFFERENCE |
| 25 | `mother_qualification` | Qualification | `mother_qualification` | Mother's Qualification | LABEL_DIFFERENCE |
| 26 | `mother_profession` | Profession | `mother_profession` | Mother's Profession | LABEL_DIFFERENCE |
| 27 | `mother_bps` | BPS | `mother_bps` | Mother's BPS | LABEL_DIFFERENCE |
| 28 | `mother_monthly_income` | Income (per month) | `mother_monthly_income` | Mother's Income (per month) | LABEL_DIFFERENCE |
| 29 | `orphan_type` | Orphan Type | `orphan_type` | Orphan Type | MATCH |
| 30 | `guardian_relation` | Relation | `guardian_relation` | Guardian Relation | LABEL_DIFFERENCE |
| 31 | `guardian_profession` | Profession | `guardian_profession` | Guardian Profession | LABEL_DIFFERENCE |
| 32 | `guardian_bps` | BPS | `guardian_bps` | Guardian BPS | LABEL_DIFFERENCE |
| 33 | `guardian_income` | Income | `guardian_income` | Guardian Income | LABEL_DIFFERENCE |
| 34 | `is_father_alive` | Yes | `is_father_alive` | Is Father Alive | LABEL_DIFFERENCE |
| 35 | `is_mother_alive` | Yes | `is_mother_alive` | Is Mother Alive | LABEL_DIFFERENCE |
| 36 | `is_orphan` | Yes | `is_orphan` | Is Orphan Child | LABEL_DIFFERENCE |

**Portal-only on this tab:**

- `guardian_qualification` — **PORTAL_ONLY (confirmed 3A.1.1, high)** — live FEMIS 36-field extract has father/mother qualification only; guardian_* conditional reveal does not include qualification. EXTRA_IN_OURS vs portal_audit. Portal may keep field; FEMIS has no counterpart.

### 3.3 tab-3 — FEMIS "Educational Details" (24 fields in 3A.1.1 extract; 22 named + shift + transport_facility)

| # | FEMIS name | FEMIS label | Portal name | Portal label | Class |
|---|---|---|---|---|---|
| 1 | `result_percentage` | Result / Percentage of Last Class passed | `result_percentage` | …passed completely | LABEL_DIFFERENCE |
| 2 | `date_of_admission` | Date of Admission | `date_of_admission` | Date of Admission | MATCH |
| 3 | `admission_number` | Admission Number | `admission_number` | Admission Number | MATCH |
| 4 | `last_other_institution` | Last Institution Attended (other than FDE) | `last_other_institution` | Last Institution Other than FDE | LABEL_DIFFERENCE |
| 5 | `primary_education_completion_years` | Number of years spent completing Primary Education (I-V) | `primary_education_completion_years` | Primary Education Completion (Years) | LABEL_DIFFERENCE |
| 6 | `total_siblings` | Total Number of Siblings | `total_siblings` | Total Siblings | LABEL_DIFFERENCE |
| 7 | `siblings_same_institution` | In Same Institution | `siblings_same_institution` | Siblings in Same Institution (Number) | LABEL_DIFFERENCE |
| 8 | `siblings_other_fde` | In Other FDE Institutions | `siblings_other_fde` | Siblings in Other FDE | LABEL_DIFFERENCE |
| 9 | `siblings_private` | In Private Institutions | `siblings_private` | Siblings in Private | LABEL_DIFFERENCE |
| 10 | `scholarship_details` | Scholarship Details | `scholarship_details` | Scholarship Details | MATCH |
| 11 | `cocurricular_details` | Achievement Details | `cocurricular_details` | Achievement Details | MATCH |
| 12 | `class_id` | Class | `class_id` | Class | MATCH |
| 13 | `section_id` | Section | `section_id` | Section | MATCH |
| 14 | `class_group_id` | Group | `class_group_id` | Class Group | LABEL_DIFFERENCE |
| 15 | `class_admitted_id` | Class Admitted In | `class_admitted_id` | Class Admitted In | MATCH |
| 16 | `medium_of_instruction` | Medium of Instruction | `medium_of_instruction` | Medium of Instruction | MATCH |
| 17 | `mode_of_study` | Mode of Study | `mode_of_study` | Mode of Study | MATCH |
| 18 | `last_fde_institution_id` | Last Institution Attended under FDE | `last_fde_institution_id` | …Under FDE | MATCH |
| 19 | `bus_route` | Bus Route | `bus_route` | Bus Route | MATCH |
| 20 | `school_meal_program_availing` | Yes | `school_meal_program_availing` | Meal Program | LABEL_DIFFERENCE |
| 21 | `scholarship` | Yes | `scholarship` | Scholarship | LABEL_DIFFERENCE |
| 22 | `cocurricular_activities` | Yes | `cocurricular_activities` | Co-curricular Activities | LABEL_DIFFERENCE |
| 23 | `shift` | Shift (Morning/Evening) | `shift` | Shift | MATCH *(confirmed 3A.1.1)* |
| 24 | `transport_facility` | Transport Facility | `transport_facility` | Transport Facility | MATCH *(confirmed 3A.1.1; portal option set adds None)* |

**Portal-only on this tab:**

- *(none — `shift` and `transport_facility` confirmed present on FEMIS 3A.1.1; both now MATCH by name)*

**FEMIS-only / structure notes (3A.1.1):**

- `shift` — **EXACT_IDENTITY** — FEMIS radio Morning|Evening under Educational Details card; screenshot-confirmed.
- `transport_facility` — **EXACT_IDENTITY** — FEMIS radio Institution Bus|Private in dedicated **Transport Facility** card; portal same name under Additional Information with extra option `None`. Conditional: Institution Bus reveals `bus_route`. Distinct from `bus_route` (select).

### 3.4 tab-4 — FEMIS "Emergency Contact" (4 fields)

| # | FEMIS name | FEMIS label | Portal name | Portal label | Class |
|---|---|---|---|---|---|
| 1 | `emergency_name` | Emergency Contact Name | `emergency_name` | Emergency Contact Name | MATCH |
| 2 | `emergency_contact` | Contact Number | `emergency_contact` | Emergency Contact Number | LABEL_DIFFERENCE |
| 3 | `emergency_relation_other` | Specify Relation | `emergency_relation_other` | Other Relation | LABEL_DIFFERENCE |
| 4 | `emergency_relation` | Relation | `emergency_relation` | Relation | MATCH |

**Portal-only:** (none)

### 3.5 tab-5 — FEMIS "IDPs Details" (4 fields)

| # | FEMIS name | FEMIS label | Portal name | Portal label | Class |
|---|---|---|---|---|---|
| 1 | `refugee_card_number` | Refugee Card Number | `refugee_card_number` | Refugee Card Number | MATCH |
| 2 | `idp_status_id` | IDP Status | `idp_status_id` | IDP Status | MATCH |
| 3 | `is_refugee` | Yes | `is_refugee` | Is Student Refugee / IDP | LABEL_DIFFERENCE |
| 4 | `is_registered_refugee` | Yes | `is_registered_refugee` | Is Registered as Refugee | LABEL_DIFFERENCE |

**Portal-only:** (none)

### 3.6 tab-6 — FEMIS "Health Details" (21 fields)

| # | FEMIS name | FEMIS label | Portal name | Portal label | Class |
|---|---|---|---|---|---|
| 1 | (empty) | Disability Type | — | — | AMBIGUOUS |
| 2 | `mental_disability_other` | Specify Mental Disability | `mental_disability_other` | Other Mental Disability | LABEL_DIFFERENCE |
| 3 | `other_medical_condition` | Other Medical Condition / Remarks | `other_medical_condition` | Other Medical Conditions | LABEL_DIFFERENCE |
| 4 | `glass_prescription` | please specify the Glasses Prescription | `glass_prescription` | Glasses Prescription | LABEL_DIFFERENCE |
| 5 | `hearing_aid_details` | Hearing Difficulty Details | `hearing_aid_details` | Hearing Aid Details | LABEL_DIFFERENCE |
| 6 | `disability_types[]` | Disability Type | `disability_types[]` | Disability Type | MATCH |
| 7 | `mental_disability_type` | Mental Disability Type | `mental_disability_type` | Mental Disability Type | MATCH |
| 8 | `difficulty_seeing_board` | Difficulty while seeing the board… | `difficulty_seeing_board` | Difficulty Seeing Board | LABEL_DIFFERENCE |
| 9 | `difficulty_reading_writing` | Difficulty Reading / Writing | `difficulty_reading_writing` | … | MATCH |
| 10 | `difficulty_remembering` | Difficulty Remembering | `difficulty_remembering` | … | MATCH |
| 11 | `difficulty_concentrating` | Difficulty Concentrating | `difficulty_concentrating` | … | MATCH |
| 12 | `has_major_disability` | Yes | `has_major_disability` | Any Major Disability | LABEL_DIFFERENCE |
| 13 | `has_mental_disability` | Yes | `has_mental_disability` | Any Mental Disability | LABEL_DIFFERENCE |
| 14 | `visually_fit` | Yes | `visually_fit` | Visually FIT | LABEL_DIFFERENCE |
| 15 | `uses_glasses` | Yes | `uses_glasses` | Wears Glasses | LABEL_DIFFERENCE |
| 16 | `has_hearing_difficulties` | Yes | `has_hearing_difficulties` | Has Hearing Difficulty | LABEL_DIFFERENCE |
| 17 | `uses_hearing_aid` | Yes | `uses_hearing_aid` | Uses Hearing Aid | LABEL_DIFFERENCE |
| 18 | `difficulty_listening` | Yes | `difficulty_listening` | Difficulty Listening | LABEL_DIFFERENCE |
| 19 | `difficulty_walking` | Yes | `difficulty_walking` | Difficulty Walking | LABEL_DIFFERENCE |
| 20 | `uses_crutches_walker` | Yes | `uses_crutches_walker` | Uses Crutches / Walker | LABEL_DIFFERENCE |
| 21 | `basic_vaccination_completed` | Yes | `basic_vaccination_completed` | Basic Vaccination Completed | LABEL_DIFFERENCE |
| 22 | `disability_certificate` | Disability Certificate (file) | `disability_certificate` | Disability Certificate | MATCH *(confirmed 3A.1.1)* |

**Portal-only on this tab:**

- *(none — `disability_certificate` confirmed present on FEMIS 3A.1.1)*

**FEMIS-only / structure notes (3A.1.1):**

- `disability_certificate` — **EXACT_IDENTITY** — FEMIS `input[type=file]` name=disability_certificate under Major Disability; conditional on `has_major_disability=Yes`. Prior extracts omitted `type=file`.
- FEMIS group **Major Disability** hosts `has_major_disability` → reveals `disability_types[]` + `disability_certificate`. Portal labels this group **Disability Information**.

### 3.7 tab-7 — FEMIS "Digital Access" (4 fields)

| # | FEMIS name | FEMIS label | Portal name | Portal label | Class |
|---|---|---|---|---|---|
| 1 | (empty) | Device Type | — | — | AMBIGUOUS |
| 2 | `digital_device_type[]` | Device Type | `digital_device_type[]` | Device Type | MATCH |
| 3 | `digital_device_at_home` | Yes | `digital_device_at_home` | Access to Digital Device | LABEL_DIFFERENCE |
| 4 | `internet_at_home` | Yes | `internet_at_home` | Internet Access | LABEL_DIFFERENCE |

**Portal-only:** (none)

---

## 4. Prior Discrepancy File Cross-check

From `data/output/audit_discrepancies_20260921_222600.json`:

| Type | Tab | Field | Status now |
|---|---|---|---|
| MISSING_IN_OURS | Personal Details | `address` | PRESENT_IN_PORTAL |
| MISSING_IN_OURS | Personal Details | `present_address` | PRESENT_IN_PORTAL |
| EXTRA_IN_OURS | Personal Details | `address_other` | REMOVED |
| EXTRA_IN_OURS | Personal Details | `present_address_other` | REMOVED |
| EXTRA_IN_OURS | Parents / Guardian | `guardian_qualification` | **STILL_PORTAL_ONLY** |
| MISSING_IN_OURS | Educational Details | `cocurricular_details` | PRESENT_IN_PORTAL |
| MISSING_IN_OURS | Educational Details | `result_percentage` | PRESENT_IN_PORTAL |
| EXTRA_IN_OURS | Educational Details | `transport_facility` | **STILL_PORTAL_ONLY** (name) |
| EXTRA_IN_OURS | Educational Details | `achievement_details` | REMOVED (now `cocurricular_details`) |
| EXTRA_IN_OURS | Educational Details | `shift` | **STILL_PORTAL_ONLY** |
| EXTRA_IN_OURS | Educational Details | `last_class_result` | REMOVED |
| EXTRA_IN_OURS | Health Details | `major_disability_text` | REMOVED |
| MISSING_IN_OURS | Digital Access | `digital_device_type[]` | PRESENT_IN_PORTAL |
| EXTRA_IN_OURS | Digital Access | `digital_device_type` | REMOVED |
| CONDITIONAL_FIELD | Personal Details | `is_bform_available` | CONDITIONAL |

---

## 5. Proposed STUDENT PORTAL STRUCTURE (PROPOSED — not implemented)

Target: group headings mirror FEMIS visual (tab-1 confirmed) / form_questions SECTION narrative; **field `name`s unchanged** (bot + DB contract).

```
TAB 1 — Personal Details
  Personal Information                    ← FEMIS (rename from Student Information)
    name, is_bform_available, b_form, gender, date_of_birth
  Birthplace & Nationality
    birth_province_id, birth_district_id, nationality, nationality_id
  Domicile Information                    ← FEMIS name
    domicile_province_id, domicile_district_id
  Address (Temporary)                     ← FEMIS "Address / Temporary Address"
    address_type, sector_id, sub_sector_id, village_id, housing_society_id,
    address, house, street, contact_number
  Permanent Address
    same_as_permanent_address, present_*, city_id, present_address,
    present_house, present_street
  Religion, Language & Other Details      ← FEMIS name
    religion, religion_id, language_id, mother_language_other, blood_group,
    email, girls_stipend, is_hafiz

TAB 2 — Parents / Guardian
  Father's Information
    father_* (12 fields)
  Mother's Information
    mother_* (10 fields)
  Orphan / Guardian Information              ← FEMIS "Orphan & Guardian Information"
    is_orphan, orphan_type, guardian_* (12 fields)
  (*guardian_qualification: PORTAL_ONLY vs FEMIS — keep on portal if desired; no FEMIS counterpart)*

TAB 3 — Educational Details
  Academic Information
    class_id, section_id, class_group_id, result_percentage, date_of_admission,
    admission_number, last_fde_institution_id, class_admitted_id,
    last_other_institution, medium_of_instruction, mode_of_study, shift
  Additional Information
    primary_education_completion_years, school_meal_program_availing,
    total_siblings, siblings_*, transport_facility, bus_route, scholarship,
    cocurricular_activities, scholarship_details, cocurricular_details
  (*shift / transport_facility: EXACT_IDENTITY on FEMIS — confirmed 3A.1.1)*

TAB 4 — Emergency Contact
  Emergency Contact Information
    emergency_name, emergency_contact, emergency_relation, emergency_relation_other

TAB 5 — IDPs Details
  Refugee / IDP Information               ← portal name; FEMIS SECTION "IDPs Details"
    is_refugee, is_registered_refugee, idp_status_id, refugee_card_number

TAB 6 — Health Details
  Disability Information                     ← FEMIS "Major Disability"
    has_major_disability, disability_types[], disability_certificate
  Mental Health
    has_mental_disability, mental_disability_type, mental_disability_other
  Other Medical Conditions                   ← FEMIS own card (portal currently nests under Mental Health)
    other_medical_condition
  Vision
    visually_fit, uses_glasses, glass_prescription, difficulty_seeing_board
  Hearing
    has_hearing_difficulties, uses_hearing_aid, hearing_aid_details,
    difficulty_listening
  Mobility
    difficulty_walking, uses_crutches_walker
  Learning Difficulties
    difficulty_reading_writing, difficulty_remembering, difficulty_concentrating
  Vaccination
    basic_vaccination_completed

TAB 7 — Digital Access
  Digital Access Information
    digital_device_at_home, digital_device_type[], internet_at_home
```

---

## 6. AMBIGUOUS / Unresolved

1. **Screenshots tabs 2–7:** ~~unconfirmed~~ **RESOLVED (3A.1.1)** — re-capture `*_20260924_183753.png` shows correct tab 7/7; headings in `portal_audit_20260924_183753.json`.
2. Empty-name FEMIS fields: Temporary Student ID, Disability Type textarea, Device Type textarea — dynamic widgets (**UNRESOLVED**, low impact; identity as FEMIS_ONLY widgets).
3. Portal-only: ~~all four~~ **only `guardian_qualification` remains PORTAL_ONLY** (high, confirmed). `shift`, `transport_facility`, `disability_certificate` → **EXACT_IDENTITY** on FEMIS (3A.1.1).
4. `portal_fields.json` = full-form dump (122 fields × all tabs) — not for tab counts.
5. YAML tab_4–7 flat maps — documented; not a portal bug.
6. form_questions Q46 "Qualification" in orphan block was not found as a named FEMIS control; live DOM wins over questions list for identity (**PORTAL_ONLY** for guardian_qualification).

---

## 7. Summary Counts

- FEMIS unique fields summed by tab (3A.1.1 extract): **133** (39+36+24+4+4+22+4)
- Portal unique `name` attrs by tab summed: **131** (38+37+24+4+4+21+3) — prior baseline
- Tab title matches: **7/7**
- Tab order matches: **7/7**
- Screenshot correct-tab matches: **7/7** (3A.1.1)
- Group structure: tab1 rename+portal split; tab2 rename; tab3 FEMIS 3 cards vs portal 2 h6; tab4 rename; tab5 rename; tab6 FEMIS 8 vs portal 7; tab7 rename
- Field names shared on same tab: majority MATCH; LABEL_DIFFERENCE common on radio questions + parent prefixes
- Portal-only open: **1 name** (`guardian_qualification`) — was 4 before 3A.1.1

---

## 8. Phase 3A.1 / 3A.1.1 Verification

| Check | Result |
|---|---|
| Docs-only deliverables (app code) | `docs/femis-portal-layout-map.md`, `docs/femis-field-identity-crosswalk.yaml` |
| Protected files unchanged this phase | `src/form_filler.py`, `src/main.py`, `config/field_mapping.yaml`, `femis-web/**` — no 3A.x edits (working-tree diffs are Phase 2 only) |
| DB schema/data | Unchanged (140 cols / 6 rows) |
| Tooling change | `audit_portal.py` only: panel IDs `tab-personal`…, file-input extract, force-panel screenshot, headings extract — not app/bot/portal code |
| Tests | See session report (53/53 expected) |

*End of Phase 3A.1 / 3A.1.1 read-only audit. No portal/bot/DB implementation performed.*
