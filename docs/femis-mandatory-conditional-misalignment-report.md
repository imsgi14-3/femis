# FEMIS Portal vs FemisBot Form — Mandatory & Conditional Misalignment Report

**Date:** 2026-09-28 (rev. 2 — adds over-enforcement inventory + Mother's-Income Housewife rule analysis; rev.2 corrections: `is_bform_available`, `mode_of_study`, `idp_status_id`, `is_registered_refugee`, `disability_types[]`, `mental_disability_type` reclassified as **correctly enforced** — §7a; **rev.2a — §6 fix list APPLIED to `form.js`/`form.html`**, verified 480/480 tests, see §6/§8 status columns; **rev.2b — sub-sector group now gated on Address Type = Sector** (temp + present — `#sub_sector_group`/`#present_sub_sector_group` shown iff type = `Sector`, so `sub_sector_id`/`present_sub_sector_id` are mandatory exactly when the portal requires them, clearing sooner doesn't unrequire `sector_id`; cascade still hides the group if the chosen sector has zero sub-sectors) **and `is_hafiz` confirmed NOT mandatory** — `required: false` in every portal capture and every `field_mapping.yaml` entry, absent from `mandatoryByTab`/`conditionalRequired`/HTML `required`, locked by test `[24e]`; **rev.2c — sector/sub-sector labels now carry the red asterisk** (`Sector *` / `Sub Sector *`, temp + present — HTML had none while `Address Type *` did; enforcement itself was already verified blocking: empty sector on Address Type = Sector → validation alert names Sector/Sub Sector and no save request fires; **rev.2d — mother_qualification now mandatory** (red asterisk; hidden-skip = mother-alive gating) **and mother_bps mandatory when mother_profession = Govt Employee** (`#mother_bps_group` gated + conditional rule; `conditionalRequired` trigger lookup extended to accept `<select>` triggers) **and orphan = Yes is corrected at selection time** when both parents are alive — click Yes → flips back to No + alert (previously only the save-time guard caught it); probes: 14/14; **rev.2e — date_of_admission is now a native calendar** (`type="date"`, replacing the inert `mm/dd/yyyy` text/pattern pair — stored values were already ISO, same as `date_of_birth`), **total_siblings is a number spinner** (`type="number" min=0 step=1`, like `siblings_same_institution`) **with a leading-zero sanitizer** (`01`→`1`, `007`→`7`, digits only — probe: 15/15), **portal asterisks added to the conditional detail labels** (Scholarship Details, Achievement Details, Specify Relation — the conditional rules/groups already existed and are now locked by test [31]-[33]); **rev.2f — `guardian_relation_other` is now enforced** (conditional rule `guardian_relation=Other` + show/hide via existing selectToggle, portal asterisk on "Other Relation", test [34]; live probe 12/12: hidden/not-required when relation=Uncle, blocked when Other + empty, saves when filled, stores to DB; father_name/father_cnic intentionally stay unconditional when father is dead — matches portal `Father's Name*` `required=True` in all 6 captures)
**Audit mode:** READ-ONLY live portal inspection (Ayat Mubeen, existing record — edit page). No CNIC typed, no field values edited, no Save/Submit clicked, no record created or modified. Browser: headed Chromium this one time (Edge channel `msedge` is the standing rule for future runs; session saved to `data/logs/femis_session.json`).

**Evidence sources**

| Source | What it gives |
|---|---|
| Live edit-page capture of **Ayat Mubeen** (this session, 7 tabs, read-only) | Current portal `required` attrs + per-field visibility for a real record → `data/output/portal_edit_audit_20260928_0034_ayat.json` |
| `data/output/portal_audit_20260924_183753.json` (create-form audit) | Portal conditional **show/hide map** (click-conditionals) + create-mode `required` flags |
| **`config/field_mapping.yaml`** | Portal-side `required` flags — **mixed file**: curated primary entries (+ conditional `note:` lines) vs 222 auto-discovered duplicates. Use primaries/notes only (§7a) |
| `femis-web/static/form.js` (`validateTab`, `mandatoryByTab`, `conditionalRequired`) | Our effective enforcement — post-rev.2a (fixes applied, §6) |
| `femis-web/templates/form.html` (56 `required` attrs) | **Inert** — no `checkValidity()`/`reportValidity()` anywhere; Save is `type="button"` (`form.html:1236`) with `preventDefault` (`form.js` submit handler) |

**Four structural facts that govern every row below** *(rev.2a: facts 2–3 describe the pre-fix state the §1/§2 verdicts were written against; both are now fixed — see §6)*

1. **Ours enforces only what `validateTab()` checks** (JS `mandatoryByTab` + `conditionalRequired` + guards). HTML `required` attributes have no effect.
2. ~~**`validateTab()` does not skip hidden fields** → any `mandatoryByTab` field inside a hidden conditional group blocks Save even though the user cannot see it.~~ **FIXED (rev.2a):** hidden-group fields are skipped (`isHiddenWithin`).
3. ~~**`validateTab()` runs in exactly one place** — the Save & Next click, for the **active tab only**… final Submit validates only tab 7.~~ **FIXED (rev.2a):** per-save still validates the active tab; final Submit now validates all 7 tabs.
4. **Portal enforces dynamically**: `required` flags change with conditionals (create-audit recorded `father_contact`/`guardian_*` required only after their trigger fired). Live-edit flags reflect Ayat's resting state.

Severity: **H** = bot save will 422/fail or wrongly blocks the operator · **M** = wrong UX/validation, no data loss · **L** = cosmetic/ambiguity.

---

## 1. Required-field mismatches (per tab)

### Tab 1 — Personal Details
Portal live required (17): `name, b_form, gender, date_of_birth, birth_province_id, birth_district_id, nationality, address_type, sector_id, sub_sector_id, contact_number, city_id, present_address_type, present_sector_id, present_sub_sector_id, religion, language_id`
Ours JS enforced (13): `name, is_bform_available, gender, date_of_birth, birth_province_id, birth_district_id, nationality, address_type, contact_number, city_id, religion, language_id, email`

| # | Field | Portal | Ours | Sev | Note |
|---|---|---|---|---|---|
| 1.1 | `b_form` | required | HTML-only (inert); NOT in `mandatoryByTab[0]` | **H** | Portal rejects empty CNIC; we never block |
| 1.2 | `sector_id`, `sub_sector_id` | required (Address Type = Sector — Ayat state); create-capture without type selected: `required=false` | ✅ required, visibility-gated — in `mandatoryByTab[0]`; sub-sector group shown iff `address_type=Sector` (rev.2b) | ✅ | Sector is the common case |
| 1.3 | `present_address_type`, `present_sector_id`, `present_sub_sector_id` | required | ✅ required, visibility-gated — present sub-sector group shown iff `present_address_type=Sector` (rev.2b) | ✅ | Permanent trio aligned |
| 1.4 | `is_bform_available` | **required** (mapping primary L8 `is_cnic_form_b_available: required: true`; user first-hand confirmed) | required (`mandatoryByTab[0]`) | ✅ | Aligned — rev.2 correction (earlier cited an auto-discovered duplicate that says `false`, see §7a) |
| 1.5 | `email` | live: NOT required; create-capture + `field_mapping.yaml:608` say required | required | M | **Ambiguous — §4** |
| 1.6 | `house`, `street` (+ `present_house/present_street`) | create-capture: required; live: visible but NOT required | HTML-only + attr-flip (`form.js:208-209`) → not enforced by `validateTab` | M | §4 |

### Tab 2 — Parents / Guardian
Portal live required (9 unique): `father_name, father_cnic, is_father_alive, father_monthly_income, mother_name, is_mother_alive, mother_monthly_income, is_orphan, orphan_type`
Ours JS enforced (16): those **plus** `father_profession, father_qualification, mother_profession, mother_qualification, mother_bps (conditional), guardian_name, guardian_cnic, guardian_relation, guardian_contact, guardian_profession, guardian_income`

| # | Field | Portal | Ours | Sev | Note |
|---|---|---|---|---|---|
| 2.1 | `guardian_*` (6 fields) | `required: true` in mapping, **but visible only when `is_father_alive=0`** (click-map); live: hidden + `req=False` | required **always** AND always visible (`form.js:423-427` forces display) | **H** | Requirement matches portal **when shown**; the bug is we show+require for every student → §7 |
| 2.2 | `father_profession`, `father_qualification`, `mother_profession` | `required: true` when their parent-alive group is shown (mapping + create-capture) | required always; `validateTab` counts them **even when group hidden** | **H** | Father-dead/mother-dead records phantom-block → §7 |
| 2.3 | `father_contact`, `mother_contact` | `required: true` when parent alive (mapping) | never required | M | Gap (HTML + JS) |
| 2.4 | `mother_monthly_income` | mapping `required: false` + note *"Required unless mother_profession = Housewife"*; live attr `req=True` | conditional guard (`form.js:639-644`) | M | **See §8 — rule exists but misbehaves** |
| 2.5 | `*_profession_other`, `guardian_relation_other` | mapping `required: false` (Other-triggered fields not portal-required) | shown via toggle, never required | ✅ | **Aligned** (was previously listed as gap — corrected rev.2) |
| 2.6 | `orphan_type` | live `req=True`; mapping `required: false` (stale) | conditional when `is_orphan=1` (`form.js:610`) | L | Aligned for Yes; §4 |
| 2.7 | `mother_qualification` | required (early create-captures `req=True` + user first-hand); live edit: hidden-group `req=False` | ✅ required in `mandatoryByTab[1]` (hidden-skip = mother-alive gating), red asterisk added (rev.2d) | ✅ | Was never enforced before rev.2d |
| 2.8 | `mother_bps` | required when `mother_profession = Govt Servant/Employee` (early create-captures `req=True` + user first-hand); hidden otherwise | ✅ conditional rule `mother_bps ← mother_profession = Govt Employee` + `#mother_bps_group` visibility gate + asterisk (rev.2d; `conditionalRequired` trigger lookup extended to support `<select>`) | ✅ | Was never enforced before rev.2d |
| 2.9 | `is_orphan = Yes` with both parents alive | portal forbids the combination | save-time guard existed; **selection-time correction added rev.2d** — clicking Yes flips back to No + alert explains (parents-alive listener unchanged) | ✅ | Was possible to select until rev.2d (blocked only at save) |

### Tab 3 — Educational Details
Portal live required (12): `class_id, section_id, date_of_admission, admission_number, class_admitted_id, shift, medium_of_instruction, school_meal_program_availing, total_siblings, transport_facility, scholarship, cocurricular_activities`
Ours JS enforced (12): same minus `shift`, plus `mode_of_study`

| # | Field | Portal | Ours | Sev | Note |
|---|---|---|---|---|---|
| 3.1 | `shift` | required (live + mapping `True`) | HTML `required` (`form.html:699`) **not in `mandatoryByTab[2]`** → inert | **H** | Never enforced by us |
| 3.2 | `mode_of_study` | **required** (mapping primary L1853 `required: true`; user first-hand confirmed) | required (`mandatoryByTab[2]`) | ✅ | Aligned — rev.2 correction (auto-copy L863 says `false`, see §7a) |
| 3.3 | `primary_education_completion_years` | mapping `false`; create-capture `true`; live `false` | never required | L | §4 |
| 3.4 | `bus_route` | mapping `required: true` | conditional-required when Institution Bus (`form.js:620`) | ✅ | **Aligned** (was flagged as possible over — corrected rev.2) |

### Tab 4 — Emergency Contact
Ours (`emergency_name, emergency_contact, emergency_relation`) == portal live — **fully aligned** ✅. `emergency_relation_other`: ours conditional for `Other|Others`, mapping `true` for Specify Relation → aligned (ours is a harmless superset of the portal's `Others`).

### Tab 5 — IDPs Details
Portal live required: `is_refugee`. Mapping: `is_refugee=true`; `idp_status`/`is_registered_as_refugee` carry `required: false` **but `note: Required when is_refugee = Yes`** (→ mandatory when triggered, rev.2); `refugee_card_number` (create-capture `true` after trigger).

| # | Field | Portal | Ours | Sev |
|---|---|---|---|---|
| 5.1 | `idp_status_id` | required when `is_refugee=Yes` (mapping note *"Required when is_refugee = Yes"*; user first-hand confirmed) | conditional-required when `is_refugee=1` (`form.js:613`) | ✅ | Aligned — rev.2 correction (mapping's bare `required: false` field ignores its own note) |
| 5.2 | `is_registered_refugee` | required when `is_refugee=Yes` (mapping note; user first-hand confirmed) | conditional-required (`form.js:614`) | ✅ | Aligned — rev.2 correction |
| 5.3 | `refugee_card_number` | required when shown (create-capture) | conditional-required when `is_registered_refugee=1` (`form.js:615`) | ✅ aligned |

### Tab 6 — Health Details
Portal live required (13 unique): `has_major_disability, has_mental_disability, visually_fit, uses_glasses, difficulty_seeing_board, has_hearing_difficulties, uses_hearing_aid, difficulty_listening, difficulty_walking, uses_crutches_walker, difficulty_reading_writing, difficulty_remembering, difficulty_concentrating`
Ours JS (12): same **minus `uses_hearing_aid`**

| # | Field | Portal | Ours | Sev | Note |
|---|---|---|---|---|---|
| 6.1 | `uses_hearing_aid` | required **always** (live `req=True` + mapping `True`), visible always | only conditional-required when `has_hearing_difficulties=1` (`form.js:619`); group hidden otherwise (`form.js:415`) | **H** | Visibility AND required mismatch |
| 6.2 | `hearing_aid_details` | requiredness conflicting (create-capture `true` vs mapping/live `false`); **trigger = `has_hearing_difficulties=1`** (click-map) | shown on **`uses_hearing_aid=1`** (`form.js:376`); never required | **H** (trigger) / §4 (requiredness) | Wrong trigger regardless of requiredness |
| 6.3 | `disability_certificate` | create-capture `true` vs mapping `false` vs live `false`-when-hidden | never required | §4 | Re-verify before adding |
| 6.4 | `disability_types[]` | required when `has_major_disability=Yes` (user first-hand confirmed; `phase3b11:125` marks **required**) | conditional-required (`form.js:616`) | ✅ | Aligned — rev.2 correction |
| 6.5 | `mental_disability_other` | create-capture `true` vs mapping n/a | shown (`form.js:369`) but never required | §4 | |
| 6.6 | `mental_disability_type` | required when `has_mental_disability=Yes` (user first-hand confirmed; `phase3b11:126` marks **required**) | conditional-required (`form.js:617`) | ✅ | Aligned — rev.2 correction |
| 6.7 | `glass_prescription` | required when `visually_fit=0` (mapping `true` + create-capture) | conditional-required same (`form.js:618`) | ✅ aligned |
| 6.8 | `basic_vaccination_completed` | not required | not required | ✅ aligned |

### Tab 7 — Digital Access
Portal live required: `digital_device_at_home, internet_at_home` — ours identical ✅. `digital_device_type[]` conditional-when-Yes both sides ✅.

---

## 2. Conditional visibility mismatches ("visible only when")

| # | Rule | Portal (click-map) | Ours | Sev |
|---|---|---|---|---|
| 2.1 | `girls_stipend` | shown only when `gender=Female`; hidden for Transgender | **always visible** (no toggle in form.js) | M |
| 2.2 | `domicile_province_id`/`domicile_district_id` | shown only when `nationality=Pakistani` | **always visible** | M |
| 2.3 | `is_hafiz` | shown only when `religion=Muslim` | **always visible** | M |
| 2.4 | `religion_id` (Other Religion) | shown when `religion=Non-Muslim` | ✅ working — `selectToggle("religion", ..., ["Non-Muslim"])` (`form.js:244`) | ~~H~~ **retracted rev.2** — earlier claim that the toggle used `["Other"]` was a report error (§6 item 6) |
| 2.5 | Guardian block | visible **only when `is_father_alive=0`** | **always visible** (`form.js:423-427`) | **H** (pairs §1.2.1, §7) |
| 2.6 | `uses_hearing_aid` | always visible | hidden until `has_hearing_difficulties=1` (`form.js:415`) | **H** (pairs §1.6.1) |
| 2.7 | `hearing_aid_details` | appears on `has_hearing_difficulties=1` | appears on `uses_hearing_aid=1` (`form.js:376`) | **H** (pairs §1.6.2) |
| 2.8 | `guardian_bps` | shown when `guardian_profession=Govt Employee` | no toggle (no `guardian_bps_group` container) | L |
| 2.9 | `nationality_id`, address-type family, `b_form` on `is_bform_available=0`, bus/scholarship/cocurricular/idp/refugee/device/disability/glass groups | per-trigger | ✅ aligned (`form.js:165-234, 413-421, 373`) | ✅ |

---

## 3. Conditional-required mismatches ("required only when")

| Ours entry (`form.js:609-623`) | Portal verdict | Status |
|---|---|---|
| `orphan_type` ← `is_orphan=1` | live required | ✅ |
| `scholarship_details` ← `scholarship=1` | required when shown | ✅ |
| `cocurricular_details` ← `cocurricular=1` | same | ✅ |
| `bus_route` ← Institution Bus | mapping `required: true` | ✅ (rev.2 correction) |
| `refugee_card_number` ← `is_registered_refugee=1` | required when shown | ✅ |
| `emergency_relation_other` ← `Other\|Others` | mapping `true` (Specify Relation) | ✅ |
| `digital_device_type[]` ← device=Yes | same | ✅ |
| `glass_prescription` ← `visually_fit=0` | same | ✅ |
| `idp_status_id` ← `is_refugee=1` | required when `is_refugee=Yes` (mapping note + user first-hand) | ✅ (rev.2) |
| `is_registered_refugee` ← `is_refugee=1` | required when `is_refugee=Yes` (mapping note + user first-hand) | ✅ (rev.2) |
| `disability_types[]` ← major=Yes | required when `has_major_disability=Yes` (user first-hand; `phase3b11:125`) | ✅ (rev.2) |
| `mental_disability_type` ← mental=Yes | required when `has_mental_disability=Yes` (user first-hand; `phase3b11:126`) | ✅ (rev.2) |
| `uses_hearing_aid` ← hearing=Yes | portal requires **unconditionally** | ✗ under → §1.6.1 |

**Portal conditionals we never enforce** (re-verified rev.2): `father_contact`/`mother_contact` ← parent alive (mapping `true`); `shift` (static). Previously-listed gaps `mother_language_other`, `disability_certificate`, `mental_disability_other`, `hearing_aid_details` requiredness → moved to §4 (conflicting evidence).

---

## 4. Portal-internal inconsistencies (create-capture vs live-edit vs mapping) — re-verify before acting

Three evidence sources disagree on these; do NOT "fix" ours until re-verified in a controlled create-mode run:

- `email` (create+mapping tab_1: required / live + other mapping copies: not)
- `house`, `street`, `present_house`, `present_street` (create: required / live: not, though visible)
- `mother_cnic`, `father_contact`/`mother_contact` (create: required / live: not — probably alive-gated)
- `mother_language_other` (create resting attr: required / mapping `false`) → our non-enforcement may actually be correct
- `disability_certificate` (create: required / mapping `false` / live hidden-false)
- `hearing_aid_details` requiredness (create: true / mapping+live: false) — the **trigger** mismatch in §2.7 stands regardless
- `primary_education_completion_years` (create: required / mapping+live: not)
- `orphan_type` (live+create: required / mapping: false — mapping likely stale)
- `mother_monthly_income` for Housewife — live attr `required=True` contradicts mapping `false` + note (§8)

---

## 5. Our internal disagreements (HTML `required` vs JS enforcement)

HTML-only (never enforced): `b_form, house, street, shift` (+ conditional attr flips at `form.js:175, 208-209` — also inert).
JS-only (enforced, not HTML-required): `father_qualification, father_profession, father_monthly_income, mother_profession, school_meal_program_availing, difficulty_seeing_board, difficulty_reading_writing, difficulty_remembering, difficulty_concentrating`.

---

## 6. Priority fix list — **APPLIED** (all items implemented; see per-item status)

**P1 — portal will reject / Save cannot succeed (under-enforcement):**
1. ✅ **APPLIED** — added to `mandatoryByTab[0]` (visibility-gated): `b_form`, `sector_id`, `sub_sector_id`, `present_address_type`, `present_sector_id`, `present_sub_sector_id`. *(rev.2b)*: `#sub_sector_group` / `#present_sub_sector_group` are also shown directly by the address-type toggle (they were previously shown only by the sector→sub-sector cascade, leaving `sub_sector_id` unenforced until options loaded); cascade keeps hiding the group when the selected sector has zero sub-sectors.
2. ✅ **APPLIED** — `shift` added to `mandatoryByTab[2]`.
3. ✅ **APPLIED** — `validateTab` now skips hidden fields via `isHiddenWithin()` (ancestor `display:none` walk scoped to the tab pane; fixes phantom blocks §1.2.2). Field lookups are pane-scoped (`fieldControl`/`controlValue`/`fieldLabel` helpers).
4. ✅ **APPLIED** — `uses_hearing_aid` → unconditional mandatory (`mandatoryByTab[5]`) + `#hearing_aid_group` always visible (HTML `display:none` removed, JS gate removed); `hearing_aid_details` trigger repointed to `has_hearing_difficulties=1`.
5. ✅ **APPLIED** — `conditionalRequired` entries added: `father_contact` ← `is_father_alive=1`, `mother_contact` ← `is_mother_alive=1`.
6. ⚪ **NO-OP (report error)** — the religion toggle was already correct: `form.js:244` uses `["Non-Muslim"]` (not `["Other"]` as §2.4 claimed). Verified working: `#other_religion_group` shows iff `religion=Non-Muslim`. §2.4 finding retracted.
7. ✅ **APPLIED** — Mother's-Income Housewife rule (8.1–8.4): asterisk now `#mother_income_required`, hidden by default, toggled by `mother_profession` change (clears for Housewife/empty); guard runs inside every `validateTab` call (incl. the new all-tabs final submit → 8.2); guard skips when either control's group is hidden (8.3); comparison is trim + case-insensitive (8.4 mitigation; string coupling remains by design — values come from the same `portal_options.json`).

**P2 — we wrongly block the operator (over-enforcement → detail §7):**
8. ✅ **APPLIED** — `#orphan_fields` split: `#orphan_type_group` ← `is_orphan=1`, new `#guardian_group` ← `is_father_alive=0` (`radioToggle`); the 6 guardian fields moved out of `mandatoryByTab[1]` into a `conditionalRequired` entry (trigger `is_father_alive=["0"]`); force-display block removed.
9. ✅ **APPLIED** — via #3: `father_profession`/`father_qualification`/`mother_profession`(+qualification/contact) live inside `father_details_group`/`mother_details_group`, which are hidden when the parent is not alive → automatically skipped by `isHiddenWithin`.
10. *(rev.2)* ~~Drop `mode_of_study`, `is_bform_available`, `idp_status_id`, `is_registered_refugee`, `disability_types[]`, `mental_disability_type`~~ — **RETRACTED**: all six are mandatory in FEMIS (user first-hand + mapping primary entries/notes). Keep our enforcement as-is (§7a).

**P3 — visibility parity:** ✅ **APPLIED** — `girls_stipend`←`gender=Female` (`#girls_stipend_group`), `domicile_*`←`nationality=Pakistani` (`#domicile_fields`), `is_hafiz`←`religion=Muslim` (`#hafiz_group`), `guardian_bps`←`guardian_profession=Govt Employee` (`#guardian_bps_group`).

**Additional change beyond the original list (required for 8.2):** final Submit now validates **every tab** (loop over `tabIds` with pane override) — FEMIS requires the complete record at submit, and previously tab jumps left skipped tabs unvalidated.

**Verification (post-fix):** 480/480 checks green — offline suites 430 (`test_data_integrity` 24, `test_mandatory_field_reconciliation` **75** (was 57; locks new state), `test_submission_status` 12, `test_bot_job_*` 62+124+13+54, `test_created_at_*` 11+26, `test_persistence_roundtrip` 29) + browser `test_prefill_rerender` **50** (was 30; now fills tabs 1-6 and exercises all-tabs final validation). `test_bot.py` (live-portal record creation) not run per standing no-create rule. Portal session saved — future audits can skip login. Future browser runs → Edge (`channel="msedge"`).

---

## 7. Over-enforcement inventory — where our form blocks more than FEMIS does

(Rev.2 slimmed this list: six fields previously here were retracted — see §7a. What remains is either *conditional-visibility* mismatch (portal requires only when a group is shown) or §4-ambiguity.)

Consolidated answer to "what does our form treat as mandatory that FEMIS does not". **Evidence standard (rev.2):** mapping **primary** entries and their `note:` lines + first-hand portal knowledge govern; auto-discovered duplicates and DOM `required` snapshots do NOT (§7a).

| Field | Portal | Ours marks mandatory via | Why it hurts |
|---|---|---|---|
| `mother_monthly_income` (non-Housewife cases) | `required: false` + *"Required unless mother_profession = Housewife"* note | guard `form.js:642` — **and the red `*` is hard-coded** (`form.html:512`) | See §8 — rule misfires; asterisk never clears |
| `guardian_*` ×6 | required **only when father not alive** | `mandatoryByTab[1]` unconditionally + always-visible (`form.js:423-427`) | Every father-alive student is asked 6 questions portal doesn't ask; record values diverge |
| `father_profession`, `father_qualification`, `mother_profession` | required **only when that parent's group is visible** | `mandatoryByTab[1]` unconditionally; `validateTab` counts hidden fields (`form.js:584`) | Parent-dead records **cannot pass Save at all** (fields hidden but flagged) |
| `email` (arguable) | live `req=False` / mapping tab_1 `true` | `mandatoryByTab[0]` | §4 — pending re-verify |

**Explicitly checked and NOT over-enforced:** `bus_route` (mapping primary `true`), `*_profession_other` / `guardian_relation_other` (mapping `false` — we correctly don't require), `mother_language_other` / `disability_certificate` / `hearing_aid_details` (§4 conflicts, hold), and — **rev.2 retraction —** `is_bform_available`, `mode_of_study`, `idp_status_id`, `is_registered_refugee`, `disability_types[]`, `mental_disability_type` (see §7a: all mandatory in FEMIS; our enforcement is correct).

### 7a. Evidence-quality warning — why rev.1 wrongly called six fields "not required"

`config/field_mapping.yaml` is **self-contradicting by design**: 222 of its entries are machine-appended `Auto-discovered from portal DOM` copies, which mostly carry a lazy `required: false`. The curated primary entries say otherwise — always check both:

| Field | Primary entry (authoritative) | Auto-discovered copy (trap) |
|---|---|---|
| `is_bform_available` | L8 `is_cnic_form_b_available: required: **true**` | L126/L969 `required: false` |
| `mode_of_study` | L1853 `required: **true**` (Day Scholar/Boarders) | L863 `required: false` |
| `idp_status_id` | L2500 `required: false` **+ `note: Required when is_refugee = Yes`** | — |
| `is_registered_refugee` | L2506 `required: false` **+ `note: Required when is_refugee = Yes`** | — |
| `disability_types[]` / `mental_disability_type` | conditional-mandatory per FEMIS flow (confirmed first-hand; `phase3b11:125-126` marks both **required**) | bare `required: false` copies |

Second trap: **DOM `required` snapshots are not proof** — fields hidden at capture time (Ayat: `is_refugee=No`, disability=No) show `required=False`, and even visible fields disagree across snapshots (`shift`: create-snapshot `false` vs live `true` vs mapping `true`). FEMIS enforces at least partly server-side; snapshot attrs under-report. First-hand portal behavior outranks both.

---

## 8. Mother's Income "not mandatory if Housewife" — why it wasn't working (FIXED)

**What the rule should be** (per `config/field_mapping.yaml:1177-1181`): field is `required: false` on the portal overall, with the note *"Required unless mother_profession = Housewife"* — i.e. **only enforce when the mother's profession is selected and is not Housewife**.

**What we have now (post-fix):** guard inside `validateTab` + a visibility-gated asterisk:

```js
if (motherProf && motherIncome &&
    !isHiddenWithin(pane, motherProf) && !isHiddenWithin(pane, motherIncome)) {
    var mp = (motherProf.value || "").trim().toLowerCase();
    if (mp && mp !== "housewife" && !motherIncome.value) {
        missing.push("Mother's Income (per month)");
    }
}
// asterisk: #mother_income_required shown by toggleStar() only when
// profession is non-empty and != "housewife" (case-insensitive)
```

**Defects found (in effect order) — fix status in last column:**

| # | Defect | Evidence | Effect | Fix status |
|---|---|---|---|---|
| 8.1 | **Static red asterisk never clears** — the label hard-codes `<span class="text-danger">*</span>` regardless of selected profession | `form.html:512` | The form *always visually marks it mandatory*, even when Housewife is selected — the most likely thing you observed. Nothing toggles it (no JS touches this label). | **FIXED** — span now `#mother_income_required` (hidden by default); `toggleStar()` in form.js shows it only when profession is non-empty and ≠ Housewife |
| 8.2 | **Rule only runs on Save & Next of that exact tab** — `validateTab` is called solely at `form.js:668`; tab switches don't validate (`form.js:510-520`); final Submit validates only tab 7 | structural | If the operator never clicks Save & Next while on the Parents tab, the exception (and the requirement) never runs at all — enforcement is inconsistent: sometimes blocks, sometimes silent. | **FIXED** — final Submit now loops `tabIds` and validates every pane (guard runs as part of tab-2's validation); per-save behavior unchanged |
| 8.3 | **Invisible-state dead zone** — when `is_mother_alive=0` the whole mother group is hidden (`form.js:301`), so `motherProf.value === ""` → guard skips → rule inoperative; meanwhile `mother_profession` itself is still in `mandatoryByTab[1]` → phantom "Mother's Profession" block (hidden field counted, fact #2) | `form.js:642` + `form.js:555` | Mother-dead records get a phantom block on profession and **no** income check — both wrong vs intent. | **FIXED** — guard now requires both controls visible (`isHiddenWithin`), and `validateTab` skips hidden `mother_profession` (phantom block gone) |
| 8.4 | **Brittle exact-string coupling** — `!== "Housewife"` depends on the option value being byte-exact. Current `portal_options.json` `mother_professions` = `… \| Housewife \| Other` matches today; any re-wording (`House Wife`, `Homemaker`, localized labels) silently reverts the rule to "always required" with no error | `form.js:642`, `portal_options.json` | Latent regression with zero signal. | **MITIGATED** — trim + case-insensitive compare (`"House Wife"`-style casing variants no longer break; semantic renames still would — `portal_options.json` remains the single source) |
| 8.5 | *(portal-parity caveat)* live portal attr on Ayat's record shows `mother_monthly_income required=True`, contradicting the mapping note — whether FEMIS server-side actually rejects empty income for Housewife is unverified (§4) | live capture | Fixing our side may still leave a portal 422 if portal is stricter; verify in create-mode. | open (§4 — needs a controlled create-mode check) |

**Fix direction — all applied (rev.2):** (a) ✅ conditional asterisk; (b) ✅ guard runs at final Submit via all-tabs validation; (c) ✅ visibility guard + `isHiddenWithin` covers hidden profession; (d) ⚠ partial — trim + case-insensitive instead of `data-`/index (single source remains `portal_options.json`); (e) open — portal behavior needs a controlled create-mode check (§4).
