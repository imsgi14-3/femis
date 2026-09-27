# Phase 3B.14 — Mandatory Validation & Conditional-Rule Reconciliation

**Date:** 2026-09-27
**Status:** COMPLETE — STOP (read-first / reconciliation only)
**Scope rule honored:** no application code, template, model, schema, DB data, or test
was modified; no rule was implemented; no commit. **Only this document was created.**
Baseline: HEAD `a35f3c0`, clean tree, post-3B.13 (F1/F2/F3/F5 fixed, F4 open).

---

## 0. Executive summary

| Question | Answer |
|---|---|
| How many of the 38 requirements are server-enforced? | **0.** Every mandatory/conditional rule is client-side only; the server performs **only** B-Form uniqueness + partial authz/lock on `save-tab` |
| Rule-status tally (38) | **MISSING 2** (R1, R2) · **PARTIAL — UI/JS only 30** · **FORMAT/RANGE — server validation missing 3** (R13–R15) · **CONDITIONAL — semantics need confirmation 1** (R35) · **NOT APPLICABLE 2** (R16, R23) |
| Can a direct HTTP request bypass everything? | **Yes — all 38.** `app.py:470-544` contains no mandatory/conditional/format check |
| Can the plain UI bypass the JS rules? | **Yes.** Tab navigation is free (`form.js:510-520`); final-submit validates **only the active tab (7)** (`form.js:668`, `:705-706`) — tabs 1–6 rules never run if the user never clicks Save & Next on them |
| Does HTML `required` enforce anything? | **Effectively no.** 56 controls carry `required`, but nothing ever calls `checkValidity`/`reportValidity` (0 hits), the Save control is `type="button"` (`form.html:1236`), and the only submit path is `preventDefault`ed (`form.js:485`) |
| Ambiguous rules that must NOT be invented | **8 decision items** (§7: guardian applicability, qualification/income scope, ISO-vs-MM/DD/YYYY legacy dates, crutches conditional, B-Form conditionality, literal `'None'` placeholders, whole-record-vs-payload scope, legacy `'Yes'` values) |
| Existing tests | 14 suites run unchanged: **470/470 green** (440 baseline incl. the 57-check static reconciliation test + 30 prefill) |
| DB / repo | DB **9/9** identical to phase-start snapshot (only probe-insert churn hash); tree **clean**, HEAD unchanged, 0 staged |

---

## 1. Method & evidence base

All findings are taken from the committed tree at `a35f3c0` (file:line citations), from the
canonical DB (read-only `mode=ro` queries), from the existing test suite outputs, and from
prior-phase recorded probes (3B.11 live probe, 3B.12/13 API fixtures). **No write probe was
sent in this phase** (bypass is proven by code reading + existing test behavior, §3).

Prior authoritative material reconciled:

- `docs/phase3b11-local-functional-integrity-audit.md` §4 (30-item requirement matrix, 4 discrepancies) and §10 (5 pending admin rulings).
- `test_mandatory_field_reconciliation.py` (57 static checks locking current state).
- This phase **corrects one 3B.11 claim**: item 9 states "no `pattern` attr" for
  `date_of_admission` — the current `form.html:677` **does** carry
  `pattern="\d{2}/\d{2}/\d{4}"` (3B.11's test regex only searched the JS file). The
  correction does not change the conclusion: the pattern is native-browser-only and inert
  on the AJAX save path (§2, §4-R13).

---

## 2. Validation layers located (investigation A)

| Layer | Location | What it actually enforces |
|---|---|---|
| HTML `required` | 56 control tags in `form.html` (name, b_form, gender … uses_crutches_walker) | **Nothing on the save path.** Native constraint validation only runs before form submission; the save button is `type="button"` (`form.html:1236`), there is no `checkValidity`/`reportValidity` call anywhere (`form.js` grep = 0 hits), and `submit` is `preventDefault`ed (`form.js:485`). Only edge: Enter-key implicit submission can raise a native bubble — but submission is prevented, so no data flows |
| HTML `pattern` | `form.html:677` `date_of_admission` `pattern="\d{2}/\d{2}/\d{4}"` | Same as above — inert on the AJAX path |
| HTML range-by-construction | `class_admitted_id` radios are **rebuilt in-range** by `form.js:431-467` (`lo/hi` from class number); generated radios get `.required = true` (`form.js:454`) | UI offers only valid values; `.required` inert; no re-check of value at save |
| JS `mandatoryByTab` | `form.js:550-576` — per-tab absolute lists (tabs 0–6) | Non-empty check of active tab's fields, **at Save/Submit click only** (`form.js:668`) |
| JS `conditionalRequired` | `form.js:609-623` — 13 rules `{fields, trigger, values}` | Trigger = `input[name=trigger]:checked` **UI state only**, scoped to active tab |
| JS inline guards | mother income unless `Housewife` (`form.js:639-644`); orphan=1 forbidden when both parents alive (`form.js:646-654`) | UI state at click time |
| JS formatting (not validation) | CNIC auto-mask `form.js:24-34` (b_form/father/mother/guardian), mobile mask `form.js:36-39` | Normalizes input only — no length/format rejection |
| JS value-type limits | `save` collects only `activeTab` controls (`form.js:671-695`), skips invisible (`:680`); radio value taken only when `checked` (`:681-682`) — unchecked radios → key **absent** (F4 root) | — |
| Server `api_save_tab` | `app.py:470-516` | student existence; teacher class/section check (update branch only, `:486-491`); lock check (`:492-493`, update branch only); **B-Form uniqueness** (`:494-504`, `_b_form_conflict` `:444-459`). **No required/conditional/format check.** Create branch has **no auth check at all** (3B.11 live probe created a row with no session) |
| Server `api_final_submit` | `app.py:519-544` | student_id presence; B-Form uniqueness; sets `submitted=True` (`:535`). **No required/conditional/format check — and no lock/teacher check** |
| Server `submit` (legacy) | `app.py:570-592` | B-Form uniqueness only; `Student(**cols)` + `submitted=True` |
| Server `_map_form_data` | `app.py:431-437` + `FORM_FIELD_MAP` `:415-428` | Key→column mapping; **silently drops unknown keys**, keeps everything that is a `Student` attribute — no value validation |
| Model / schema | `app.py:36-195`, SQLite DDL | NOT NULL: **`id`, `created_at` only**; unique index `uq_students_b_form`; every data column nullable `String` — **no domain/range constraints** |
| B-Form | mask (JS), `required` (HTML, unconditional), uniqueness (server) | Format/length **never validated**; emptiness never validated server-side |
| Date parsing | none | `date_of_birth` is `type="date"` (native format, inert on AJAX path); `date_of_admission` is **text** (`form.html:677`) — presence only in JS |
| Shared helpers | `_b_form_conflict`, `_b_form_digits` (`app.py:440-459`), `formatCNIC`/`formatMobile` (`form.js:24-39`) | Uniqueness + formatting only — **no shared required/conditional validator exists** |
| WTForms or equivalent | **None** — plain Flask `request.get_json()` / `request.form` | — |
| Existing mandatory tests | `test_mandatory_field_reconciliation.py` (static), `test_data_integrity.py` (API behavior) | §6 |
| Prior reconciliation docs | `phase3b11…` §4 (30 items, 4 gaps), `phase3b1-data-contract-audit`, `femis-separation-audit` | §1 |

---

## 3. Real write paths & bypass analysis (investigation B)

| # | Path | Client enforcement | Server enforcement | Bypassable? |
|---|---|---|---|---|
| P1 | Browser → Save & Next → `validateTab(activeTab)` → `POST /api/save-tab` (`form.js:666-716`) | JS rules **for the active tab only, at click time** | b_form uniqueness; update-branch authz+lock (`app.py:486-497`); create branch **no auth** | **Yes** — crafted POST skips JS entirely; even UI-side, other tabs are unchecked at this moment |
| P2 | Browser → Submit (tab 7) → `validateTab(tab-7 only)` → `POST /api/final-submit` | **Tab 7 fields only** (`form.js:668` + `:705-706`); tabs 1–6 not re-validated | b_form uniqueness + `submitted=True` (`app.py:529-535`); **no lock/teacher check** | **Yes, twice over** — (a) crafted POST, (b) plain UI: free tab navigation (`form.js:510-520`) lets a user jump to Submit and skip every earlier tab's JS rules |
| P3 | Direct HTTP `POST /api/save-tab` (no browser) | none | as P1 | **Yes** — proven by code (no validation block) and by existing tests: `test_data_integrity.py` posts partial payloads → `ok:true` (lines 27–74); 3B.11 recorded a no-session create probe (id 11) |
| P4 | Direct HTTP `POST /api/final-submit` (no browser) | none | as P2 | **Yes** — `test_data_integrity.py:151-155` **"legacy final-submit (no data) ok"** + "sets submitted": an empty payload flips a record to submitted |
| P5 | Legacy form `POST /submit` (`form.html:24`, `app.py:570-592`) | In-browser blocked (`form.js:485` preventDefault) | b_form uniqueness only; creates `submitted=True` from raw columns | **Yes** — reachable by direct POST or JS-disabled client; no validation |
| P6 | Login auto-create (`app.py:661-669`) | n/a | requires name/class/section/roll only | By design creates incomplete rows (so "record completeness" can only be enforced at save/submit time, never at create) |
| P7 | `POST /api/upload-file` (`app.py:547-567`) | none | exists/filename checks only; `setattr(student, field_name, …)` with **unvalidated `field_name`** (`:565`) | **Yes** — can write a filename string into any column-named field (integrity observation, out of the 38) |
| P8 | Bot flow (`femis-web/job_api.py`) | n/a | reads `Student` for version token (`job_api.py:256-276`); writes **`BotJob` only** | Bot's student-data writes go through P1/P2 (same server, same gaps) |
| P9 | lock/unlock, register/setup-teacher (`app.py:714-789`) | n/a | writes flags/teacher rows only | Not student-field data |

**Conclusion:** every one of the 38 requirements is bypassable by a direct request (P3/P4/P5),
and requirements on tabs 1–6 are additionally skippable through the ordinary UI (P2).

---

## 4. Rule matrix (investigation C)

Legend for statuses: **PASS — server enforced** (none qualify), **PARTIAL — UI/JS only**,
**MISSING**, **CONDITIONAL — semantics need confirmation**, **FORMAT/RANGE — server validation
missing**, **NOT APPLICABLE**, **AMBIGUOUS — do not implement yet**.
`app.py:470-544` = no server rule exists for any row unless stated.

| ID | Requirement | Field(s) | Condition | Current UI enforcement | Current JS enforcement | Current server enforcement | Direct-request bypass? | Status | Evidence |
| -- | ----------- | -------- | --------- | ---------------------- | ---------------------- | -------------------------- | ---------------------- | ------ | -------- |
| R1 | Sector address → sector required | `sector_id` | `address_type='Sector'` | control present, **no** `required` | **none** — not in `mandatoryByTab[0]`, no conditional entry | none | Yes (nothing enforces anywhere) | **MISSING** | `form.js:551` (absent), `form.js:609-623` (absent), 3B.11 gap 1; data currently OK (id6/id8 filled) |
| R2 | Sector address → sub-sector required | `sub_sector_id` | `address_type='Sector'` | control present, **no** `required` | **none** (3B.13 only fixed *re-render*, not requirement) | none | Yes (nothing enforces anywhere) | **MISSING** | same as R1 |
| R3 | Orphan type required | `orphan_type` | `is_orphan='1'` (Yes) | select present, not `required` | `conditionalRequired` `form.js:610` | none | Yes | **PARTIAL — UI/JS only** | `form.js:610`, trigger values `['1']` verified (`form.html` radios `1`=Yes/`0`=No) |
| R4 | Orphan=Yes incompatible with both parents alive | `is_orphan` × `is_father_alive` × `is_mother_alive` | orphan=`1` AND father=`1` AND mother=`1` | n/a | inline guard `form.js:646-654` | none | Yes | **PARTIAL — UI/JS only** | `form.js:646-654`; caveat §5-4 (legacy `'Yes'` breaks re-render) |
| R5 | Guardian name required where applicable | `guardian_name` | applicability **undefined** (code: always) | `required` ✓ | `mandatoryByTab[1]` `form.js:557` | none | Yes | **PARTIAL — UI/JS only** (§7-A1) | `form.js:557`, `form.html` required tag |
| R6 | Guardian CNIC required where applicable | `guardian_cnic` | same | `required` ✓ | `form.js:557` | none | Yes | **PARTIAL — UI/JS only** (§7-A1) | as R5 |
| R7 | Guardian relation required where applicable | `guardian_relation` | same | `required` ✓ | `form.js:557` | none | Yes | **PARTIAL — UI/JS only** (§7-A1) | as R5 |
| R8 | Guardian WhatsApp/contact required where applicable | `guardian_contact` | same | `required` ✓ | `form.js:558` | none | Yes | **PARTIAL — UI/JS only** (§7-A1) | as R5 |
| R9 | Guardian profession required where applicable | `guardian_profession` | same | `required` ✓ | `form.js:558` | none | Yes | **PARTIAL — UI/JS only** (§7-A1) | as R5 |
| R10 | Guardian income required where applicable | `guardian_income` | same | `required` ✓ | `form.js:558` | none | Yes | **PARTIAL — UI/JS only** (§7-A1) | as R5 |
| R11 | Mother income optional when housewife | `mother_monthly_income` | `mother_profession='Housewife'` → **not** required | no `required` attr | inline rule `form.js:639-644` (requires only when profession non-empty **and** `!== 'Housewife'`) | none | Yes | **PARTIAL — UI/JS only** | `form.js:640-644`; exact-string comparison (§5-6) |
| R12 | Mother income required otherwise | `mother_monthly_income` | profession set and `≠ 'Housewife'` | no `required` attr | same inline rule (JS is the **only** layer) | none | Yes | **PARTIAL — UI/JS only** | `form.js:642` |
| R13 | Date of admission `MM/DD/YYYY` | `date_of_admission` | always | text input + `pattern="\d{2}/\d{2}/\d{4}"` + placeholder (`form.html:677`) — **native-inert** | presence only (`form.js:561`); **no format check** (3B.11 gap 9 corrected) | none | Yes | **FORMAT/RANGE — server validation missing** | `form.html:677`, `form.js:561`; canonical rows store **ISO** (`2023-04-24`, `2024-01-15`) → §7-A3 |
| R14 | Class admitted 6–10 for grades 6–10 | `class_admitted_id` × `class_id` | `class_id` value ≥ 6 | radios **rebuilt to 6..10** by `form.js:440-441` (`lo=6,hi=10`) | presence (`form.js:561`); range guaranteed only by option construction | none | Yes — crafted POST can store out-of-range | **FORMAT/RANGE — server validation missing** | `form.js:431-467` |
| R15 | Class admitted 1–5 for grades 1–5 | `class_admitted_id` × `class_id` | `class_id` value ≤ 5 | radios rebuilt to 1..5 (`form.js:440-441`) | presence only | none | Yes | **FORMAT/RANGE — server validation missing** | same as R14 |
| R16 | Primary Education Completion NOT mandatory | `primary_education_completion_years` | — | **no** `required` | **not** in `mandatoryByTab`, no conditional rule | none (nothing to enforce) | n/a | **NOT APPLICABLE** | absence verified in HTML/JS (3B.11 item 11); Ayat id6 correctly stores `5` as optional data |
| R17 | Meal program mandatory | `school_meal_program_availing` | always | control present, **no** `required` attr (JS-only layer) | `mandatoryByTab[2]` `form.js:563` | none | Yes | **PARTIAL — UI/JS only** | `form.js:563` |
| R18 | Transport facility mandatory | `transport_facility` (→ col `transport`) | always | `required` ✓ | `form.js:564` | none | Yes | **PARTIAL — UI/JS only** | `form.js:564`, `FORM_FIELD_MAP` `app.py:425` |
| R19 | Scholarship mandatory | `scholarship` | always | `required` ✓ | `form.js:564` | none | Yes | **PARTIAL — UI/JS only** | `form.js:564` |
| R20 | Co-curricular activity mandatory | `cocurricular_activities` | always | `required` ✓ | `form.js:564` | none | Yes | **PARTIAL — UI/JS only** | `form.js:564` |
| R21 | Qualification required where FEMIS says so | `father_qualification` (enforced); `mother_qualification`, `guardian_qualification` (not) | "where applicable" **undefined** | **none of the three** carry `required` (JS-only layer) | father in `mandatoryByTab[1]` (`form.js:554`); mother/guardian absent | none | Yes | **PARTIAL — UI/JS only** (scope beyond father = §7-A2) | `form.js:554`; HTML check: `father_qualification`/`mother_qualification`/`guardian_qualification` all `required`-absent |
| R22 | Income per month required where applicable | `father_monthly_income`, `guardian_income`, `mother_monthly_income` | father/guardian always; mother per R11/R12 | `guardian_income` `required` ✓; `father_monthly_income` and `mother_monthly_income` **no** `required` | father `form.js:554`, guardian `:558` (absolute lists); mother inline rule only (`:639-644`) | none | Yes | **PARTIAL — UI/JS only** | HTML: guardian ✓ / father ✗ / mother ✗ (verified); JS covers all three (father+guardian absolute, mother conditional) |
| R23 | Bus field labeled "Institution Bus" | `transport_facility` option values/labels | — | values **`Institution Bus` / `Private` / `None`**, no plain `Bus` | `bus_route` trigger tolerates legacy `Bus` alongside `Institution Bus` (`form.js:620`) | n/a (label/value rename, not a validation rule) | n/a | **NOT APPLICABLE** | HTML radio values verified; DB stores `'Institution Bus'` (id6); no legacy `'Bus'` rows in canonical data. **Label-only vs data-contract:** rename already applied at **value level too** (data contract), with a JS-side legacy tolerance |
| R24 | IDP status mandatory where applicable | `idp_status_id` (radio group from opts) | `is_refugee='1'` | `is_refugee` `required` ✓; `idp_status_id` not `required` | `is_refugee` in `mandatoryByTab[4]` (`form.js:567`) **+** conditional `idp_status_id ← is_refugee=['1']` (`:613`) | none | Yes | **PARTIAL — UI/JS only** | `form.js:567,613` |
| R25 | Refugee registration mandatory when refugee/IDP = Yes | `is_registered_refugee`, `refugee_card_number` | `is_refugee='1'`; card when `is_registered_refugee='1'` | `is_refugee` `required` ✓ | conditionals `form.js:614-615` (chain) | none | Yes | **PARTIAL — UI/JS only** | `form.js:614-615`; `refugee_card_number → refugee_card` (`app.py:426`) |
| R26 | Major disability mandatory | `has_major_disability` | always | `required` ✓ | `mandatoryByTab[5]` `form.js:569` | none | Yes | **PARTIAL — UI/JS only** | `form.js:569` |
| R27 | Mental disability status mandatory | `has_mental_disability` | always | `required` ✓ | `form.js:569` | none | Yes | **PARTIAL — UI/JS only** | `form.js:569` |
| R28 | Visually fit mandatory | `visually_fit` | always | `required` ✓ | `form.js:569` | none | Yes | **PARTIAL — UI/JS only** | `form.js:569` |
| R29 | Wears glasses mandatory | `uses_glasses` | always | `required` ✓ | `form.js:569` | none | Yes | **PARTIAL — UI/JS only** | `form.js:569` |
| R30 | Glasses prescription when visually fit = No | `glass_prescription` | `visually_fit='0'` | `required` **unconditionally** (native-inert; diverges from condition) | conditional `form.js:618` (`values:['0']`) | none | Yes | **PARTIAL — UI/JS only** | `form.js:618` |
| R31 | Hearing difficulty mandatory | `has_hearing_difficulties` | always | `required` ✓ | `form.js:570` | none | Yes | **PARTIAL — UI/JS only** | `form.js:570` |
| R32 | Hearing aid when hearing difficulty = Yes | `uses_hearing_aid` | `has_hearing_difficulties='1'` | `required` **unconditionally** (native-inert; diverges) | conditional `form.js:619` | none | Yes | **PARTIAL — UI/JS only** | `form.js:619` |
| R33 | Difficulty listening mandatory | `difficulty_listening` | always | `required` ✓ | `form.js:570` | none | Yes | **PARTIAL — UI/JS only** | `form.js:570` |
| R34 | Difficulty walking mandatory | `difficulty_walking` | always | `required` ✓ | `form.js:571` | none | Yes | **PARTIAL — UI/JS only** | `form.js:571` |
| R35 | Crutches/walker when walking-difficulty = Yes | `uses_crutches_walker` | requirement: `difficulty_walking='1'`; **code: unconditional** | `required` ✓ (unconditional) | `mandatoryByTab[5]` absolute list `form.js:571` — **no conditional entry** | none | Yes | **CONDITIONAL — semantics need confirmation** | requirement text vs `form.js:571`; data pairs consistent (`difficulty_walking='0'`, `uses_crutches_walker='0'` for id6/id8) → §7-A4 |
| R36 | Digital device access mandatory | `digital_device_at_home` | always | `required` ✓ | `mandatoryByTab[6]` `form.js:575` | none | Yes | **PARTIAL — UI/JS only** | `form.js:575` |
| R37 | Device type when access = Yes | `digital_device_type[]` | `digital_device_at_home='1'` | checkboxes present, no `required` | conditional `form.js:621` | none | Yes | **PARTIAL — UI/JS only** | `form.js:621`; `→ digital_device_type` (`app.py:423`) |
| R38 | Internet access mandatory | `internet_at_home` | always | `required` ✓ | `form.js:575` | none | Yes | **PARTIAL — UI/JS only** | `form.js:575` |

### Supplementary cross-cutting rows

| ID | Topic | Finding | Status |
|----|-------|---------|--------|
| X1 | Server-side enforcement of *any* mandatory rule | `api_save_tab`/`api_final_submit`/`submit` contain **zero** required/conditional/format checks (`app.py:470-544, 570-592`); only B-Form uniqueness + partial authz | **MISSING** (3B.11 gap X) |
| X2 | Final-submit validates only the active tab | `validateTab(currentTab)` at `form.js:668`; tab navigation unrestricted (`form.js:510-520`); final-submit payload carries **only tab-7 fields** (`form.js:671, 705-708`) — server never even receives tabs 1–6 in that request | **PARTIAL** — JS layer incomplete by construction (P2) |
| X3 | HTML `required`/`pattern` inertness | 56 `required` tags; 0 `checkValidity`/`reportValidity`; Save is `type="button"`; `submit` prevented | **PARTIAL** — native layer does not enforce on the save path |
| X4 | B-Form required/format | HTML `required` **unconditional** (even when `is_bform_available='0'`); JS: mask only (`form.js:24-34`), not in `mandatoryByTab`; server: uniqueness only — emptiness/format never checked | **CONDITIONAL — semantics need confirmation** (§7-A5) |
| X5 | HTML-only `required` (no JS counterpart) | `b_form`, `house`, `street`, `shift` carry `required` but are absent from `mandatoryByTab` (3B.11 gap Y) | **PARTIAL** — divergent layers, neither effective |
| X6 | `upload-file` arbitrary field write | `setattr(student, field_name, safe_name)` unvalidated `field_name` (`app.py:565`) | observation (out of scope of the 38) |
| X7 | Data already violates R13 | canonical `date_of_admission` = ISO strings (id6, id8) | input to §7-A3 |

**Tally:** MISSING 2 (+X1) · PARTIAL — UI/JS only 30 (+X2, X3, X5) · FORMAT/RANGE 3 ·
CONDITIONAL 1 (+X4) · NOT APPLICABLE 2 · PASS — server enforced: **0**.

---

## 5. Cross-field semantics (investigation D)

1. **Radio value domain in the current form:** every Yes/No trigger radio uses
   `value="1"` = Yes, `value="0"` = No (verified for all 21 trigger fields extracted from
   `form.html`: is_orphan, is_father/mother_alive, is_refugee, is_registered_refugee,
   has_major/major-mental disability, visually_fit, uses_glasses, hearing, aid,
   difficulty_listening/walking, crutches, digital, internet, meal, scholarship, cocurricular).
   `transport_facility` domain = `Institution Bus | Private | None`.
2. **Trigger evaluation is UI-state-only:** all 13 `conditionalRequired` rules and both
   inline guards read `input[name=trigger]:checked` (`form.js:625, 640-651`) — they never
   read DB state. A NULL radio (never answered) reads as *no trigger* → conditional field
   **not** demanded, and the absolute field itself is demanded (unless its own list entry
   is missing).
3. **NULL ≠ '0':** canonical DB shows NULL for untouched rows (3, 4, 9, 10) and for the
   un-asked conditional fields; explicit answers are `'1'`/`'0'`. Unchecked radios are
   omitted from the payload (`form.js:681-682`) so **NULL is preserved on save, but once
   set a radio can never be re-returned to NULL** — the known **F4** issue. Any future
   server validator must keep NULL (unanswered) distinct from `'0'` (No) and must not
   default NULL → No.
4. **Legacy value drift — `'Yes'` exists in canonical data:** id 8 stores
   `is_father_alive='Yes'`, `is_mother_alive='Yes'` (label strings, not `'1'`). Such rows
   render as **unchecked** (no radio has `value="Yes"`), so the R4 guard (`form.js:646-654`)
   and any conditional keyed on `'1'` will not see them as answered. **Do not silently
   normalize** `'Yes'` → `'1'` without an explicit data decision (§7-A8).
5. **Literal `'None'` placeholders:** id6/id8 store `achievement_details='None'` and
   `scholarship_details='None'` as **strings** (evidence: 3B.11 §6). Whether a server-side
   conditional check treats `'None'` as filled is undefined (§7-A6). Separately,
   `transport='None'` is a *legitimate option value* (no transport) — the two "None"
   semantics must not be conflated.
6. **`Housewife` comparison:** R11/R12 use exact string equality against the profession
   option value `'Housewife'` (`form.js:642`); a `mother_profession_other='Other'` path or
   case/whitespace drift would change semantics — server mirror must compare the same
   authoritative option value.
7. **Chain conditionals:** R25 is two-level (`is_refugee='1'` → `is_registered_refugee`
   required; `is_registered_refugee='1'` → `refugee_card_number` required,
   `form.js:614-615`). `bus_route` trigger accepts `['Bus', 'Institution Bus']` —
   `'Bus'` is legacy tolerance only; **no canonical row contains legacy `Bus`**.
8. **Date semantics:** `date_of_birth` = `type="date"` (stores ISO from the browser);
   `date_of_admission` = free text with native pattern; canonical rows are ISO — three
   different date representations coexist (§7-A3).

---

## 6. Existing tests — what they prove and do not prove (investigation E)

| Suite (exact command) | Result | Proves | Does **not** prove |
|---|---|---|---|
| `python test_mandatory_field_reconciliation.py` | **57/57** | **Static source facts**: which rules exist/are absent in `form.html`/`form.js`/`app.py` text; locks current state (its own GAP report = 4 discrepancies: items 1, 9, X, Y — with item 9's "no pattern" claim corrected by §1) | Any runtime behavior; that saves are actually blocked; server behavior; DB state; bypass |
| `python test_data_integrity.py` | **24/24** | API round-trips; **`legacy final-submit (no data) ok` + `sets submitted`** — live proof that P4 performs no validation; save-tab accepts partial payloads | That rejection *should not* happen (characterization, not assertion of absence) |
| `python test_persistence_roundtrip.py` | **29/29** | Save → read fidelity through both APIs; id/created_at preserved; no unexpected error field | Validation of any kind |
| `python smoke_test.py` | **14/14** | save-tab 200/ok, spot persistence (`sub_sector_id`, `same_address`), all 122 `field_mapping` labels exist in the portal | Validation |
| `python test_submission_status.py` | **12/12** | Bot Finish-click → `submit_failed`/success classification semantics | Form-field validation |
| `python test_bot_job_schema.py` / `test_bot_job_api.py` / `test_bot_job_api_isolation.py` / `test_bot_job_bot_integration.py` | 62 / 124 / 13 / 54 | Job schema, auth (tokens), version tokens, claim/lease/idempotency, bot-runner integration — **253 checks** | Student mandatory-field validation (job API never writes student columns, `job_api.py`) |
| `python test_students_null_created_at.py` / `test_created_at_creation_paths.py` / `test_created_at_not_null_integrity.py` | 11 / 11 / 26 | `created_at` NOT NULL invariants across create paths (**48 checks**) | Field-level validation |
| `python smoke_test_bot.py` | **3/3** | Bot date normalizer units | Format validation of the portal |
| `python test_prefill_rerender.py` | **30/30** | F1/F2/F3/F5 re-render + preservation + intentional-clear | Mandatory rules |

**Gap:** no test asserts that `save-tab`/`final-submit` **reject** incomplete payloads —
because they do not. Per phase rules, no test was rewritten.

---

## 7. Ambiguous requirements — decisions needed before implementation

*(Nothing below may be invented; each needs an authoritative ruling.)*

| ID | Ambiguity | Why it blocks | Anchor |
|---|---|---|---|
| **A1** | Guardian fields "where applicable" — is a guardian **always** required, or only when a parent is missing/orphan? | Code enforces **unconditionally**; id6/id8 have both parents alive and all 6 guardian columns NULL → they cannot pass current JS validation; FEMIS source-of-truth ruling still open | 3B.11 §6 + §10.5; `form.js:557-558` |
| **A2** | R21/R22 scope: are `mother_qualification` / `guardian_qualification` (and any income variant) mandatory under FEMIS? | Only father's qualification + guardian income are enforced; mother's qualification is not required anywhere | `form.js:554-558` |
| **A3** | R13 format: canonical rows store ISO `date_of_admission` (`2023-04-24`) while the requirement is `MM/DD/YYYY` — grandfather, migrate, or reject? | A server format check would fail existing valid records on day one | DB id6/id8; `form.html:677` |
| **A4** | R35: should `uses_crutches_walker` be conditional on `difficulty_walking='1'` (requirement) or unconditional (current `mandatoryByTab[5]`)? | Two different rules; implementing the wrong one either blocks valid records or lets required ones slide | requirement text vs `form.js:571` |
| **A5** | X4: B-Form — required always, or only when `is_bform_available='1'`? Any format rule (13 digits / mask shape)? | HTML says always; JS says never; server never checks | `form.html` required, `form.js:24-34` |
| **A6** | Do literal `'None'` placeholder strings satisfy conditional-detail requirements (`scholarship_details`, `achievement_details`)? | Server mirror must decide "filled" semantics; string `'None'` ≠ NULL ≠ option value `None` | 3B.11 §6; §5-5 |
| **A7** | Enforcement unit: validate **payload keys only** per request, or the **whole assembled record** at each save/final-submit? | `save-tab`/`final-submit` payloads carry **one tab's fields** (`form.js:671`); whole-record validation must read the DB and define partial-save behavior (e.g., create-on-tab-1 ships 13 keys only) | `form.js:671-708`, `app.py:477-516` |
| **A8** | Legacy `'Yes'` values (id8 `is_father_alive`/`is_mother_alive`) — normalize to `'1'`, map during read, or treat as distinct? | Affects R4 guard and every `'1'`-keyed conditional; must not be silently converted (F4-adjacent) | DB id8; §5-4 |

**Safe-to-implement without further decisions** (proven: field + condition + value semantics + enforcement path identified):
server-side mirrors of (a) the unconditional `mandatoryByTab` lists per tab,
(b) the 13 `conditionalRequired` entries with verified `1`/`0`/option-value triggers,
(c) the two inline guards (orphan conflict; mother-income `Housewife`) —
each scoped per A7's ruling, plus the R14/R15 range check (independent of A3).

---

## 8. Regression / integrity gate (investigation G)

Exact commands, run from the repository root, fresh processes, **files unmodified**:

```
python test_bot_job_schema.py
python test_bot_job_api.py
python test_data_integrity.py
python test_submission_status.py
python test_bot_job_api_isolation.py
python smoke_test.py
python smoke_test_bot.py
python test_bot_job_bot_integration.py
python test_students_null_created_at.py
python test_created_at_creation_paths.py
python test_created_at_not_null_integrity.py
python test_persistence_roundtrip.py
python test_mandatory_field_reconciliation.py
python test_prefill_rerender.py
```

| | Value |
|---|---|
| Results | **470/470 pass, 0 fail, all `exit=0`** (62+124+24+12+13+14+3+54+11+11+26+29 = **440 baseline** + 57 reconciliation (in baseline) + 30 prefill) |
| Failures | **none** — no pre-existing or phase-caused failure to classify |
| HEAD | `a35f3c0` (unchanged; nothing staged, nothing committed) |
| `git status` | **clean** (only `docs/phase3b14-mandatory-validation-reconciliation.md` created — untracked, per scope) |
| DB before/after | phase-start snapshot vs end: **9/9** — 6 canonical student rows byte-identical, Ayat `updated_at` unchanged, bot_jobs 0, teachers 3, integrity ok, no probe leftovers; file sha differs only by test probe insert/delete churn |

---

## 9. Files created / modified

**Created (1):** `docs/phase3b14-mandatory-validation-reconciliation.md` (this file).
**Modified:** **none** — no `app.py`, `form.js`, HTML, model, schema, DB data, or test changes;
Ayat untouched; auth untouched; F4 untouched; nothing committed.
Temporary read-only analysis scripts lived in `%LOCALAPPDATA%\Temp\opencode\` (outside the
repo) and were removed before STOP.

---

## 10. STOP report appendix — recommended grouping for the next phase (not started)

1. **G1 — server mirror of unconditional per-tab required lists** (payload/tab-scoped, per A7): targets all PARTIAL rows → server-enforced.
2. **G2 — server mirror of the 13 conditional rules + 2 inline guards** (trigger values already verified `1`/`0`): targets R3, R4, R11/R12, R24, R25, R30, R32, R37 (+ scholarship/cocurricular/bus_route/emergency/disability-mental conditionals).
3. **G3 — MISSING rules R1/R2** (conditional `sector_id`/`sub_sector_id` ← `address_type='Sector'`) — implementable: fields, condition, and values verified; recommend adding in **both** JS and server.
4. **G4 — FORMAT/RANGE (R13–R15)**: class-admitted range server check can proceed now; date-format check **blocked by A3**.
5. **G5 — decision-gated**: A1–A8 (guardian applicability, qualification scope, legacy dates, crutches conditional, B-Form conditionality, `'None'` semantics, enforcement unit, legacy `'Yes'`) — requires admin rulings before any code.
6. **X2 fix** (final-submit validating only tab 7) should be designed together with G1/G2 — it is the difference between "the JS layer blocks" and "the record can never be submitted incomplete".
7. F4 remains separate and untouched.

**STOP. Awaiting approval before any implementation.**
