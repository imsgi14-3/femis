# FEMIS Separation Audit — READ-ONLY Analysis

**Date:** 2026-09-24
**Scope:** Complete repository audit to plan separation into STUDENT PORTAL + FEMIS BOT with a shared DATABASE contract.
**Phase rules honored:** No application code modified, no schema changes, no migrations, no dependencies installed, no files deleted. The repository's own `smoke_test.py` was executed for verification (17/17 pass; it creates and deletes its own test row).

---

## STEP 1 — Current Architecture

### 1.1 Entry points

| Module | Entry point | How it runs |
|---|---|---|
| Student Portal | `femis-web/app.py` (`Flask` app), `femis-web/wsgi.py` | `python femis-web/app.py` locally; `gunicorn wsgi:app` via `Procfile` / `render.yaml` (Render); also deployed on PythonAnywhere (per `SESSION_HANDOFF.md`) |
| FEMIS Bot (batch) | `src/main.py` → `FEMISBot.run()` | `python -m src.main <source> --type {photos,excel,google_sheets,webform,auto} [--submit]` — local, headed Chromium/Edge via Playwright |
| FEMIS Bot (single record, DB-driven — the path actually used) | `test_bot.py` | `python test_bot.py [--student-id N] [--submit] [--manual-login]` |
| Portal auditor (tooling) | `audit_portal.py` | Standalone Playwright script; diffs live FEMIS portal DOM vs `form.html` + `field_mapping.yaml` |

There is **no bot dashboard / control portal** anywhere in the repository. Bot output = timestamped JSON reports in `data/output/report_*.json`, logs in `data/logs/run_*.log`, screenshots, and `data/logs/api_errors.log`.

### 1.2 Flask routes (`femis-web/app.py`)

| Route | Method | Purpose | Auth |
|---|---|---|---|
| `/` | GET | Role redirect | session `role` |
| `/login` | GET/POST | Student/teacher login; **creates** Student on unknown identity | none |
| `/logout` | GET | `session.clear()` | none |
| `/form/<student_id>` | GET | Renders 7-tab `form.html` | session; student must own id; honors `is_locked` |
| `/student-dashboard` | GET | Student dashboard | session `user_name` |
| `/teacher-dashboard` | GET | Teacher class list | session role=teacher |
| `/api/save-tab` | POST | Upsert tab data (creates row when `student_id` null) | partial (see §10) |
| `/api/final-submit` | POST | Sets `submitted=True` **only** — receives **no field data** | **none** |
| `/api/upload-file` | POST | Saves file to `femis-web/uploads/`, sets column to filename | **none** |
| `/submit` | POST | Legacy full-form POST (blocked in browser by `form.js` `preventDefault`) | none |
| `/success/<student_id>` | GET | Success page | none |
| `/students` | GET | List ALL students | **none** |
| `/students/<id>/json` | GET | Full row as JSON | **none** |
| `/api/lock/<id>`, `/api/unlock/<id>` | POST | Teacher lock/unlock | session role=teacher |
| `/api/register-teacher`, `/api/setup-teacher` | POST | Teacher CRUD | teacher session / first-run |
| `/api/districts/<province>`, `/api/sub-sectors/<sector>` | GET | Cascading dropdown data (hardcoded maps) | none |

### 1.3 Templates & JavaScript

- Templates: `base.html`, `login.html`, `dashboard.html` (student+teacher), `form.html` (7 tabs, 1233 lines), `list.html`, `success.html`.
- JavaScript: `static/form.js` (882 lines — cascading dropdowns, conditionals, dirty tracking, per-tab validation, AJAX save, edit prefill) plus inline scripts in `login.html` / `dashboard.html`.
- Dropdown option source: `femis-web/portal_options.json` (loaded per request by `seed_options()`).

### 1.4 Database models & initialization

- `Student` — 139 columns, single table `students` (`femis-web/app.py:49-206`).
- `Teacher` — table `teachers`.
- Init: `db.create_all()` at import + an ad-hoc inline "migration" that `ALTER TABLE` adds `sub_sector_id` / `present_sub_sector_id` if missing (`app.py:34-43`). Silent `except: pass`.
- URI: `DATABASE_URL` env or `sqlite:///femis-web/instance/femis.db`.

### 1.5 Database files — ⚠ TWO DIVERGENT COPIES

| File | Rows | Tables | Status |
|---|---|---|---|
| `femis-web/instance/femis.db` | 6 students + 1 teacher | students, teachers | **LIVE** — used by Flask (basedir) and by the bot (`webform_handler.DB_PATH`). Currently file-locked (Flask dev server running). Has extra legacy column `transport TEXT` not in the model. Row id=8 has NULL `created_at`/`submitted` (raw-SQL insert via `insert_test_record.py`). |
| `instance/femis.db` (repo root) | 7 students, different id set (1,2,3,4,5,6,7) | students only | **STALE/ORPHAN** — artifact of an older app path (pre commit `539f86d` "Fix SQLite DB path to absolute"). Missing `sub_sector_id`, `present_sub_sector_id`, `transport`, `guardian_email`, `address`, `disability_certificate`. Nothing in current code reads it. |

`SESSION_HANDOFF.md` also records that the **local SQLite and the PythonAnywhere SQLite are not synced** — so up to three divergent copies may exist across environments.

`.gitignore` excludes `*.db`, `instance/`, `femis-web/instance/` — DBs are not in git (good), and there is no backup mechanism.

### 1.6 Authentication / session handling

- Flask signed cookie session (`SECRET_KEY` env, dev fallback hardcoded).
- **Student login has no password**: identity = `name + class_id + section_id + roll_no` matched with `ilike`; unknown identity **auto-creates** a Student row (`app.py:421-440`).
- Teacher login: name + class + section + password hash (werkzeug).
- The bot has **no** relationship with Flask sessions. It authenticates to the official FEMIS portal (`src/auth.py`): saved Playwright `storage_state` (`data/logs/femis_session.json`) → interactive CAPTCHA (human) → auto CAPTCHA (local OCR stub `src/ocr/local_captcha.py` returns `''` currently → Gemini fallback) → manual fallback via `data/logs/captcha_code.txt`.

### 1.7 File uploads

- Only field: `disability_certificate` (Tab 6, `input[type=file]`).
- `POST /api/upload-file` → `femis-web/uploads/student_{id}_{field}{ext}`, 16 MB cap; column stores the filename.
- Side effect: during `save-tab`, the file input's browser value `C:\fakepath\...` is also JSON-serialized into `data` and — because a `disability_certificate` column exists — is written to the DB first; the subsequent upload call overwrites it with the real filename. If upload fails, junk remains.
- The bot never uploads files to the official FEMIS portal (file inputs are skipped during DOM learning and have no fill routine).

### 1.8 Bot browser-automation entry points

- `src/main.py` — orchestrator: load data → login → `goto(create_url)` → per student `fill_student_form` → optional `submit_form` → JSON report.
- `test_bot.py` — single student from SQLite: login reuse → `FormFiller.open_form` (create vs edit detection) → fill → optional submit.
- `src/form_filler.py` (2318 lines) — the engine: tab clicking, field fill by name/label, `Save & Next` handling, `_force_save` (FormData POST + Laravel `_method=PUT` to `form.action`), validation capture, Finish click, success wait, DOM "learning" that **rewrites `config/field_mapping.yaml` at runtime**.
- `src/auth.py` — portal login/CAPTCHA/session persistence.
- Support: `audit_portal.py`, `explore_portal.py`, `discover_dom.py`, `probe_*` scripts (some referenced in handoff as temporary).

### 1.9 Configuration & environment

| File | Owner | Contents | Notes |
|---|---|---|---|
| `config/settings.yaml` | Bot | portal URLs, timeout 30000, slow_mo 500, captcha, OCR, batch delay 2000ms, output dir | listed in `.gitignore` as `config/settings.yaml` but **is tracked** (present in working tree; ignore pattern ineffective for already-tracked file) |
| `config/field_mapping.yaml` | Bot | 2368 lines, 215 leaf field configs across 7 tabs | **Bot mutates this file at runtime** (`_learn_unmapped_fields` → `_save_field_map`) |
| `config/femisbot-*.json` | Bot | Google service account | `config/*.json` gitignored |
| `.env` | Bot | `FEMIS_USERNAME/PASSWORD`, `GEMINI_API_KEY`, … | gitignored ✓ |
| `.en` | ? | **`GROQ_API_KEY=...` — TRACKED IN GIT** | ⚠ secret committed (`.gitignore` covers `.env` but not `.en`) |
| `.env.example` | both | template | |
| `render.yaml`, `Procfile` | Portal | gunicorn deploy | |

Flask env: `SECRET_KEY`, `DATABASE_URL`, `PORT`. Bot env: `FEMIS_USERNAME`, `FEMIS_PASSWORD`, `GEMINI_API_KEY`, `GOOGLE_SHEETS_CREDENTIALS`, `GOOGLE_FORMS_SPREADSHEET_ID`.

### 1.10 Dependencies

- Root `requirements.txt` (bot): playwright, google-generativeai, google-genai, opencv-python, Pillow, gspread, oauth2client, pyyaml, openpyxl, python-dotenv. **No Flask.**
- `femis-web/requirements.txt` (portal): flask, flask-sqlalchemy, gunicorn. **No Playwright.**
- ⚠ Root and portal dependency sets share no overlap, but `smoke_test.py` imports **both** worlds (portal `app` + `src.form_filler`).

### 1.11 Tests & scripts

| Script | What it does | Touches live DB? |
|---|---|---|
| `smoke_test.py` | 17 checks: save-tab persistence, JS mandatory lists, field_mapping labels vs form.html, date normalizer | Yes — creates + deletes a test row |
| `browser_smoke_test.py` | Playwright e2e against `127.0.0.1:5000` (login → autofill → save → JSON verify) | Yes — creates row |
| `test_bot.py` | Manual/real bot run against official FEMIS portal | Read-only on DB |
| `insert_test_record.py` | Raw INSERT of "Ahmed Khan" | Yes — DELETE + INSERT |
| `audit_portal.py` | Official-portal DOM auditor (957 lines) | No |

No test framework (no pytest/unittest config).

### 1.12 Dependency map (who depends on what)

```
                     ┌────────────────────────────────────────────┐
                     │            SHARED RUNTIME STATE            │
                     │  femis-web/instance/femis.db  (canonical)  │
                     │  instance/femis.db            (stale)      │
                     │  config/field_mapping.yaml (bot-mutated)   │
                     │  data/logs/* (session, logs, screenshots)  │
                     │  femis-web/uploads/*                        │
                     └────────▲───────────────────────▲───────────┘
                              │                       │
        SQLAlchemy ORM        │                       │  raw sqlite3 SELECT/UPDATE
        (db.create_all,       │                       │  (WebFormHandler — path
         ad-hoc ALTER)        │                       │   hardcoded to femis-web/…)
                              │                       │
        ┌─────────────────────┴──────┐   ┌────────────┴──────────────────────┐
        │      STUDENT PORTAL        │   │           FEMIS BOT               │
        │  femis-web/app.py          │   │  test_bot.py / src/main.py         │
        │  templates/*.html          │   │  src/form_filler.py  (Playwright)  │
        │  static/form.js            │   │  src/auth.py (portal CAPTCHA)      │
        │  portal_options.json       │   │  config/settings.yaml              │
        │  Flask session auth        │   │  config/field_mapping.yaml (R/W)   │
        │  NO bot imports            │   │  .env (FEMIS creds, Gemini)        │
        └────────────────────────────┘   │  NO Flask imports                  │
                                         └────────────────────────────────────┘
        Coupling points (the contract surface):
          (1) SQLite file path + table/column NAMES
          (2) FORM_FIELD_MAP (app.py) ↔ PORTAL_NAME_ALIASES/form.js reverseMap
              — the same alias knowledge is DUPLICATED in 3 places
          (3) semantic agreement on "submitted/locked/processed" (undocumented)
          (4) smoke_test.py imports BOTH modules (test-level coupling only)

        Official FEMIS portal (femis.fde.gov.pk) — external system,
        depended on ONLY by the bot.
```

Key observation: **the bot does not import Flask code, and the portal does not import bot code.** The real coupling is (a) the SQLite file, (b) column-name conventions, (c) alias tables duplicated across `FORM_FIELD_MAP` / `PORTAL_NAME_ALIASES` / `form.js reverseMap`.

---

## STEP 2 — Student Data Ownership: Complete 7-Tab Field Map

Legend for **Validation**: `HTML` = `required` attribute; `JS-M` = `mandatoryByTab` in `form.js`; `JS-C` = `conditionalRequired` / custom JS rule; **Server**: Flask performs **zero** validation on `/api/save-tab` (any value for any known column is stored).

Legend for **Persist?**: ✅ persisted → column; ❌ **silently dropped** (no column / no map entry — `api_save_tab` skips unknown keys with no error); ⚠️ partial/conditional.

### TAB 1 — Personal Details (38 fields)

| # | HTML `name` | JS field | Flask/API (`FORM_FIELD_MAP`) | DB column | Validation | File | Notes / gaps |
|---|---|---|---|---|---|---|---|
| 1 | `name` | same | pass-through | `name` | HTML, JS-M | | Portal requires **CAPITALS only**; bot uppercases (`CAPITAL_NAME_SOURCES`); portal does not enforce |
| 2 | `is_bform_available` | same | pass-through | `is_bform_available` | HTML, JS-M | | radio 1/0; toggles #3 |
| 3 | `b_form` | same | pass-through | `b_form` | HTML, JS-M if #2=1 | | JS auto-format `XXXXX-XXXXXXX-X`; bot `format_cnic`; portal dedupe key (422 "already taken") |
| 4 | `gender` | same | pass-through | `gender` | HTML, JS-M | | |
| 5 | `date_of_birth` | same | pass-through | `date_of_birth` | HTML, JS-M | | `type=date` → stored `YYYY-MM-DD`; bot rewrites to `DD/MM/YYYY` for portal |
| 6 | `birth_province_id` | same | pass-through | `birth_province_id` | HTML, JS-M | | stores province **text** (opts value); cascade trigger |
| 7 | `birth_district_id` | same | pass-through | `birth_district_id` | HTML, JS-M | | filled from `/api/districts/<province>`; stores district **name** |
| 8 | `nationality` | same | pass-through | `nationality` | HTML, JS-M | | "Other" shows #9 |
| 9 | `nationality_id` | same | pass-through | `nationality_id` | JS-C (Other) | | |
| 10 | `domicile_province_id` | same | pass-through | `domicile_province_id` | — | | optional |
| 11 | `domicile_district_id` | same | pass-through | `domicile_district_id` | — | | cascade |
| 12 | `address_type` | same | pass-through | `address_type` | HTML, JS-M | | conditional: Sector/Village/Housing Society/Other show/hide siblings |
| 13 | `sector_id` | same | pass-through | `sector_id` | — | | shown when type=Sector |
| 14 | `sub_sector_id` | same | pass-through | `sub_sector_id` | — | | cascade `/api/sub-sectors`; **added by ad-hoc ALTER** (old DBs lack it) |
| 15 | `village_id` | same | pass-through | `village_id` | — | | |
| 16 | `housing_society_id` | same | pass-through | `housing_society_id` | — | | |
| 17 | `address` | same | pass-through | `address` | HTML label ⋆ (Other type) | | textarea; JS validation only enforces when visible |
| 18 | `house` | same | pass-through | `house` | HTML, JS-M | | required unless type=Other (JS toggles) |
| 19 | `street` | same | pass-through | `street` | HTML, JS-M | | same |
| 20 | `contact_number` | same | pass-through | `contact_number` | HTML, JS-M | | JS `formatMobile` → `0XXX-XXXXXXX` |
| 21 | `city_id` | same | pass-through | `city_id` | HTML, JS-M | | |
| 22 | `same_as_permanent_address` | same | **→ `same_address`** | `same_address` | — | | checkbox; JS autofills all `present_*` pairs; **edit prefill broken** (reverseMap key mismatch — sees below) |
| 23 | `present_address_type` | same | pass-through | `present_address_type` | — | | collected even when hidden (special-cased in JS) |
| 24 | `present_sector_id` | same | pass-through | `present_sector_id` | — | | |
| 25 | `present_sub_sector_id` | same | pass-through | `present_sub_sector_id` | — | | ad-hoc ALTER column |
| 26 | `present_village_id` | same | pass-through | `present_village_id` | — | | |
| 27 | `present_housing_society_id` | same | pass-through | `present_housing_society_id` | — | | |
| 28 | `present_address` | same | **→ `present_address_other`** | `present_address_other` | — | | textarea (Other type) |
| 29 | `present_house` | same | pass-through | `present_house` | — | | |
| 30 | `present_street` | same | pass-through | `present_street` | — | | |
| 31 | `religion` | same | pass-through | `religion` | HTML, JS-M | | "Non-Muslim" shows #32 |
| 32 | `religion_id` | same | pass-through | `religion_id` | JS-C | | |
| 33 | `language_id` | same | pass-through | `language_id` | HTML, JS-M | | "Other" shows #34 |
| 34 | `mother_language_other` | same | pass-through | `mother_language_other` | JS-C | | |
| 35 | `blood_group` | same | pass-through | `blood_group` | — | | optional |
| 36 | `email` | same | pass-through | `email` | HTML, JS-M | | |
| 37 | `girls_stipend` | same | pass-through | `girls_stipend` | — | | radio; optional; **placed on Tab 1 in our form** (FEMIS placement may differ) |
| 38 | `is_hafiz` | same | pass-through | `is_hafiz` | — | | same note as #37 |
| — | `student_id` (hidden) | same | routing only | `id` (implicit) | — | | |
| — | `is_locked` (hidden) | — | ❌ dropped (no column) | — | — | | UI-only |

### TAB 2 — Parents / Guardian (37 fields)

| # | HTML `name` | JS field | Flask/API | DB column | Validation | File | Notes / gaps |
|---|---|---|---|---|---|---|---|
| 1 | `father_name` | same | pass-through | `father_name` | HTML, JS-M | | portal: capitals only |
| 2 | `father_cnic` | same | pass-through | `father_cnic` | HTML, JS-M | | CNIC format JS |
| 3 | `is_father_alive` | same | pass-through | `is_father_alive` | HTML, JS-M | | hides father detail block when 0; auto-drives `is_orphan` |
| 4 | `father_contact` | same | pass-through | `father_contact` | JS-M (label ⋆; HTML attr absent) | | shown only when alive=1; still mandatory in JS list |
| 5 | `father_landline` | same | pass-through | `father_landline` | — | | |
| 6 | `father_email` | same | pass-through | `father_email` | — | | |
| 7 | `father_qualification` | same | pass-through | `father_qualification` | **JS-M** (HTML select has no required) | | |
| 8 | `father_profession` | same | pass-through | `father_profession` | HTML, JS-M | | "Other" shows #9; "Govt Employee" shows BPS |
| 9 | `father_profession_other` | same | pass-through | `father_profession_other` | JS-C | | |
| 10 | `father_monthly_income` | same | pass-through | `father_monthly_income` | **JS-M** | | |
| 11 | `father_bps` | same | pass-through | `father_bps` | JS-C (Govt Employee) | | |
| 12 | `father_domicile_province_id` | same | pass-through | `father_domicile_province_id` | — | | cascade |
| 13 | `father_domicile_district_id` | same | pass-through | `father_domicile_district_id` | — | | |
| 14 | `mother_name` | same | pass-through | `mother_name` | HTML, JS-M | | capitals in portal |
| 15 | `is_mother_alive` | same | pass-through | `is_mother_alive` | HTML, JS-M | | hides mother details when 0; drives orphan |
| 16 | `mother_cnic` | same | pass-through | `mother_cnic` | — | | |
| 17 | `mother_contact` | same | pass-through | `mother_contact` | JS-M | | |
| 18 | `mother_landline` | same | pass-through | `mother_landline` | — | | |
| 19 | `mother_email` | same | pass-through | `mother_email` | — | | |
| 20 | `mother_qualification` | same | pass-through | `mother_qualification` | — | | optional in our form |
| 21 | `mother_profession` | same | pass-through | `mother_profession` | HTML, JS-M | | "Other" shows #22 |
| 22 | `mother_profession_other` | same | pass-through | `mother_profession_other` | JS-C | | |
| 23 | `mother_monthly_income` | same | pass-through | `mother_monthly_income` | **JS-C**: mandatory unless profession=Housewife | | custom JS rule |
| 24 | `mother_bps` | same | pass-through | `mother_bps` | JS-C | | |
| 25 | `is_orphan` | same | pass-through | `is_orphan` | HTML, JS-M | | JS auto-sets Yes + type when a parent dead; JS blocks Yes if both alive |
| 26 | `orphan_type` | same | pass-through | `orphan_type` | **JS-C** (is_orphan=1) | | Single/Double Orphan (auto-set) |
| 27 | `guardian_name` | same | pass-through | `guardian_name` | HTML, JS-M | | block always visible (FEMIS-mandatory) |
| 28 | `guardian_cnic` | same | pass-through | `guardian_cnic` | HTML, JS-M | | |
| 29 | `guardian_relation` | same | pass-through | `guardian_relation` | HTML, JS-M | | "Other" shows #30 |
| 30 | `guardian_relation_other` | same | pass-through | `guardian_relation_other` | JS-C | | |
| 31 | `guardian_contact` | same | pass-through | `guardian_contact` | HTML, JS-M | | |
| 32 | `guardian_email` | same | pass-through | `guardian_email` | — | | |
| 33 | `guardian_qualification` | same | pass-through | `guardian_qualification` | — | | text input (free text) |
| 34 | `guardian_profession` | same | pass-through | `guardian_profession` | HTML, JS-M | | "Other" shows #35 |
| 35 | `guardian_profession_other` | same | pass-through | `guardian_profession_other` | JS-C | | **not in bot field_mapping** (bot never fills it) |
| 36 | `guardian_income` | same | pass-through | `guardian_income` | HTML, JS-M | | |
| 37 | `guardian_bps` | same | pass-through | `guardian_bps` | — | | |

### TAB 3 — Educational Details (24 fields)

| # | HTML `name` | JS field | Flask/API | DB column | Validation | File | Notes / gaps |
|---|---|---|---|---|---|---|---|
| 1 | `class_id` | same | pass-through | `class_id` | HTML, JS-M | | radio value = digit string (`"9"`); **data inconsistency observed**: rows contain both `"9"` and `"Class 9"`; JS section options depend on class (9+ → A,B,C) |
| 2 | `section_id` | same | pass-through | `section_id` | HTML, JS-M | | radios regenerated by JS |
| 3 | `class_group_id` | same | pass-through | `class_group_id` | — | | |
| 4 | `result_percentage` | same | **→ `last_class_result`** | `last_class_result` | — | | reverseMap prefill uses `result_percentage` ✓ |
| 5 | `date_of_admission` | same | pass-through | `date_of_admission` | HTML + `pattern=\d{2}/\d{2}/\d{4}` | | portal wants `mm/dd/yyyy` UI / `DD/MM/YYYY` POST (bot converts) |
| 6 | `admission_number` | same | pass-through | `admission_number` | HTML, JS-M | | |
| 7 | `last_fde_institution_id` | same | pass-through | `last_fde_institution_id` | — | | "Other" shows #9 |
| 8 | `class_admitted_id` | same | pass-through | `class_admitted_id` | HTML, JS-M | | JS rebuilds range: class≤5→1..5, ≥6→6..10 |
| 9 | `last_other_institution` | same | **→ `last_institution_other`** | `last_institution_other` | JS-C | | |
| 10 | `shift` | same | pass-through | `shift` | HTML, JS-M | | Morning/Evening |
| 11 | `medium_of_instruction` | same | pass-through | `medium_of_instruction` | HTML, JS-M | | |
| 12 | `primary_education_completion_years` | same | pass-through | `primary_education_completion_years` | — | | intentionally **not** mandatory (FEMIS rule) |
| 13 | `school_meal_program_availing` | same | pass-through | `school_meal_program_availing` | **JS-M** | | |
| 14 | `mode_of_study` | same | pass-through | `mode_of_study` | HTML, JS-M | | |
| 15 | `total_siblings` | same | pass-through | `total_siblings` | HTML, JS-M | | |
| 16 | `siblings_other_fde` | same | pass-through | `siblings_other_fde` | — | | |
| 17 | `siblings_same_institution` | same | **→ `siblings_same`** | `siblings_same` | — | | |
| 18 | `siblings_private` | same | pass-through | `siblings_private` | — | | |
| 19 | `transport_facility` | same | **❌ NO MAPPING, NO COLUMN → DROPPED** | *(none)* | HTML, **JS-M** | | ⚠ **Confirmed data loss**: student's Institution Bus / Private / Never choice is never stored. Legacy unused column `transport TEXT` exists only in the live DB file (not in the model). Bot work-around: if `bus_route` non-empty it forces "Institution Bus" |
| 20 | `bus_route` | same | pass-through | `bus_route` | **JS-C** (transport = Bus / Institution Bus) | | |
| 21 | `scholarship` | same | pass-through | `scholarship` | HTML, JS-M | | "1" shows details |
| 22 | `cocurricular_activities` | same | pass-through | `cocurricular_activities` | HTML, JS-M | | "1" shows #24 |
| 23 | `scholarship_details` | same | pass-through | `scholarship_details` | JS-C | | |
| 24 | `cocurricular_details` | same | **→ `achievement_details`** | `achievement_details` | JS-C | | |

### TAB 4 — Emergency Contact (4 fields)

| # | HTML `name` | JS field | Flask/API | DB column | Validation | File | Notes |
|---|---|---|---|---|---|---|---|
| 1 | `emergency_name` | same | pass-through | `emergency_name` | HTML, JS-M | | capitals in portal |
| 2 | `emergency_contact` | same | pass-through | `emergency_contact` | HTML, JS-M | | JS mobile format |
| 3 | `emergency_relation` | same | pass-through | `emergency_relation` | HTML, JS-M | | Other/Others shows #4 |
| 4 | `emergency_relation_other` | same | pass-through | `emergency_relation_other` | JS-C | | |

### TAB 5 — IDPs Details (4 fields)

| # | HTML `name` | JS field | Flask/API | DB column | Validation | File | Notes / gaps |
|---|---|---|---|---|---|---|---|
| 1 | `is_refugee` | same | pass-through | `is_refugee` | HTML, JS-M | | "1" shows #2–#4 |
| 2 | `idp_status_id` | same | pass-through | `idp_status_id` | **JS-C** (is_refugee=1) | | radios with text values |
| 3 | `is_registered_refugee` | same | pass-through | `is_registered_refugee` | **JS-C** (is_refugee=1) | | "1" shows #4 |
| 4 | `refugee_card_number` | same | **❌ NO MAPPING → DROPPED** | *(column `refugee_card` exists but unreachable)* | **JS-C** | | ⚠ **Confirmed data loss**: HTML name ≠ column name; `FORM_FIELD_MAP` has no entry → dropped by `api_save_tab`. Edit-prefill also broken: reverseMap maps `refugee_card`→`refugee_card` but HTML field is `refugee_card_number`. Bot aliases `refugee_card`→`refugee_card_number` (portal side OK) but the DB value is always empty. |

### TAB 6 — Health Details (21 fields)

| # | HTML `name` | JS field | Flask/API | DB column | Validation | File | Notes / gaps |
|---|---|---|---|---|---|---|---|
| 1 | `has_major_disability` | same | pass-through | `has_major_disability` | HTML, JS-M | | "1" shows #2–#3 |
| 2 | `disability_types[]` | checkbox multi, joined `","` by JS | **❌ NO MAPPING (`digital_device_type[]` is mapped, this is not) → DROPPED** | *(column `disability_types` unreachable from save-tab)* | JS-C (label ⋆ when shown) | | ⚠ **Confirmed data loss** |
| 3 | `disability_certificate` | file | via `/api/upload-file` (`setattr(field_name)`) → `disability_certificate` | `disability_certificate` | — | ✅ | save-tab first stores `C:\fakepath…` string; upload overwrites with filename; bot never sends files to FEMIS |
| 4 | `has_mental_disability` | same | pass-through | `has_mental_disability` | HTML, JS-M | | "1" shows #5 |
| 5 | `mental_disability_type` | same | pass-through | `mental_disability_type` | **JS-C** | | "Other" shows #6 |
| 6 | `mental_disability_other` | same | pass-through | `mental_disability_other` | JS-C | | |
| 7 | `other_medical_condition` | same | **→ `other_conditions`** | `other_conditions` | — | | edit-prefill reverseMap key mismatch (`other_conditions` not keyed) → **not prefilled** on edit |
| 8 | `visually_fit` | same | pass-through | `visually_fit` | HTML, JS-M | | "0" shows #10 (JS rule: prescription when FIT=No) |
| 9 | `uses_glasses` | same | pass-through | `uses_glasses` | HTML, JS-M | | |
| 10 | `glass_prescription` | same | pass-through | `glass_prescription` | **JS-C** (visually_fit=0), HTML required attr | | |
| 11 | `difficulty_seeing_board` | same | pass-through | `difficulty_seeing_board` | **JS-M** | | |
| 12 | `has_hearing_difficulties` | same | pass-through | `has_hearing_difficulties` | HTML, JS-M | | "1" shows #13 |
| 13 | `uses_hearing_aid` | same | pass-through | `uses_hearing_aid` | **JS-C**, HTML required | | "1" shows #14 |
| 14 | `hearing_aid_details` | same | pass-through | `hearing_aid_details` | — | | |
| 15 | `difficulty_listening` | same | pass-through | `difficulty_listening` | HTML, JS-M | | |
| 16 | `difficulty_walking` | same | pass-through | `difficulty_walking` | HTML, JS-M | | |
| 17 | `uses_crutches_walker` | same | pass-through | `uses_crutches_walker` | HTML, JS-M | | |
| 18 | `difficulty_reading_writing` | same | pass-through | `difficulty_reading_writing` | **JS-M** | | |
| 19 | `difficulty_remembering` | same | pass-through | `difficulty_remembering` | **JS-M** | | |
| 20 | `difficulty_concentrating` | same | pass-through | `difficulty_concentrating` | **JS-M** | | |
| 21 | `basic_vaccination_completed` | same | pass-through | `basic_vaccination_completed` | — | | optional |

### TAB 7 — Digital Access (3 fields) — ⚠ CRITICAL

| # | HTML `name` | JS field | Flask/API | DB column | Validation | File | Notes / gaps |
|---|---|---|---|---|---|---|---|
| 1 | `digital_device_at_home` | same | *(never sent — see below)* | `digital_device_at_home` | HTML, JS-M | | |
| 2 | `digital_device_type[]` | joined `","` | **→ `digital_device_type`** *(never sent — see below)* | `digital_device_type` | **JS-C** | | |
| 3 | `internet_at_home` | same | *(never sent — see below)* | `internet_at_home` | HTML, JS-M | | |

**CRITICAL:** On Tab 7 the Save&Next button becomes "Submit" and `form.js` switches endpoints:

```js
var isLastTab = currentTab >= 6;
var endpoint  = isLastTab ? "/api/final-submit" : "/api/save-tab";
var payload   = isLastTab ? { student_id: student_id.value }
                          : { tab: currentTab + 1, student_id: ..., data: data };
```

`/api/final-submit` reads **only** `student_id` and sets `submitted=True`. **The Tab-7 `data` object is built, validated by `validateTab(6)`, then discarded.** All three digital-access values are validated client-side and **never persisted**. (Legacy `/submit` would persist them but is disabled by `form.addEventListener("submit", e => e.preventDefault())`.)

### 2.1 Explicit gap register

**A. Fields submitted by JS but NOT persisted (silently dropped by `api_save_tab` `hasattr` filter):**

| Field | Why dropped | Impact |
|---|---|---|
| `transport_facility` | no column, no `FORM_FIELD_MAP` entry | Student's transport choice lost; bot defaults from `bus_route` only |
| `refugee_card_number` | column is `refugee_card`, no map entry | Refugee card number always NULL in DB |
| `disability_types[]` | `[]` suffix unmapped (unlike `digital_device_type[]`) | Disability types lost |
| `temp_id` | mapped to `None` (intentional) | none |
| `is_locked` | no column | UI-only, harmless |
| Tab 7 (all 3 fields) | never sent at all (final-submit payload) | **Digital access data never exists in DB** |
| `disability_certificate` (during save-tab) | has column — stores `C:\fakepath…` until upload overwrites | junk value if upload fails |

**B. Database columns with NO form source:**

| Column | Notes |
|---|---|
| `parent_name` | never written by any route/form (legacy) |
| `years_primary` | superseded by `primary_education_completion_years` (no HTML field) |
| `major_disability` | no HTML field; free-text disability detail never collected (JS reverseMap references non-existent `major_disability_text`) |
| `transport` | **not in the SQLAlchemy model**; orphan column present only in the live DB file |
| `role`, `roll_no`, `id`, `created_at`, `submitted`, `locked` | system/lifecycle columns (set by login/routes, not the 7-tab form) |

**C. Naming mismatches (the three classic suspects — verified against current code):**

| Suspect | Verdict (current code) |
|---|---|
| `transport_facility` | **STILL BROKEN** — HTML + JS-mandatory, zero persistence path |
| `refugee_card_number` vs `refugee_card` | **STILL BROKEN** — save AND prefill both miss; bot alias already correct for portal side |
| name capitalization | Portal-only rule; bot enforces uppercase at fill time (`_preflight_save` + `CAPITAL_NAME_SOURCES`); Student Portal stores whatever the user typed. Not a persistence bug, but a bot-retry trigger if names are mixed-case. |
| *(new)* `disability_types[]` | **BROKEN** — same class of bug as the two above; not previously called out |

**D. Fields silently ignored by save logic:** anything not matching a `Student` attribute (see A). No error is returned to the browser — the UI reports success.

**E. Conditional fields (show/hide):** `b_form`; `address_type` group (sector/village/housing/other/house+street); `nationality_id`; `religion_id`; `mother_language_other`; father/mother detail blocks; `orphan_type`; `*‑profession_other`; `guardian_relation_other`; `father_bps`; `bus_route`; `scholarship_details`; `cocurricular_details`; `emergency_relation_other`; `idp_fields`; `refugee_card_group`; `disability_fields`; `mental_disability_*`; `glass_prescription`; `hearing_aid_*`; `device_type_group`. JS collection skips invisible fields (except `present_*` special case) — so hidden conditionals save as absent (previous value retained on update, since only received keys are `setattr`'d).

**F. Value transformations before storage:**

| Where | Transform |
|---|---|
| `form.js` on input | CNIC → `XXXXX-XXXXXXX-X`; mobile → `0XXX-XXXXXXX` |
| `form.js` on collect | `digital_device_type[]` checkboxes → comma-joined string; unchecked checkbox → `""` |
| `form.js` autofill | same-as-temporary copies 7 pairs into `present_*` before save |
| `form.js` orphan logic | auto-sets `is_orphan`/`orphan_type` from parent-alive radios |
| Flask | none (raw store) |
| Bot (read-time only) | date `YYYY-MM-DD`→`DD/MM/YYYY`; names→UPPER; CNIC/mobile re-format; `class` digit→`Class N`; guardian defaults from father when non-orphan; `bus_route`→transport fallback |

**G. Edit-mode prefill gaps (`form.js reverseMap`):** `same_address` (key missing → looks for `same_as_permanent_address`? maps `same_as_permanent_address` key which never occurs as a DB col → checkbox never restored), `other_conditions` (not keyed → looks for field named `other_conditions`), `refugee_card` (maps to `refugee_card`, HTML is `refugee_card_number`). Values round-trip incorrectly on edit.

---

## STEP 3 — Existing Student Lifecycle

```
LOGIN (/login, student role)
  ├─ match (name, class, section, roll_no) ilike  → attach session.student_id
  └─ no match → INSERT minimal row (name/class/section/roll_no, role='student')
        │
        ▼
DRAFT  (submitted=0, locked=0)  ←──────────────┐
        │                                       │
        │ /api/save-tab  (tab=1 creates row     │ teacher or student
        │  when student_id null; later tabs     │ edits via /form + save-tab
        │  upsert received keys only)           │
        │ (tab number is NOT stored)            │
        ▼                                       │
FINAL  /api/final-submit {student_id}           │
  → submitted=1                                 │
  → tab-7 data never sent  ⚠                   │
  → redirect /success/<id>                      │
        │                                       │
        ▼                                       │
SUBMITTED (submitted=1) ── student may STILL ───┘
        │                    edit (save-tab does not check `submitted`;
        │                    dashboard shows "Edit Record")
        ▼
TEACHER: /api/lock  → locked=1
  • student saves blocked ("Record is locked by teacher")
  • form inputs disabled in JS when is_locked
  • teacher can still save; /api/unlock reverses
        │
        ▼
LOCKED (locked=1)   — nothing else. There is NO approval,
                      NO eligibility flag, NO per-tab progress,
                      NO "sent to FEMIS" state.
```

**What the flags actually mean today:**

| Flag | True means | Set by | Checked by |
|---|---|---|---|
| `submitted` | *student* clicked Submit on Tab 7 of *our* portal | `/api/final-submit` (and legacy `/submit`) | dashboard badge only — **bot ignores it** |
| `locked` | teacher froze the record against student edits | `/api/lock` | `save-tab` (non-teacher), `form.js` disable-all |

**Status-confusion hotspots (bot vs student):**

1. `submitted` ≠ "submitted to official FEMIS". Nothing records whether FEMIS Finish ever succeeded.
2. `locked` (teacher freeze) could easily be misread as "locked by bot worker".
3. `webform_handler.read_unprocessed/mark_processed` introduce a *third* concept (`processed` column) that **does not exist in the DB and is never called** by any entry point.
4. Bot reports (`status: success|error|skipped|submit_failed`) live only in throwaway JSON files, invisible to the portal.
5. Dashboard label "Submitted Students" on `/students` actually lists **all** rows including drafts.

No state field may be overloaded for both lifecycles in the separation design (see Step 5).

---

## STEP 4 — Current Bot Workflow

### 4.1 Record selection

| Runner | Selection | Filters |
|---|---|---|
| `test_bot.py --student-id N` | `read_by_id(N)` | none |
| `test_bot.py` (no id) | `read_all(limit=1)` → **first row `ORDER BY created_at ASC`** | none — ignores `submitted`, `locked`, completeness |
| `src/main.py --type webform` | `read_all()` — **every row** | none |
| `read_unprocessed()` | would filter `processed=0` if column existed | **dead code — never called** |

### 4.2 Obtaining student data

`WebFormHandler` opens `sqlite3.connect(femis-web/instance/femis.db)`, `SELECT *`, drops `id`/`created_at`, returns plain dicts keyed by **DB column names**. One read at start; no refresh; no version check.

### 4.3 DB → FEMIS field mapping

`config/field_mapping.yaml` (7 tab keys, 215 leaf configs): each leaf = `{label, type, required, source_field, options?, validation?, note?}`. Fill algorithm (`_fill_field`):

1. `value = data.get(source_field)` — **DB column name must match `source_field` exactly.**
2. Conditional short-circuits (`orphan_type`, `glass_prescription`, `transport_facility` fallback, guardian father-defaults).
3. Empty required → log `Missing required`, skip.
4. Transform (UPPER names, CNIC/mobile format, `Class N`).
5. Visibility guard (never fill hidden/other-tab controls).
6. Fill by portal `name` attr → label → JS fallback; verify; radio has 5-strategy cascade + JS group scan.

**Alias layer** `PORTAL_NAME_ALIASES` maps DB name → portal input name (`refugee_card`→`refugee_card_number`, `same_address`→`same_as_permanent_address`, `achievement_details`→`cocurricular_details`, …).

⚠ The YAML also contains **duplicate entries with FORM-side source names** (`result_percentage`, `last_other_institution`, `siblings_same_institution`, `cocurricular_details`, `other_medical_condition`, `same_as_permanent_address`, `transport_facility`) whose `data.get(...)` is always `None` because those keys are not DB columns; the correctly-named twin entries do the real work. Additionally, portal auto-learning has placed **Tab-7 digital fields under tab_4/tab_5 keys** (map pollution).

### 4.4 Handling of the 7 tabs / Save & Next

```
open_form(): search portal list by name → verify CNIC on row →
             open EDIT (form_mode='edit') or CREATE
fill_student_form():
  edit mode → _probe_incomplete_tab(): click tab N, Save & Next (probe),
               re-click tab; first failure = fill_from
  for tab 1..7:
      click tab nav (tab-nav-personal … tab-nav-digital)
      _fill_tab_fields (yaml-driven) + _learn_unmapped_fields (rewrites YAML)
      if tab < 7: _save_next()
           preflight (UPPER names, date rewrite)
           click #saveNextBtn / "Save & Next"
           sleep 2s, handle confirm dialog
           collect: UI errors, DOM errors, empty-required, invalid count,
                    HTTP responses captured by _attach_save_listeners
           ok = no errors && no 4xx/5xx && no empties/invalids
           if no network request observed → _force_save()  ← the PUT hack
           if !ok and edit-mode: one retry with _fill_default_required
           if !ok: log, re-click same tab, CONTINUE TO NEXT TAB ANYWAY
                    (create-mode has no retry)  ⚠
      (tab 7): after loop → _force_save()
submit_form():  (only with --submit)
      re-fill or repair → preflight → duplicate-422 recovery → click tab 7
      → click #saveNextBtn if visible → _force_save()
      → click #finishBtn → handle confirm
      → _wait_for_success(15s): visible "Form Submitted Successfully!" heading
         OR URL left /students/create while still on femis.fde.gov.pk with
         "successfully" in body or "/students" in URL
      → screenshot; return bool
```

**Where Save & Next is clicked:** after each of tabs 1–6 in `fill_student_form`, during `_probe_incomplete_tab`, once more on tab 7 in `submit_form`, plus force-save before Finish and after the final tab.

### 4.5 Progression / Finish / failure detection — as implemented today

| Concern | Mechanism | Persisted? |
|---|---|---|
| Successful tab progression | active-tab id changed + no errors + no empty-required + no invalids + (API traffic OR force-save OK) | **No** — only log lines |
| Finish | locator `#finishBtn` visible → click → confirm dialog | **No** |
| Success | `_wait_for_success` (heading or URL heuristic) | `submit_form` returns bool → report JSON `submitted` field |
| Validation failures | dialog handler, `.invalid-feedback` scrape, empty-required scan, HTTP ≥400 | logs + `api_errors.log` + screenshot |
| Network errors | Playwright exceptions caught per click; response listener flags ≥400 | logs |
| Timeouts | portal `timeout: 30000` config (used for goto); save waits fixed 2s; success wait 15s; login interactive 180s; manual CAPTCHA 600s | logs |
| Unexpected pages | `open_form` falls back to create; session check via URL/login-form heuristics; 503 portal → treated as generic failure | logs |
| Retries | save: 1× in edit-probe mode only; CAPTCHA: up to N; create-mode save: **none** | logs |
| Duplicate processing | **none locally**; portal-side dedupe: name+CNIC search → edit mode; 422 `b_form already taken` → `_recover_duplicate` | n/a |
| Two workers same student | **no protection whatsoever** (no claim, no lock, no unique job) | n/a |
| Progress storage | recomputed each run via `_probe_incomplete_tab` | **none** |
| Error storage | log files, screenshots, `api_errors.log`, in-memory `_dialog_messages` | **no DB** |

### 4.6 "Success" semantics — ⚠ currently misleading

`src/main.py:162`:

```python
"status": "success" if (submitted or not getattr(self, "submit", False)) else "submit_failed"
```

Without `--submit`, a **fill-only** run is reported as `success`. Only `test_bot.py --submit` ties success to the Finish confirmation — and even then success lives only in a log line + screenshot. **Nothing in the database knows whether FEMIS Finish completed.**

---

## STEP 5 — Proposed Database Contract

### 5.1 Design principles

1. `students` table stays **exactly as the Student Portal owns it** (columns, semantics of `submitted`/`locked` unchanged in meaning).
2. Bot lifecycle lives in a **new, separate table** `bot_jobs` (1:1 with `students`) inside the **same SQLite file** — the DB file remains "the contract", but ownership of rows is unambiguous: portal writes `students`, bot writes `bot_jobs`, portal gets **read** access for display only.
3. Why a separate table instead of columns on `students`:
   - zero risk of breaking `to_dict()`, save-tab's `hasattr` filter, or the 7-tab workflow;
   - no accidental conflation of `submitted`/`locked` with bot state;
   - bot can add/alter its own columns later without touching the portal model;
   - `/students/<id>/json` does not leak bot internals unless intentionally joined.
4. **Eligibility** is a rule, not a new student status: a job may run only when `students.submitted = 1` (teacher lock can be made a second gate later — see state machine).
5. One extra **portal-owned** column IS justified on `students`: `updated_at` (auto-touch on every save-tab/final-submit) so the bot can detect mid-flight student edits. This is additive and invisible to the form.

### 5.2 Proposed schema (NOT applied in this phase)

```sql
-- portal-owned (additive)
ALTER TABLE students ADD COLUMN updated_at DATETIME;          -- touched on every save
-- existing: submitted, locked unchanged

-- bot-owned
CREATE TABLE bot_jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id          INTEGER NOT NULL UNIQUE,   -- 1:1, FK logical (SQLite)
    bot_status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    current_tab         INTEGER,                   -- 1..7 tab being worked (NULL if none)
    last_completed_tab  INTEGER DEFAULT 0,         -- highest tab confirmed persisted in FEMIS
    failed_tab          INTEGER,
    failed_field        VARCHAR(120),
    failure_type        VARCHAR(40),               -- enum, see below
    failure_message     TEXT,
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 3,
    processing_started_at DATETIME,
    last_heartbeat_at   DATETIME,
    last_attempt_at     DATETIME,
    completed_at        DATETIME,
    claimed_by          VARCHAR(80),               -- worker id (hostname:pid)
    lease_expires_at    DATETIME,                  -- claim lease for crash recovery
    portal_mode         VARCHAR(10),               -- 'create' | 'edit' last used
    portal_record_url   VARCHAR(300),              -- official-FEMIS edit URL once known
    student_updated_at_seen DATETIME,              -- students.updated_at at claim time
    last_success_at     DATETIME,                  -- last time Finish was CONFIRMED
    notes               TEXT
);
CREATE INDEX idx_bot_jobs_status ON bot_jobs(bot_status, lease_expires_at);
```

### 5.3 Status vocabularies (kept strictly separate)

**STUDENT LIFECYCLE (portal-owned, existing semantics kept):**

| State | Source of truth | Meaning |
|---|---|---|
| `DRAFT` | `submitted = 0` | form in progress (derived, not stored) |
| `SUBMITTED` | `submitted = 1` | student finished our 7-tab form |
| `TEACHER_APPROVED / ELIGIBLE` | *does not exist yet* | **Recommendation:** do NOT invent a third student flag now; make bot eligibility = `submitted = 1` (+ optional gate: `locked = 1` if teachers should bless records before the bot runs — decision for Phase 3, default OFF to preserve current behavior) |

**BOT LIFECYCLE (bot-owned, new):**

| State | Meaning | Set when |
|---|---|---|
| `PENDING` | queued, not yet claimed | job row created (backfill for `submitted=1`; new rows via trigger/portal hook on final-submit) |
| `PROCESSING` | worker holds a valid lease | atomic claim succeeded |
| `COMPLETED` | official FEMIS Finish **confirmed** | `_wait_for_success` true AND finish clicked |
| `FAILED` | terminal until human/auto requeue | failure recorded & `attempt_count >= max_attempts`, OR non-retryable type |
| *(optional)* `RETRY_WAIT` | failed but attempts remain | transition out of PROCESSING on retryable failure |

### 5.4 State transitions

```
                 (job created / backfill where submitted=1)
                              │
                              ▼
                          ┌────────┐
            ┌─────────────│PENDING │◄──────────────┐
            │             └───┬────┘               │ requeue (manual or
            │ claim (atomic)   │                    │ retry policy)
            │                 ▼                    │
            │         ┌──────────────┐   failure   │
            │         │ PROCESSING   │────────────►┤
            │         │ tab=1..7     │             ▼
            │         │ heartbeat    │      ┌────────────┐
            │         └──────┬───────┘      │    FAILED  │
            │                │              │ failed_tab │
            │   Finish CONFIRMED            │ failed_field│
            │                │              │ failure_*  │
            │                ▼              └────────────┘
            │         ┌────────────┐
            └────────►│ COMPLETED  │  (completed_at, last_success_at,
                      └────────────┘   last_completed_tab=7)
```

Rules:

- `PENDING → PROCESSING` only via **atomic claim** (single `UPDATE ... WHERE id=? AND bot_status='PENDING'` — SQLite single-writer makes this safe; or API claim endpoint).
- Worker must refresh `last_heartbeat_at` ≥ every 30s and update `current_tab` after every confirmed Save & Next.
- `PROCESSING → PENDING` (lease takeover) allowed only when `lease_expires_at < now` (crash recovery) — status may physically remain `PROCESSING` until stolen; claim query accepts expired leases.
- `COMPLETED` is **only** reachable from a confirmed Finish. Fill-only runs must never set it.
- Student edits (`students.updated_at > student_updated_at_seen`) while `PROCESSING`/`FAILED` → policy: mark `PENDING` again (data changed ⇒ old attempt obsolete) or flag `notes='stale'`; recommended: requeue on completion check.

### 5.5 Failure taxonomy (`failure_type`)

`VALIDATION_FIELD` (include `failed_tab`+`failed_field`), `PORTAL_HTTP_4XX`, `PORTAL_HTTP_5XX`, `NETWORK`, `TIMEOUT`, `SESSION_EXPIRED`, `CAPTCHA_REQUIRED`, `UNEXPECTED_PAGE`, `BROWSER_CRASH`, `FINISH_UNCONFIRMED`, `DUPLICATE_CONFLICT`, `DATA_STALE`, `INTERNAL`.

---

## STEP 6 — Failure / Recovery Model (stress test)

Data needed to recover safely, at all times: **(student_id, bot_status, current_tab, last_completed_tab, attempt_count, lease/heartbeat, students.updated_at seen, portal_mode, portal_record_url)** + the student row itself.

| Scenario | What happens today | Recovery under proposed contract |
|---|---|---|
| Bot crashes mid-Tab 3 | nothing recorded; portal may hold 1–2 saved tabs (force-save) | row stays `PROCESSING`, `current_tab=3`, heartbeat stops → lease expires → another worker claims → `open_form` edit-mode `_probe_incomplete_tab` finds first unsaved tab → resume from Tab 3 (FEMIS-side partial save + DB-side progress agree) |
| Internet dies during Save & Next | click raises or no API traffic detected; create-mode continues anyway ⚠ | `_save_next` already returns `ok=false` when no network request → record `FAILURE(NETWORK, tab=N)`, heartbeat stops, lease expiry → retry; **must stop advancing tabs on failure** (behavior change, Phase 4) |
| FEMIS accepts save, response lost | listener sees nothing → force-save PUT runs → second save of same data (idempotent PUT) | same as above; force-save makes "unknown outcome" converge to confirmed/failed; `last_completed_tab` only advances on confirmed save |
| Browser crashes | Playwright exception → caught in `main`/`test_bot` → report error (or process dies) | `PROCESSING` + stale lease → takeover; edit-mode probe re-derives portal truth |
| Bot process killed (taskkill) | same as crash | same — lease takeover; no local state to corrupt |
| Bot restarts | re-reads first row; may redo everything | claim skips `COMPLETED`/`PROCESSING` (fresh lease); resumes at `last_completed_tab+1` with probe verification |
| Two workers pick same student | both fill simultaneously → portal record corruption risk | atomic claim: only one gets `PENDING→PROCESSING`; second sees `PROCESSING` (live lease) and skips. SQLite single-writer + `UPDATE…WHERE status='PENDING'` gives correctness without SELECT-then-UPDATE races |
| Student edits data while bot processing | bot never notices (data snapshot taken at read) | `students.updated_at` vs `student_updated_at_seen` mismatch → on completion attempt requeue (`PENDING`) or fail `DATA_STALE`; portal can additionally disable edits while job is `PROCESSING` (display-only warning first) |
| FEMIS session expires mid-run | subsequent goto lands on login; fills fail silently or probe fails | detect login URL/form → `FAILURE(SESSION_EXPIRED)` (non-auto-retry: needs human CAPTCHA) → `FAILED`/manual requeue |
| FEMIS validation rejects a field | errors captured; create-mode may continue ⚠ | `FAILURE(VALIDATION_FIELD)` + `failed_tab` + parsed `failed_field`+message; retry with `_fill_default_required` only for safe defaults; never mark `last_completed_tab` past the failing tab |
| Finish reached but confirmation not detected | returns False → `submit_failed` in ephemeral report | `FAILURE(FINISH_UNCONFIRMED)` with `portal_mode`, screenshot ref; retry is **portal-safe** because reopen is edit-mode (name+CNIC) and Finish is re-checked — but guard against double-Finish: on retry, if portal already shows success/list page → treat as `COMPLETED` |
| Same student retried after partial submission | full re-run from tab 1 (or probe from first invalid) | claim only from `PENDING`; attempts increment; `last_completed_tab` caps redundant work; after `max_attempts` → `FAILED` (terminal until human requeue) |
| Portal 503 (recently observed) | generic fill error | `FAILURE(PORTAL_HTTP_5XX)` — retryable with backoff; batch can pause |

**Idempotency key for the external system:** official FEMIS record is keyed by `b_form` (422 "already been taken" → edit recovery already implemented). That, plus name search, is the natural external dedupe — record the discovered `portal_record_url` in the job so retries go straight to edit.

---

## STEP 7 — API Boundary Recommendation

### 7.1 Can the bot talk to the DB directly?

| | Same host (today's reality) | Different host (portal on PythonAnywhere, bot local — ALREADY true per SESSION_HANDOFF) |
|---|---|---|
| Direct SQLite | ✅ workable **if** bot keeps read-only on `students` and writes only `bot_jobs`, with atomic claim SQL | ❌ **impossible** — bot cannot open the server's SQLite file; this is already the desync documented in the handoff |
| HTTP API | optional convenience | **mandatory** |

**Recommendation:** design the boundary as an API *contract* from day one, implemented in two steps:

- **Phase 3 (same host):** bot still uses `WebFormHandler`-style direct access **restricted to `bot_jobs` + read of `students`**, with atomic claim SQL. Zero new infrastructure; API shapes defined but not built.
- **Phase 6 (cross-host / dashboard):** Student Portal (or a thin bot-side service) exposes the job API; the bot's data access shrinks to one client module. Because the DATABASE remains the storage behind the API, "database is the contract" stays true.

### 7.2 Proposed endpoints (implement later — NOT now)

| Endpoint | Purpose | Semantics |
|---|---|---|
| `GET /api/bot/pending` | queue snapshot | `submitted=1` ∧ (`bot_status='PENDING'` ∨ lease-expired `PROCESSING`); returns student payload + job fields; **read-only** |
| `POST /api/bot/{student_id}/claim` | atomic lease | `UPDATE bot_jobs SET bot_status='PROCESSING', claimed_by=?, lease_expires_at=now+lease, processing_started_at=coalesce(...), attempt_count=attempt_count+1 WHERE student_id=? AND (bot_status='PENDING' OR (bot_status='PROCESSING' AND lease_expires_at<now))` → 409 if no row changed |
| `POST /api/bot/{student_id}/progress` | checkpoint | body: `{current_tab, last_completed_tab, portal_mode, portal_record_url}`; refreshes heartbeat; rejects if lease expired or `students.updated_at` advanced (409 `DATA_STALE`) |
| `POST /api/bot/{student_id}/heartbeat` | liveness | updates `last_heartbeat_at`, extends lease |
| `POST /api/bot/{student_id}/complete` | success | only from `PROCESSING`; sets `COMPLETED`, `completed_at`, `last_completed_tab=7`; **caller must send proof fields** (success heading text / final URL) for the audit trail |
| `POST /api/bot/{student_id}/fail` | failure | body: `{failure_type, failed_tab, failed_field, failure_message}` → `FAILED` or `RETRY_WAIT` per policy |
| `GET /api/bot/stats` | dashboard counts | pending / processing / completed / failed |

Security (when built): bot token header (static secret in `.env`), **not** the student/teacher session; API is write-scoped to `bot_jobs` only; never exposes FEMIS credentials.

### 7.3 Why not let the bot keep writing arbitrary tables?

Because the current failure mode is exactly "two processes, one file, undocumented writers" (`insert_test_record.py`, ad-hoc `ALTER`s, `mark_processed`'s implicit schema change). One writer per table is the rule: **portal→`students`, bot→`bot_jobs`.**

---

## STEP 8 — Separation Boundary

**STUDENT PORTAL owns:**
- `femis-web/**` (app.py, wsgi.py, templates, static, portal_options.json, uploads/)
- the `students` and `teachers` tables — schema, migrations, `submitted`/`locked` semantics
- student/teacher auth, sessions, dashboards, cascading-district APIs
- the 7-tab form behavior exactly as today (until separately scheduled fixes)
- read-only rendering of bot job status (display join only)

**FEMIS BOT owns:**
- `src/**`, `test_bot.py`, `config/settings.yaml`, `config/field_mapping.yaml`
- Playwright lifecycle, FEMIS portal login/CAPTCHA/session (`data/logs/femis_session.json`)
- the `bot_jobs` table — all writes
- bot logs, screenshots, reports under `data/**`
- its own dashboard/control portal (Phase 6) — separate process/port, bot-token auth
- `audit_portal.py` and probe tooling

**SHARED DATABASE owns (the contract):**
- one canonical SQLite file (`femis-web/instance/femis.db` today; path becomes config)
- `students` (portal-writable, bot-readable) + `bot_jobs` (bot-writable, portal-readable)
- documented column semantics: `submitted` = student finished OUR form; `bot_status=COMPLETED` = official FEMIS Finish confirmed
- `students.updated_at` staleness signal

**Hard rules:**
- Bot must not import Flask, templates, `form.js`, or student sessions (already true — keep it).
- Portal must not import `src.*` (true today except `smoke_test.py` — split that test in Phase 1).
- Neither side may ALTER the other's tables; no cross-table writes.
- Portal runs with zero knowledge of whether the bot process is alive (already true; preserve).

---

## STEP 9 — Incremental Migration Plan

Each phase is small, independently verifiable, and reversible. **Nothing below has been executed.**

### Phase 0 — Baseline & freeze
- **Files:** none (process only); create `docs/baseline/` backups outside code paths.
- **DB:** byte-copy both `instance/femis.db` and `femis-web/instance/femis.db` to a backup dir; record row counts + schema hashes.
- **Tests:** run `smoke_test.py` (17/17 baseline), record `git rev-parse HEAD`.
- **Rollback:** n/a (read-only).
- **Untouched:** everything.

### Phase 1 — Canonicalize the database, decouple tests
- **Files:** `docs/femis-separation-audit.md` (this file), new `docs/db-canonical.md` decision note; later: move root `instance/femis.db` to `backup/` (file move, not deletion); split `smoke_test.py` into portal-only test (drop `src.form_filler` import).
- **DB:** none (no schema change; only file hygiene decision: `femis-web/instance/femis.db` = canonical).
- **Tests:** smoke 17/17 (portal part), `browser_smoke_test.py` against local server.
- **Rollback:** restore DB copies from Phase 0 backups; git revert test split.
- **Untouched:** app.py, form.js, form.html, form_filler.py, field_mapping.yaml.

### Phase 2 — Add `bot_jobs` (additive schema only)
- **Files (future):** `femis-web/app.py` (add `BotJob` model + `db.create_all` pickup + `students.updated_at` touch in `api_save_tab`/`api_final_submit`), `docs/bot_jobs.md`.
- **DB:** `CREATE TABLE bot_jobs`; `ALTER TABLE students ADD COLUMN updated_at DATETIME`; backfill `PENDING` jobs for `students.submitted=1`; backfill `updated_at=created_at`.
- **Tests:** new smoke assertions (table exists, backfill count, save-tab touches `updated_at`); full existing smoke must stay 17/17; `browser_smoke_test.py` unaffected.
- **Rollback:** `DROP TABLE bot_jobs`; `updated_at` is additive (harmless if left); backups from Phase 0.
- **Untouched:** form behavior, bot behavior, field_mapping.

### Phase 3 — Bot claims & records job state (bot-side only)
- **Files (future):** new `src/job_store.py` (claim/progress/complete/fail/heartbeat via SQL or API client), modified `test_bot.py` + `src/main.py` (wrap fill/submit with lifecycle), optionally `webform_handler.py` gains `read_claimable()` (replacing dead `read_unprocessed`).
- **DB:** writes only to `bot_jobs`.
- **Tests:** unit tests for claim atomicity (two claims, one wins); integration: run test_bot → assert `COMPLETED` only when `--submit` success; fill-only runs must end `PENDING`/`FAILED`, never `COMPLETED`.
- **Rollback:** revert bot commits; `bot_jobs` rows become inert (portal ignores them).
- **Untouched:** entire `femis-web/`, form.js, field_mapping fill logic.

### Phase 4 — Eligible-only selection + stop-on-failure + accurate success
- **Files:** `src/main.py`, `test_bot.py`, `src/form_filler.py` (minimal: propagate `ok=false` as hard stop per tab; treat only Finish-confirmed as success), `webform_handler.py`.
- **DB:** none new.
- **Tests:** draft student never claimed; failure on tab N leaves `last_completed_tab=N-1`, `failure_type` set; success path requires Finish confirmation.
- **Rollback:** git revert (bot-only).
- **Untouched:** portal.

### Phase 5 — Portal data-loss fixes (separate, explicitly approved — changes form behavior)
Ordered by severity, each with its own test:
1. **Tab 7 persistence:** `/api/final-submit` accepts and stores `data` (or client sends tab-7 via `save-tab` before final-submit). *This changes student-visible behavior only by making data that is already validated actually persist — regression-test with a new smoke case.*
2. `FORM_FIELD_MAP` add: `transport_facility` (new column), `refugee_card_number→refugee_card`, `disability_types[]→disability_types`.
3. Edit-prefill reverseMap fixes (`same_address`, `other_conditions`, `refugee_card_number`).
4. Optional hygiene: server-side validation echoing unknown keys instead of silent drop; auth gaps (Step 10).
- **DB:** `ALTER TABLE students ADD COLUMN transport_facility VARCHAR(50)` (+ backfill: `bus_route IS NOT NULL → 'Institution Bus'`).
- **Tests:** new smoke rows for each formerly-dropped field; full browser smoke; manual 7-tab walkthrough.
- **Rollback:** revert commit; new column additive (values ignored if reverted); keep Phase 0 backups.
- **Untouched:** bot (bot's `transport_facility` source_field suddenly receives real values — verify fallback still safe).

### Phase 6 — Bot dashboard / control portal (bot-owned)
- **Files (future):** new `bot_dashboard.py` (own Flask or static+JSON server, port separate), template(s) under bot; reads `bot_jobs` (+ read-only `students` join); actions: requeue, force-fail, view last error/screenshot.
- **DB:** read `bot_jobs`/`students`; write requeue action to `bot_jobs`.
- **Tests:** counts match SQL; requeue transitions `FAILED→PENDING`.
- **Rollback:** stop the dashboard process; no schema impact.
- **Untouched:** Student Portal UX.

### Phase 7 — Runtime split / API layer
- **Files:** portal gains `/api/bot/*` (Step 7) + bot token config; bot's DB access replaced by client; `render.yaml`/`Procfile` unchanged for portal; bot documented as local/long-running process.
- **DB:** storage stays where the portal runs; bot no longer needs filesystem access to it.
- **Tests:** claim conflicts return 409; stale-lease takeover; end-to-end with portal stopped → portal keeps working (Student Portal independence check), bot stopped → portal keeps working (bot independence check).
- **Rollback:** feature-flag bot back to direct-SQLite when co-hosted.
- **Untouched:** 7-tab workflow throughout.

**Independence acceptance criteria (definition of done):**
1. Portal fully functional with bot process killed (already true — prove with test).
2. Bot processes queued jobs with portal serving reads (or via API) — no shared imports.
3. Zero regression: `smoke_test` + `browser_smoke_test` green; manual 7-tab pass.
4. Every `COMPLETED` job corresponds to a confirmed FEMIS Finish; every failure queryable with tab/field/type.
5. Existing student rows intact (row-count + checksum vs Phase 0 backup).

---

## STEP 10 — RED FLAGS

### Critical — must fix before (or as gate of) separation
1. **Tab 7 data never persisted** (`form.js` final-submit payload drops `data`) — digital-access fields do not exist in the DB; the bot then fills FEMIS tab 7 from NULLs.
2. **Silent field drops:** `transport_facility`, `refugee_card_number`, `disability_types[]` — save reports success while discarding data; server never validates.
3. **No bot state anywhere** — unlimited duplicate processing; no crash recovery; no truthful completion signal; fill-only runs reported as `success`.
4. **Two divergent DB files** (`instance/` vs `femis-web/instance/`) plus documented local↔PythonAnywhere desync — "the contract" currently has multiple copies.
5. **Committed secret:** `.en` (GROQ API key) is tracked in git; `.gitignore` covers `.env` only.

### Dangerous assumptions in the current architecture
6. That `SELECT *` column names will always match `source_field` in a YAML the bot rewrites at runtime (map pollution already places digital fields under tab_4/tab_5).
7. That Save & Next persisted data (portal often issues **no** network request; correctness depends on the `_force_save` PUT hack).
8. That name search + CNIC row text is a reliable portal identity (CNIC filter on portal is broken per handoff; search matches substring rows).
9. That `submitted`/`locked`/`processed` mean the same thing to every reader (they do not).
10. That one canonical DB path exists (`webform_handler` probes 4+ fallback paths).

### Data-loss risks
11. create-mode failed save **continues to the next tab** (values vanish on reload).
12. upload failure leaves `C:\fakepath…` in `disability_certificate`; bot never uploads files to FEMIS at all (silently absent there).
13. `api_save_tab` drops unknown keys with `ok:true`.
14. Edit-prefill reverseMap mismatches (`same_address`, `other_conditions`, `refugee_card`) — user re-saves and can persist blanks over good data.
15. No DB backups; gitignores exclude DBs from version control.

### Duplicate-processing risks
16. No claim/lease; `test_bot` always takes row #1; `main --type webform` reprocesses everyone; `mark_processed` dead.
17. Two headed browsers against one portal session file (`data/logs/femis_session.json`) can invalidate each other's CAPTCHA/session.
18. Portal-side dedupe (b_form 422 → edit) is the *only* thing preventing duplicate FEMIS records.

### State-management risks
19. Bot "success" ≠ Finish (fill-only aliasing in `main.py`; `_wait_for_success` URL heuristic can false-positive on navigation to `/students` list).
20. Success detection has two different criteria (heading vs URL) and a 15s window.
21. `_learn_unmapped_fields` mutates tracked config during production runs (non-reproducible builds, dirty git state).
22. Lease-less `PROCESSING` equivalent does not exist today — any crash = invisible limbo (once bot_jobs exists, lease expiry must be implemented from day one).

### Deployment risks
23. Portal (PythonAnywhere/Render) and bot (local headed Edge) already run in **different environments with unsynced DBs** — separation work must pick the storage home first (Phase 1 decision).
24. `render.yaml`/`Procfile` only deploy the portal; bot has no supervisor, no restart policy, no idempotent queue.
25. Hardcoded portal URLs duplicated in `settings.yaml` and `form_filler.py` (`LIST_URL`/`CREATE_URL`).
26. `instance/` directory creation + silent `except: pass` migration can mask schema drift.
27. Auth holes on portal API (`/api/final-submit`, `/api/upload-file`, `/students`, `/students/<id>/json` unauthenticated; `save-tab` does not verify the student_id belongs to the session; teacher class-check expression has a precedence bug) — becomes more serious once a bot API is added on the same app.

### Things we must NOT change yet
28. `form.html` / `form.js` 7-tab workflow and validation lists (until Phase 5, explicitly approved).
29. `form_filler.py` fill/save/finish mechanics (Phase 3–4 touch only orchestration/state, not selectors).
30. `field_mapping.yaml` contents (no manual "cleanup" — the bot's learner depends on current shape).
31. Existing `students` rows and column names; `submitted`/`locked` semantics.
32. No new frameworks, hosts, or package changes in any upcoming phase without explicit approval.
33. Do not delete the stale root `instance/femis.db` — back it up first (it may contain rows 1,2,4,5 absent from the live file).

---

## Verification performed (read-only)

- `git status` clean before and after; no application file modified by this audit.
- `smoke_test.py` → **17/17 PASS** (self-cleaning test row).
- Schema dumps of both DB files; row inventories compared.
- 215 leaf configs in `field_mapping.yaml` parsed and cross-checked against the 139-column model and 131 HTML field names.
- All entry points, routes, templates, env files, deploy configs, and test scripts read.

---
---

# Executive Summary (A–J)

## A. Current architecture
Two loosely coupled modules sharing one SQLite file: a Flask Student Portal (`femis-web/`, 7-tab form + teacher lock, session auth, no bot dependency) and a Playwright FEMIS Bot (`src/` + `test_bot.py`, headed Edge, portal CAPTCHA login, yaml-driven fill, no Flask dependency). Coupling = DB path + column names + alias tables duplicated in 3 places. No bot dashboard exists; bot progress/errors live only in logs/JSON reports. Two divergent local DBs + an unsynced remote copy.

## B. Complete 7-tab data mapping
131 HTML fields mapped end-to-end (full tables in Step 2). Result: **4 confirmed persistence bugs** — `transport_facility`, `refugee_card_number`, `disability_types[]` silently dropped by `api_save_tab`, and **all of Tab 7 never sent** (final-submit payload omits `data`). 3 orphan columns (`parent_name`, `years_primary`, `major_disability`) + legacy `transport` column. Edit-prefill reverseMap broken for `same_address`/`other_conditions`/`refugee_card`. Bot-side: alias-form `source_field`s read NULL; `address`/`present_address_other`/`guardian_profession_other` never filled by bot.

## C. Current bot workflow
Select (first row / explicit id / all rows — no filters) → read SQLite once → portal session reuse or CAPTCHA login → `open_form` (name+CNIC → edit or create) → per tab: click nav → yaml fill → Save & Next with multi-signal ok-check + force-save PUT hack → 1 retry (edit mode only) but **continues past failures** → force-save → Finish → 15s success wait → ephemeral report. Progress: recomputed via probe, never stored. Errors: logs/screenshots only. No claim/lock/heartbeat; duplicates fully possible; fill-only runs labeled `success`.

## D. Proposed database contract
Keep `students` portal-owned (add only `updated_at`). New bot-owned `bot_jobs` table (1:1, UNIQUE student_id): `bot_status, current_tab, last_completed_tab, failed_tab, failed_field, failure_type, failure_message, attempt_count, max_attempts, processing_started_at, last_heartbeat_at, last_attempt_at, completed_at, claimed_by, lease_expires_at, portal_mode, portal_record_url, student_updated_at_seen, last_success_at, notes`. Same SQLite file = contract; one writer per table.

## E. Proposed state machine
Student: `DRAFT (submitted=0)` → `SUBMITTED (submitted=1)` → *(optional future* `TEACHER_APPROVED`*; default: eligibility = submitted)*, with parallel `locked` flag unchanged. Bot: `PENDING → PROCESSING (atomic claim + lease + heartbeat + tab checkpoints) → COMPLETED (only on confirmed FEMIS Finish)` or `FAILED (typed, with tab/field/message; retryable to PENDING until max_attempts)`. Stale lease ⇒ auto-requeue; `students.updated_at` drift ⇒ requeue/stale flag. Statuses never overlap vocabularies.

## F. Failure/recovery model
Recovery anchors: job row (status/tab/attempt/lease) + student row + `portal_mode`/`portal_record_url` + seen `updated_at`. Crash mid-tab → lease takeover → edit-mode probe resumes at first unsaved tab. Unknown save outcome → force-save idempotent PUT + no network ⇒ failure. Finish unconfirmed → typed failure; retry safe via portal b_form dedupe; already-submitted page ⇒ flip COMPLETED. Session expiry/validation/network/503 → typed failures, selective retry. Full scenario table in Step 6.

## G. API boundary recommendation
API-first contract, two-phase: Phase 3 same-host direct SQL confined to `bot_jobs` with atomic claim (no new infra); Phase 6/7 real endpoints `GET /api/bot/pending`, `POST .../claim|progress|heartbeat|complete|fail`, `GET /api/bot/stats` served by the portal with bot-token auth — required once bot and portal live on different machines (already the PythonAnywhere/local reality). DB remains storage behind the API.

## H. Incremental migration plan
0 Baseline/backup → 1 Canonical-DB decision + split coupled test → 2 Additive `bot_jobs` + `updated_at` → 3 Bot claims/state (bot-only) → 4 Eligible-only selection, stop-on-failure, truthful success → 5 Approved portal data-loss fixes (tab 7, three field maps, prefill) → 6 Bot dashboard → 7 Runtime split/API. Each phase: named files, additive DB only, explicit tests, git/backup rollback, and a "untouched" list. Definition of done in Step 9.

## I. Critical risks
Top five: (1) Tab 7 data never saved; (2) three silently dropped fields with `ok:true`; (3) zero bot state ⇒ duplicate/false-success; (4) multiple divergent DB copies; (5) committed `.en` secret. Plus: create-mode continues past failed saves, runtime-mutated field mapping, false-success URL heuristic, auth holes on portal APIs, no backups, dead `mark_processed`, misleading `success` semantics.

## J. Exact next command after you review this audit
```
Phase 1 — canonicalize and baseline: back up instance/femis.db and femis-web/instance/femis.db to backup/2026-09-24/, write docs/db-canonical.md naming femis-web/instance/femis.db as the single canonical contract DB (root copy archived, not deleted), and split smoke_test.py so the portal test no longer imports src.*. No schema or behavior changes. Then re-run smoke_test.py to confirm 17/17.
```
