# Phase 3B.1 — Portal → DB → Bot Data-Contract Audit

**Mode:** READ-ONLY (evidence + documentation only)  
**Date:** 2026-09-24  
**Branch:** `main` (HEAD at audit start: `6871f81`)  
**Scope:** Trace every portal field identity through `form.js` → API payload → `FORM_FIELD_MAP` → SQLite `students` → `WebFormHandler` → `field_mapping.yaml` / `form_filler` → FEMIS.  
**Out of scope (hard rules):** no edits to `form.html`, `form.js`, `app.py`, `webform_handler.py`, `form_filler.py`, `main.py`, `field_mapping.yaml`, DB schema/data (except temporary synthetic row create/delete), auth, hosting, bot selectors; no `bot_jobs`; no live FEMIS submission; no commits.

**Evidence tools:**  
- Synthetic contract test: `C:\Users\faiza\AppData\Local\Temp\opencode\phase3b1_synthetic_trace.py` (temp artifact; creates student id 11, asserts 74 checks, deletes row).  
- Result: **74/74 PASS**.  
- Prior suites (unchanged): `test_data_integrity.py` 24/24, `test_submission_status.py` 12/12, `smoke_test.py` 14/14, `smoke_test_bot.py` 3/3 → **53/53**.

---

## 1. Executive summary

| Boundary | Verdict | Notes |
|---|---|---|
| Portal → DB (`FORM_FIELD_MAP`) | **END_TO_END_VERIFIED** for mapped renames; identity for all others | Synthetic tab saves land on correct columns; `temp_id` dropped; re-save of one tab does **not** blank other tabs (partial update only). |
| DB → bot (`WebFormHandler`) | **END_TO_END_VERIFIED** | `read_by_id` returns full row minus `id`/`created_at`; injects `transport_facility` from `transport` without removing raw `transport`. |
| Bot → portal name (aliases) | **END_TO_END_VERIFIED** | `PORTAL_NAME_ALIASES` resolves 10 DB/yaml keys to portal `input[name]` values. |
| Bot → FEMIS (`field_mapping.yaml` `source_field`) | **BOT_TO_FEMIS_VERIFIED** (mapping identity) + **known working** (bot suite) | `source_field` keys align with bot-row keys; live fill not re-run this phase. |
| Final submit / status flags | **PORTAL_TO_DB_VERIFIED** | `/api/final-submit` sets `submitted=True`, never `locked`; incomplete payload still sets `submitted=True` (no server-side required-field check). |
| Bot result status | **BOT_TO_FEMIS_VERIFIED** | `classify_student_result` / `is_submission_success`: fill-only → `fill_success`, never `success`. |
| Tab 7 multi-value | **END_TO_END_VERIFIED** | `digital_device_type` / `disability_types` comma-joined in form.js, stored as CSV, read as CSV, alias to `[]` names. |
| Deployment schema drift | **BROKEN (deployment only)** | Historical `sqlite3.OperationalError: no such column: students.address` on PythonAnywhere remains a **deployed-instance schema** issue, not a local code path. |

No **BROKEN** in-code contracts found. One **PORTAL_ONLY** field (`guardian_qualification`) and one **FEMIS_ONLY** widget (`Temporary Student ID`) remain intentional.

---

## 2. Architecture diagram (current data contract)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ STUDENT PORTAL (femis-web)                                              │
│                                                                         │
│  form.html  ──renders──►  input[name=X] / name[]                        │
│       │                                                                │
│  form.js  collect active tab                                           │
│       │  • radio → last checked value                                  │
│       │  • checkbox name[] → checked values .join(",")                 │
│       │  • hidden #admissionForm inputs always included                │
│       │  • endpoint: tab<7 → POST /api/save-tab                        │
│       │                   tab==7 → POST /api/final-submit              │
│       ▼                                                                │
│  JSON payload { tab?, student_id, data: { formKey: value } }           │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTP (session cookie auth)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ API LAYER (app.py)                                                     │
│  _map_form_data(data)                                                  │
│    FORM_FIELD_MAP.get(formKey, formKey) → dbCol if hasattr(Student)    │
│    unmapped / None / non-model keys DROPPED                            │
│  /api/save-tab: partial setattr on existing row (or create on tab1)    │
│  /api/final-submit: partial setattr + student.submitted = True         │
│  /api/lock|unlock (teacher): student.locked = True/False               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ SQLAlchemy (Flask)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ SQLite  femis-web/instance/femis.db   table students (canonical, 140c) │
│  columns store DB names (e.g. transport, refugee_card,                 │
│  digital_device_type CSV, disability_types CSV,                        │
│  present_address_other, achievement_details, …)                        │
│  flags: submitted BOOLEAN, locked BOOLEAN                              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ sqlite3 SELECT * (direct SQL)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ BOT DATA SOURCE (webform_handler.py)                                   │
│  read_by_id / read_all / read_unprocessed                              │
│    drop id, created_at, processed                                       │
│    setdefault transport_facility ← transport  (keeps transport raw)     │
│    → dict keys = DB column names (yaml source_field space)              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ data.get(source_field)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ FORM FILLER (form_filler.py) + field_mapping.yaml                      │
│  source_field → PORTAL_NAME_ALIASES.get(source, source) → portal name  │
│  conditionals: transport_facility/bus_route, disability_certificate,   │
│                digital_device_at_home → device_type[], guardian_* …    │
│  finish: is_submission_success(finish_clicked, indicator)              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ Playwright (selectors / FEMIS DOM)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ LIVE FEMIS (femis.fde.gov.pk)                                          │
│  official Finish action → indicator → status classification            │
│  report: main.classify_student_result → success | fill_success |       │
│          submit_failed | error                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Separation boundaries (what future API must NOT expose):** Flask internals, SQLAlchemy session, Selenium/Playwright page state, FEMIS credentials (`FEMIS_USERNAME`/`FEMIS_PASSWORD`/`GEMINI_API_KEY`), CAPTCHA flows, DOM selectors, YAML internal structure, DB file path / PRAGMA / column DDL details.

---

## 3. Synthetic contract test (Portal → DB → bot read)

Script: `phase3b1_synthetic_trace.py` (temp). Flow:

1. Flask `test_client` + app context.  
2. `POST /api/save-tab` tab=1 create with distinctive values (text, radio, select, multi-value, conditional, file-representation fields, `temp_id` decoy).  
3. Sequential `save-tab` tabs 3, 5, 6.  
4. `POST /api/final-submit` tab=7 data.  
5. Assert `Student` attributes, direct SQLite row, `WebFormHandler.read_by_id`, alias resolution.  
6. Re-save tab=1 with **minimal** payload → assert other-tab fields **not** blanked.  
7. Second identical `final-submit` → idempotent `ok` + `submitted` still True.  
8. **Delete** student id 11 and assert gone.

**Outcome:** 74/74 PASS (see §12 checklist).

### 3.1 Distinctive values (identity sample)

| Domain | Portal form key | Payload | DB column | Bot dict key | yaml `source_field` | Portal name after alias |
|---|---|---|---|---|---|---|
| Text | `name` | `SYNTHETIC AUDIT TRACE` | `name` | `name` | identity | `name` |
| Text | `address` | Trace Permanent… | `address` | `address` | identity | `address` |
| Text | `present_address` | Trace Temporary… | **`present_address_other`** | `present_address_other` | identity (if mapped) | `present_address` (form.js reverse) |
| Radio | `same_as_permanent_address` | `Yes` | **`same_address`** | `same_address` | identity | `same_as_permanent_address` |
| Radio+cond | `transport_facility` | `Institution Bus` | **`transport`** | `transport` + alias `transport_facility` | `transport_facility` | `transport_facility` |
| Text+cond | `bus_route` | `Route-99` | `bus_route` | `bus_route` | `bus_route` | `bus_route` |
| Radio+cond | `is_registered_refugee` | `Yes` | `is_registered_refugee` | same | same | same |
| Text | `refugee_card_number` | `RC-TRACE-99001` | **`refugee_card`** | `refugee_card` | `refugee_card` | **`refugee_card_number`** |
| Multi[] | `disability_types` | `Visual,Hearing` | **`disability_types`** (CSV) | same | `disability_types` | **`disability_types[]`** |
| Text | `disability_certificate` | `CERT-TRACE-66` | same | same | `disability_certificate` | identity |
| Multi[] | `digital_device_type` | `Smartphone,Laptop` | **`digital_device_type`** (CSV) | same | `digital_device_type` | **`digital_device_type[]`** |
| Radio | `digital_device_at_home` | `Yes` | same | same | `digital_device_at_home` | identity |
| Radio | `internet_at_home` | `No` | same | same | `internet_at_home` | identity |
| Text | `other_medical_condition` | TraceOtherCondition | **`other_conditions`** | `other_conditions` | identity | **`other_medical_condition`** |
| Text | `cocurricular_details` | Trace co-curricular… | **`achievement_details`** | `achievement_details` | identity | **`cocurricular_details`** |
| Text | `result_percentage` | `87.5` | **`last_class_result`** | `last_class_result` | identity | **`result_percentage`** |
| Text | `siblings_same_institution` | `Yes` | **`siblings_same`** | `siblings_same` | identity | **`siblings_same_institution`** |
| Decoy | `temp_id` | should_be_dropped | **dropped** (`None` in map) | — | — | — |

**Multi-value contract (A+B+C):**  
Portal checks A,B,C → form.js `arrayChecks[name]` → `"A,B,C"` → API → DB CSV `"A,B,C"` → bot row `"A,B,C"` → alias expands display name to `name[]` for FEMIS multi-select. Verified for `disability_types` and `digital_device_type` with 2 values; same join path for N values.

**No-blank guarantee:** partial `setattr` only; keys absent from payload are untouched. Re-saving tab 1 without multi-value keys left `disability_types`, `digital_device_type`, `transport`, `refugee_card`, Tab 7 fields intact.

---

## 4. Summary tables

### 4.1 Portal → DB (`FORM_FIELD_MAP` + identity)

| Portal form key | DB column | Status |
|---|---|---|
| `temp_id` | *(dropped)* | END_TO_END_VERIFIED |
| `same_as_permanent_address` | `same_address` | END_TO_END_VERIFIED |
| `last_other_institution` | `last_institution_other` | END_TO_END_VERIFIED |
| `siblings_same_institution` | `siblings_same` | END_TO_END_VERIFIED |
| `other_medical_condition` | `other_conditions` | END_TO_END_VERIFIED |
| `cocurricular_details` | `achievement_details` | END_TO_END_VERIFIED |
| `result_percentage` | `last_class_result` | END_TO_END_VERIFIED |
| `digital_device_type[]` / `digital_device_type` | `digital_device_type` | END_TO_END_VERIFIED (CSV) |
| `present_address` | `present_address_other` | END_TO_END_VERIFIED |
| `transport_facility` | `transport` | END_TO_END_VERIFIED (**do not rename DB col**) |
| `refugee_card_number` | `refugee_card` | END_TO_END_VERIFIED (**do not rename**) |
| `disability_types[]` / `disability_types` | `disability_types` | END_TO_END_VERIFIED (CSV) |
| All other model keys | same name | PORTAL_TO_DB_VERIFIED (pass-through `_map_form_data`) |
| Unknown / non-model keys | dropped | END_TO_END_VERIFIED (silent drop by design) |

### 4.2 DB → bot (`WebFormHandler`)

| Concern | Status |
|---|---|
| `SELECT * FROM students WHERE id=?` | END_TO_END_VERIFIED |
| drop `id`, `created_at` | END_TO_END_VERIFIED |
| drop `processed` (read_unprocessed only) | END_TO_END_VERIFIED (path reviewed) |
| inject `transport_facility` ← `transport` | END_TO_END_VERIFIED (raw `transport` kept) |
| row keys match yaml `source_field` space | END_TO_END_VERIFIED (spot-checked critical fields) |
| DB path resolution (`instance/femis.db` preferred) | END_TO_END_VERIFIED |

### 4.3 DB → bot → FEMIS (aliases + yaml)

| yaml `source_field` / bot key | `PORTAL_NAME_ALIASES` → portal name | Status |
|---|---|---|
| `transport_facility` | identity (no alias entry) | BOT_TO_FEMIS_VERIFIED |
| `bus_route` | identity | BOT_TO_FEMIS_VERIFIED |
| `refugee_card` | `refugee_card_number` | BOT_TO_FEMIS_VERIFIED |
| `digital_device_type` | `digital_device_type[]` | BOT_TO_FEMIS_VERIFIED |
| `disability_types` | `disability_types[]` | BOT_TO_FEMIS_VERIFIED |
| `other_conditions` | `other_medical_condition` | BOT_TO_FEMIS_VERIFIED |
| `achievement_details` | `cocurricular_details` | BOT_TO_FEMIS_VERIFIED |
| `last_class_result` | `result_percentage` | BOT_TO_FEMIS_VERIFIED |
| `last_institution_other` | `last_other_institution` | BOT_TO_FEMIS_VERIFIED |
| `siblings_same` | `siblings_same_institution` | BOT_TO_FEMIS_VERIFIED |
| `same_address` | `same_as_permanent_address` | BOT_TO_FEMIS_VERIFIED |
| `digital_device_at_home` / `internet_at_home` / `disability_certificate` | identity | BOT_TO_FEMIS_VERIFIED |

### 4.4 Tab 7 (Digital Access)

| Field | Portal | DB | Bot | Status |
|---|---|---|---|---|
| `digital_device_at_home` | radio Yes/No | same | same | END_TO_END_VERIFIED |
| `digital_device_type[]` | multi checkbox | CSV `digital_device_type` | CSV + alias `[]` | END_TO_END_VERIFIED |
| `internet_at_home` | radio Yes/No | same | same | END_TO_END_VERIFIED |
| Conditional show device list | `radioToggle(..., ["1"])` | n/a | filler sets `[]` when Yes | END_TO_END_VERIFIED (UI + filler) |

### 4.5 Transport / Refugee / Disability

| Feature | Portal → DB | DB → bot | Bot → FEMIS | Status |
|---|---|---|---|---|
| Transport choice | `transport_facility` → `transport` | + `transport_facility` alias | `source_field: transport_facility`, options Institution Bus/Private | END_TO_END_VERIFIED |
| Bus route | `bus_route` → `bus_route` | same | `source_field: bus_route`; portal shows when Institution Bus | END_TO_END_VERIFIED |
| Refugee card | `refugee_card_number` → `refugee_card` | same | alias → `refugee_card_number`; `is_registered_refugee` gates UI | END_TO_END_VERIFIED |
| Disability types | `disability_types` CSV | same | alias `disability_types[]` | END_TO_END_VERIFIED |
| Disability certificate | `disability_certificate` | same | `source_field` + shown when `has_major_disability=Yes` | END_TO_END_VERIFIED |

### 4.6 Multi-value fields

| Field | form.js collect | DB storage | Bot read | Status |
|---|---|---|---|---|
| `digital_device_type[]` | `.join(",")` | CSV string | CSV string | END_TO_END_VERIFIED |
| `disability_types[]` | `.join(",")` | CSV string | CSV string | END_TO_END_VERIFIED |
| Uncheck-all / later tab save | empty or omit | not blanked by unrelated tab | — | END_TO_END_VERIFIED (partial update) |

### 4.7 Final submit / flags

| Action | Writes | `submitted` | `locked` | Notes | Status |
|---|---|---|---|---|---|
| `/api/save-tab` | mapped columns only | unchanged | unchanged (blocks non-teacher if locked) | create on missing student_id | PORTAL_TO_DB_VERIFIED |
| `/api/final-submit` | mapped columns + **`submitted=True`** | **True** | unchanged | **no server-side completeness check**; empty `data` still sets submitted | PORTAL_TO_DB_VERIFIED |
| `/api/lock` (teacher) | `locked=True` | unchanged | True | 403 if not teacher | PORTAL_TO_DB_VERIFIED |
| `/api/unlock` (teacher) | `locked=False` | unchanged | False | | PORTAL_TO_DB_VERIFIED |
| Bot Finish semantics | n/a | n/a | n/a | `submitted`/`locked` ≠ FEMIS success | see §4.8 |

**Idempotency:** repeating final-submit with same body returns `ok` and leaves `submitted=True`; overwrite replaces only keys present in payload.

### 4.8 Bot success semantics (must not conflate)

| Condition | Status string | Source |
|---|---|---|
| Error during fill | `error` | `classify_student_result(..., error=)` |
| Fill only (submit not requested) | **`fill_success`** (never `success`) | `src/main.py` L37–38 |
| Finish requested, not detected | `submit_failed` | L39 |
| Finish requested + `is_submission_success` | `success` | L39 + `form_filler.is_submission_success` |
| Dry run | `dry_run` | `main.py` L173 |

`form_filler.is_submission_success(finish_clicked, indicator_detected)` requires **both**.  
Portal `students.submitted` is a **portal UI flag only** — it does **not** mean FEMIS accepted the form.

### 4.9 Known non-blocking classification

| Item | Status |
|---|---|
| `guardian_qualification` | **PORTAL_ONLY** (keep; no FEMIS counterpart) |
| FEMIS `Temporary Student ID` | **FEMIS_ONLY** (expected absent on portal) |
| `shift`, `transport_facility`, `disability_certificate` identity on FEMIS | **EXACT_IDENTITY** (3A.1.1) |
| PythonAnywhere `no such column: students.address` | **BROKEN (deployment-schema issue)** — not a local code/contract defect; local model + migrations add column via best-effort ALTER |
| `form_questions` vs live DOM empty-name widgets | **UNRESOLVED** (low; dynamic FEMIS widgets) |

---

## 5. Multi-value test detail (Section 5 of plan)

Synthetic used 2-value CSVs; join implementation is generic (`arrayChecks[n].join(",")`), so A+B+C → `"A,B,C"`:

1. Portal A+B+C checked → payload `"A,B,C"`.  
2. DB stores `"A,B,C"` (VARCHAR).  
3. Bot `read_by_id` returns `"A,B,C"`.  
4. Subsequent save of another tab **omitting** the multi key → CSV unchanged (asserted).  
5. Bot expands to portal name `field[]` for FEMIS multi-select controls.

---

## 6. Conditional wiring (portal UI ↔ bot source)

| Trigger (portal) | Reveals | Bot / yaml behavior |
|---|---|---|
| `transport_facility=Institution Bus` | `bus_route_group` | `bus_route` required in yaml; filler defaults transport if blank when bus_route set |
| `is_registered_refugee=Yes` | `refugee_card_group` | `refugee_card` source_field |
| `has_major_disability=Yes` | `disability_fields` (+ certificate) | `disability_certificate` source_field; types multi |
| `digital_device_at_home=Yes` | `device_type_group` | filler skips/types gated on Yes (`form_filler` L1638) |
| `scholarship=Yes` / `cocurricular_activities=Yes` | detail groups | `achievement_details` etc. |

Portal only **shows/hides**; API still accepts values if sent. Bot applies its own gates from `source_field` logic.

---

## 7. Write semantics (save vs final-submit)

1. **Per-tab Save & Next** (`/api/save-tab`): maps **only keys present in that tab’s active inputs** (plus hidden fields). Creates row on first save (`student_id=null`). Does not touch `submitted`/`locked`.  
2. **Tab switch without save**: `form.js` confirm discards unsaved changes (no API call).  
3. **Submit on last tab** (`/api/final-submit`): same map + `submitted=True`. Server does **not** validate mandatory-by-tab; incomplete data can still set `submitted=True`.  
4. **Teacher lock**: disables portal inputs client-side; API rejects non-teacher writes when `locked`.  
5. **Overwrite**: later saves replace mapped columns for keys included; omitted keys persist.  
6. **Idempotent final-submit**: safe to re-POST same payload.

---

## 8. Bot status vs portal flags

```
Portal:  students.submitted  ──►  “student finished portal flow”
         students.locked     ──►  “teacher froze portal edits”
Neither implies FEMIS acceptance.

Bot:     fill only           → fill_success
         finish + indicator  → success
         finish, no indicator→ submit_failed
         exception           → error
```

Documented from `src/main.py` L19–39, L177–203 and `src/form_filler.py` L50–55; covered by `test_submission_status.py` (12/12).

---

## 9. Contract proposal (future API — design only, not implemented)

### 9.1 What the portal provides (write path)

- Stable **logical field IDs** (portal form names or DB names — pick one and version it).  
- Tab-scoped partial updates + explicit finalization event (`finalize` ≠ FEMIS success).  
- Role-gated mutations (student own row, teacher class/section, admin).  
- Multi-value as **arrays** over the wire; CSV only as storage detail.

### 9.2 What the bot consumes (read path)

- Snapshot of finalized (or explicitly claimed) student payload keyed by logical field IDs.  
- Aliases for FEMIS display names **owned by bot** (`PORTAL_NAME_ALIASES` + yaml), not by Flask.  
- No requirement for Flask session, HTML, or CSS.

### 9.3 What the bot returns (status path)

- Enum: `success | fill_success | submit_failed | error` (+ optional `dry_run`).  
- Optional: per-field fill errors, screenshot refs, FEMIS receipt ids — **never** credentials, selectors, CAPTCHA tokens, raw Playwright state.

### 9.4 Separation boundaries (must NOT enter future API)

Flask/SQLAlchemy internals · DB file paths & DDL · Selenium/Playwright state · FEMIS username/password · Gemini API keys · CAPTCHA solvers · CSS/DOM selectors · `field_mapping.yaml` file layout · student passwords/hashes beyond opaque auth tokens.

---

## 10. Auth boundary documentation (no code changes)

| Actor | Today | Future bot-job API |
|---|---|---|
| Student | Session login; own row only (`student_id` match) | Indirect — writes via portal only |
| Teacher | Session; class/section match; lock/unlock; read student JSON | May claim/prioritize jobs for own class |
| Admin | Session (portal admin routes) | Job admin, stats |
| Bot | Direct SQLite (same host today) | **Machine identity**: static bot token / mTLS / private network — **not** student/teacher passwords |
| Cross-host (PythonAnywhere portal ↔ local bot) | DB desync risk already documented | Requires API + token; SQLite remains storage behind portal |

**Not implemented in 3B.1** — documented for Phase 6/7 API design only.

---

## 11. What must NOT enter a future API / shared contract

- Flask `session`, `db.session`, model class internals.  
- Absolute paths (`femis-web/instance/femis.db`, Windows paths).  
- FEMIS / Gemini secrets, CAPTCHA workflows.  
- Playwright locators, `TAB_IDS`, portal HTML structure.  
- Raw `field_mapping.yaml` nodes (`note`, auto-discover blobs).  
- Student login credentials beyond already-hashed portal passwords.  
- Environment-specific column repair details (except as ops runbooks).

---

## 12. Verification checklist (synthetic script)

| # | Check | Result |
|---|---|---|
| 1 | Tab1 create ok | PASS |
| 2–4 | Tab3/5/6 save ok | PASS |
| 5 | Final-submit ok | PASS |
| 6–7 | `submitted=True`, `locked=False` | PASS |
| 8 | `temp_id` dropped | PASS |
| 9–25 | Field identity map (renames + CSV + conditionals) | PASS |
| 26–31 | Re-save Tab1 does not blank other tabs | PASS |
| 32–45 | `WebFormHandler.read_by_id` + transport alias + yaml keys | PASS |
| 46–56 | `PORTAL_NAME_ALIASES` resolutions | PASS |
| 57–63 | Bot row has all critical `source_field` keys non-empty | PASS |
| 64–66 | Final-submit idempotent / overwrite | PASS |
| 67–74 | Direct SQLite identity + cleanup delete | PASS |
| — | **TOTAL** | **74/74 PASS** |

---

## 13. Test suite results (Phase 3B.1 gate)

| Suite | Result |
|---|---|
| `python test_data_integrity.py` | 24/24 |
| `python test_submission_status.py` | 12/12 |
| `python smoke_test.py` | 14/14 |
| `python smoke_test_bot.py` | 3/3 |
| **Total** | **53/53** |

Synthetic phase script: 74/74 (extra; not part of 53).

---

## 14. Git footprint (this phase)

**Expected after 3B.1:**  
- **Added:** `docs/phase3b1-data-contract-audit.md` (this file).  
- **Untracked temp:** `C:\Users\faiza\AppData\Local\Temp\opencode\phase3b1_synthetic_trace.py` (outside repo).  
- **No changes** to portal, bot, yaml, schema, auth, hosting.

**Pre-existing dirty tree (Phase 2 / 3A.x, untouched):**  
`audit_portal.py`, `config/field_mapping.yaml`, `femis-web/app.py`, `femis-web/static/form.js`, `femis-web/templates/form.html`, `smoke_test.py`, `src/data_sources/webform_handler.py`, `src/form_filler.py`, `src/main.py`, untracked `docs/*` prior files, `smoke_test_bot.py`, `test_data_integrity.py`, `test_submission_status.py`.

---

## 15. Stop conditions honored

- [x] No code edits to implementation files  
- [x] No `bot_jobs`  
- [x] No live FEMIS submit  
- [x] No commit  
- [x] Synthetic student created and deleted  
- [x] DB canonical columns unchanged  

**Next session anchor:** await approval for the next single roadmap step (e.g., Phase 3B.2 contract API design doc, or deployment-schema remediation runbook — not started here).
