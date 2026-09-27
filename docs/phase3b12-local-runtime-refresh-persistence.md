# Phase 3B.12 — Local Runtime Refresh & Persistence Re-verification

**Date:** 2026-09-26
**Status:** COMPLETE — STOP
**Scope rule honored:** diagnostics and verification only. No fixes to `required`,
JS validation, server validation, labels, field mappings, selectors, grouping,
authorization, admin/dashboard, or Ayat-completion. **No application file was
modified. Nothing staged. Nothing committed.**

---

## 0. Outcome Summary

| Question | Answer |
|---|---|
| Was the stale server process (3B.11 RC1) stopped and replaced? | **Yes** — PID 15996 (started 2026-09-23 10:20:50) stopped; fresh PID **27312** (started 2026-09-26 23:15:39) serving the current working tree on `:5000` |
| Did the stale-process defects (3B.11 RC2) clear? | **Yes** — live-code checks 19/19: job blueprint registered (404→401/405), student JSON 139→**141 keys**, `transport` + `updated_at` readable, aliases present, `form.html`/`form.js` byte-current |
| Does save→reload persistence work end-to-end? | **Yes** at the data layer — API probe, teacher UI path, and student UI path all round-trip through DB + JSON |
| Does the form re-render saved values after reload? | **Partially** — 16/19 checked fields render; **3 gaps remain in current `form.js`** (F1–F3 below), two of them causing **silent data loss on save** and one **blocking save** |
| Canonical data intact? | **Yes** — 9/9 before/after checks: all 6 student row hashes + 3 teacher row hashes byte-identical, Ayat `updated_at` unchanged, no probe leftovers |
| Regression? | **440/440** across all 13 suites (identical to 3B.11 baselines) |
| Repo touched? | **No** — HEAD still `6871f81`, 0 staged, `app.py`/`form.js`/`form.html` mtimes unchanged |

**Verdict: PASS with 3 open product findings (F1–F3), diagnosed and impact-probed
but NOT fixed in this phase per the STOP rules.**

---

## 1. Step 1–2: STOP FIRST, then Runtime Refresh

### Pre-refresh (unchanged since 3B.11)

| Item | Value |
|---|---|
| Listening PID on `:5000` | **15996** (= 3B.11 identified stale PID) |
| Started | 2026-09-23 10:20:50 |
| Command line | `"C:\Users\faiza\AppData\Local\Programs\Python\Python312\python.exe" femis-web/app.py` |
| Known defects | drops `transport_facility`/`refugee_card_number`/`disability_types[]`; model lacks `transport`/`updated_at`; `/api/jobs` 404 |
| App files | untouched (`app.py` mtime 09/26 22:04:32, `form.js` 09/24 16:50:54, `form.html` 09/24 19:23:25) |
| Port logic | `app.py:894` `port = int(os.environ.get("PORT", 5000))`; `app.py:895` `app.run(debug=False, host="0.0.0.0", port=port)` → no reloader |
| DB before-snapshot | `p3b12_db_before.json`, file sha256 `d13e94fee5accb5b…`, students 6 `[3,4,6,8,9,10]`, bot_jobs 0, teachers 3, Ayat id6 `updated_at=2026-09-26 13:42:48.243900` |

### Refresh executed

- PID 15996 **stopped** (verified `GONE` afterwards).
- Fresh process started from the current working tree with stdout/stderr redirected
  to `p3b12_server_out.log` / `p3b12_server_err.log`.

### Post-refresh

| Item | Value |
|---|---|
| New PID | **27312** |
| Started | 2026-09-26 23:15:39 |
| Command line | `"…\python.exe" femis-web\app.py` |
| Startup log | `Serving Flask app 'app'` / `Debug mode: off` / `Running on all addresses (0.0.0.0)` / `http://127.0.0.1:5000` |
| Readiness | `GET /login` → **HTTP 200** |
| Still running at close of phase | Yes (PID 27312, HTTP 200) |

---

## 2. Step 3: Live-Code Verification — 19/19 PASS

Script: `p3b12_liveverify.py`.

| # | Check | Pre-refresh (3B.11) | Post-refresh |
|---|---|---|---|
| 1 | `GET /api/jobs` | **404** (blueprint missing) | **401** `{"error":"Authentication required.","error_code":"authentication_required"}` |
| 2 | `/api/jobs` fail-closed auth | n/a | 401 without token |
| 3 | `POST /api/jobs/claim` | (404) | **405** (route exists, method-gated) |
| 4 | `GET /students/6/json` | 200, **139 keys** | 200, **141 keys** (model == working-tree schema) |
| 5 | JSON exposes `updated_at` | absent | `'Sat, 26 Sep 2026 13:42:48 GMT'` |
| 6 | JSON exposes `transport` | **absent (dropped)** | `'Institution Bus'` |
| 7 | 3B-expected columns present | `transport`, `updated_at`, `guardian_income`, `sub_sector_id`, `primary_education_completion_years`, `digital_device_at_home` all present | — |
| 8–10 | `FORM_FIELD_MAP` aliases | `transport_facility→transport`, `refugee_card_number→refugee_card`, `disability_types[]→disability_types` present (`app.py:415-428`) | — |
| 11 | served `/static/form.js` | byte-identical to working tree, sha256 `1265b82650cc21a1…` | same |
| 12 | `Cache-Control` | `no-cache` | same |
| 13–15 | served `/form/6` (student session) | 8/8 working-tree markers | 8/8 markers + `student_id` hidden control + disk body sample present |

**Conclusion:** RC1 (stale process) and RC2 (stale-model field dropping) are
**cleared by the refresh**. The server now executes the current working tree.

---

## 3. Step 4: Persistence Probe (API) + Render Check (Browser)

### 3.1 API-level probe — 32/34 (`p3b12_persist_probe.py`)

Dedicated temp row (id 11, deleted after; never Ayat id 6/9):

| Scenario | Result |
|---|---|
| Create with populated fields (`father_name`, `transport='None'`, `digital_device_type='Mobile Phone'`, `sub_sector_id='I-14/3'`) + empty fields (`guardian_name`, `bus_route`, `disability_types`) | DB direct read: populated written, empty stays empty ✅ |
| Edit already-populated field → `P3B12-FATHER-V2` | ✅ |
| Edit previously-empty field → `P3B12-GUARDIAN` | ✅ (empty→filled) |
| Change `transport` → `Institution Bus`; fill conditional `bus_route='TARNOL'` | ✅ |
| Multi-value change → `Mobile Phone,Laptop`; multi-value empty→filled → `Visual,Speech` | ✅ |
| Untouched siblings (`sub_sector_id`, `date_of_admission`) stable | ✅ |
| `updated_at` bumped by save | ✅ |
| Reload JSON re-reads all saved values + `updated_at` | ✅ (8/8 fields) |
| Probe deleted; `students` restored to 6 `[3,4,6,8,9,10]` | ✅ |

The 2 failing checks were the harness's static-HTML attempt to prove
`sub_sector_id` renders (its `<option>`s are JS-populated) — escalated to the
real-browser check below, which produced the authoritative render results.

### 3.2 Real-browser render check (Chromium/Playwright, Ayat id 6, read-only)

Field-level DOM vs DB after reload (app's own pre-fill, unmodified):

| Rendered ✅ (12 non-empty + 4 empty-ok) | Not rendered ❌ (3) |
|---|---|
| `name`, `father_name`, `gender`, `class_id`, `section_id`, `house`, `street`, `date_of_admission`, `sector_id`, `transport_facility`, `is_bform_available`, `b_form` | `sub_sector_id`: DB `I-14/3` → DOM `''` |
| empty-ok: `guardian_name`, `guardian_income`, `disability_types[]`, `domicile_district_id` | `birth_district_id`: DB `Faisalabad` → DOM `''` |
| | `digital_device_type[]`: DB `Mobile Phone,Laptop` → DOM unchecked |

Browser suite total incl. paths below: **42/43** (single FAIL = the 3 gaps above).

---

## 4. Findings F1–F3 — Remaining Root Cause AFTER Refresh

All three live in the **current working-tree `form.js`** (byte-identical copy is
served — see §2), so they are **not stale-server artifacts**. Root mechanism:
the pre-fill runs **once, synchronously, with no retry** (`form.js:846-871`).

### F1 — Sub-sector select: display-empty + silent data loss on tab-1 save

- **Mechanism:** pre-fill sets `sector_id` and dispatches `change`
  (`form.js:854-856`) → the cascade fetch (`form.js:131-149) resolves *after*
  pre-fill already attempted `sub_sector_id` (options not yet loaded → assignment
  silently fails). The `data-pending-value` rescue exists (`form.js:134,145-147`)
  but is set **only** by the same-address copy (`form.js:261`), never by pre-fill.
- **Visibility wrinkle:** `address_type` change handler re-hides
  `#sub_sector_group` on **every** change (`form.js:198`); only the sector cascade
  shows it (`form.js:149`). Save collects the **active tab only** and skips
  invisible controls (`form.js:671,675`).
- **Impact probe** (`p3b12_overwrite_probe.py`, 15/15):
  - group **visible** (normal state when `address_type='Sector'` + cascade ran):
    pre-save DOM `''` → payload `sub_sector_id: ''` → DB `I-14/3` → **`''`**
    — **silent data loss on every tab-1 save**.
  - group **hidden** (e.g. after an `address_type` change re-hides it): key absent
    from payload → stored value survives (no loss, still display-empty).

### F2 — Province→District cascade: display-empty **blocks** tab-1 save

- **Mechanism:** `loadDistricts` (`form.js:83-99`) repopulates the district
  `<select>` after fetch and has **no pending-value mechanism at all**; pre-fill's
  district value (set while the select is mid-"Loading…") is lost.
- **Impact probe** (`p3b12_block_probe.py`, 12/12) — all other tab-1 mandatory
  fields filled, stored district `Faisalabad`:
  1. On open: DOM `''` ✅ (race lost)
  2. After district options load: **still** `''` ✅ (no pending-value)
  3. Click Save → **0 `save-tab` requests fired** — `validateTab` blocks
     (`form.js:663` + `mandatoryByTab[0]` includes `birth_district_id`,
     `form.js:546`) with alert
     `"Please fill the following mandatory fields: • District of Birth"` ✅
  4. DB untouched by the blocked save ✅
  5. Recovery: user re-selects district → save proceeds → persisted ✅
- Same code path (`setupSelectCascading`) serves `domicile_district_id` and
  `father_domicile_district_id`; Ayat's `domicile_district_id` is empty in DB so
  only the birth field was impact-probed.

### F3 — Checkbox arrays never re-rendered + silent data loss on tab-7 save

- **Mechanism:** the pre-fill input branch skips checkboxes entirely
  (`form.js:866-688`: `if (input.type !== "radio" && input.type !== "checkbox") input.value = val`)
  — it never checks boxes from the comma-joined DB value.
- **Impact probe** (`p3b12_overwrite_probe.py`, P2):
  - Save from tab-7 (Digital Access, final-submit endpoint): unchecked
    `digital_device_type[]` boxes still create the payload key as `''`
    (`form.js:678-692` creates `arrayChecks[name]` before the `checked` test) →
    payload `digital_device_type[]: ''` (5 keys) → DB `Mobile Phone,Laptop` →
    **`''`** — **silent data loss on every tab-7 save.**
  - Reload afterwards shows the emptied state (consistent, but the data is gone).

### Related save-path semantics observed (documented, not defects claimed here)

- Save collects **only the active tab** (`form.js:671`) + hidden `student_id`
  (`form.js:696-698`); each tab must be saved separately.
- `validateTab` (`form.js:573-656`) gates every save; saved records whose
  re-render fails for a *mandatory* field cannot be re-saved from that tab (F2).
- **Unchecked radios are omitted from the payload** (`form.js:676-677`): a
  `NULL` radio column can **never be restored through the form** — the value,
  once written, persists until overwritten by another checked radio. This is why
  the student path used a temp row instead of editing sparse id 10 (§6).

---

## 5. Step 5: Teacher Path — PASS

Session minted with the app's own key (`app.py:14`
`SECRET_KEY = os.environ.get("SECRET_KEY", "femis-web-dev-key-change-in-prod")`),
payload `{role: teacher, user_name: "Mrs. Ahmed", teacher_id: 1, teacher_class: "5",
teacher_section: "A"}` (row read from DB), signed via Flask's
`SecureCookieSessionInterface` and set as the `session` cookie.

Flow on temp row (class 5/A, roll `P3BT`, id 11 — created then deleted):

| Step | Result |
|---|---|
| `GET /form/11` with teacher session | 200, no login redirect ✅ |
| Tab-2: 17 mandatory/conditional fields filled (`form.js:547-554` + mother income `form.js:634-639`; `is_orphan='0'` to satisfy `form.js:641-648`) + edits `father_name`, `guardian_name` | ✅ |
| Save & Next → `POST /api/save-tab` | 200 `{"ok":true}` ✅ |
| Auto-advance to tab-3 | ✅ |
| Tab-3: 13 mandatory fields (`form.js:555-560`) incl. `transport_facility='Institution Bus'`, `bus_route` collected (group shown by `form.js:414`), `scholarship/cocurricular='0'` to avoid conditionals; `class_id` kept `'5'` (teacher class/section check `app.py:486-491` passes) | ✅ |
| Save #2 → `save-tab` | 200 ✅ |
| **DB direct read:** `father_name='TCH-EDITED-FATHER'`, `guardian_name='TCH-GUARDIAN'`, `transport='Institution Bus'` | ✅ |
| **Reload renders** all three (radio included) | ✅ |
| JSON endpoint shows saved values | ✅ |
| Probe deleted | ✅ (left=0) |

---

## 6. Step 6: Student Path — PASS

### id 10 (`Portal Verify Student`) — read-only, byte-identical

- Own-session login (name/class/section/roll exact match) → `/form/10` 200 →
  JSON readable ✅.
- **Not edited in place**: id 10 is a sparse row (10 non-empty columns; all radio
  columns `NULL`). Because unchecked radios are omitted from the payload
  (`form.js:676-677`), a `NULL` radio cannot be restored through the form — any
  in-place UI edit would permanently alter the row. Verified **byte-identical**
  before/after the whole phase (all 141 columns) ✅.

### Student edit round-trip — temp row (class 9/A, roll `P3BS`, deleted after)

| Step | Result |
|---|---|
| Student login (exact match — no row auto-created) | ✅ |
| `GET /form/<temp>` own record; pre-fill renders fixture value `STU-ORIGINAL-FATHER` on open | ✅ |
| Tab-2 fill + edit (`father_name`, `guardian_name`) → Save & Next | 200 ✅ |
| **DB:** `father_name='S-EDITED-FATHER'`, `guardian_name='S-EDITED-GUARDIAN'` (empty→filled) | ✅ |
| `id` + `created_at` unchanged; **only `updated_at` bumped** | ✅ |
| Reload renders both edited values | ✅ |
| JSON shows saved values | ✅ |
| Probe deleted; 6 canonical rows remain | ✅ |

---

## 7. Step 8: DB Before/After — 9/9 PASS

`p3b12_db_before.json` → `p3b12_db_after.json` (`p3b12_db_compare.py`), re-run
**after all probes and regression suites**:

| Check | Result |
|---|---|
| `PRAGMA integrity_check` | `ok` |
| students count / ids | `6` / `[3,4,6,8,9,10]` identical |
| bot_jobs / teachers | `0` / `3` |
| 6 student row hashes (ALL columns) | identical (Ayat id 6 & 9, id 3/4/8/10 untouched) |
| 3 teacher row hashes | identical |
| Ayat id 6 `updated_at` | `2026-09-26 13:42:48.243900` unchanged |
| `P3B12%` probe leftovers | none |
| file sha256 | `d13e94fee5accb5b…` → `5e322e201cfad7c2…` (bytes differ only from probe insert/delete cycles; **row contents identical**) |

---

## 8. Step 9: Regression — 440/440 across 13 Suites (individually, fresh processes)

| Suite | Result | Baseline (3B.11) |
|---|---|---|
| `test_bot_job_schema.py` | 62/62 | 62/62 |
| `test_bot_job_api.py` | 124/124 | 124/124 |
| `test_data_integrity.py` | 24/24 | 24/24 |
| `test_submission_status.py` | 12/12 | 12/12 |
| `test_bot_job_api_isolation.py` | 13/13 | 13/13 |
| `smoke_test.py` | 14/14 | 14/14 |
| `smoke_test_bot.py` | 3/3 | 3/3 |
| `test_bot_job_bot_integration.py` | 54/54 | 54/54 |
| `test_students_null_created_at.py` | 11/11 | 11/11 |
| `test_created_at_creation_paths.py` | 11/11 | 11/11 |
| `test_created_at_not_null_integrity.py` | 26/26 | 26/26 |
| `test_persistence_roundtrip.py` | 29/29 | 29/29 |
| `test_mandatory_field_reconciliation.py` | 57/57 | 57/57 |
| **Total** | **440/440** | **440/440** |

(`test_bot.py` exists but is not part of the 13-suite 3B.11 baseline — excluded
to keep this phase's regression identical to the prior baseline. All suites exit 0.)

---

## 9. Files Changed / Untouched

**Repo: nothing created, modified, or deleted by this phase.**

- `git status`: same pre-existing uncommitted working set as before this phase
  (29 entries incl. untracked `docs/` and test files); **0 staged**; HEAD
  `6871f81` unchanged.
- `femis-web/app.py` mtime 09/26 22:04:32, `femis-web/static/form.js`
  09/24 16:50:54, `femis-web/templates/form.html` 09/24 19:23:25 — all untouched.
- This document (`docs/phase3b12-local-runtime-refresh-persistence.md`) is the
  only new repo path (under the already-untracked `docs/`).

**Verification artifacts (outside the repo, `%LOCALAPPDATA%\Temp\opencode\`):**

`p3b12_db_before.json`, `p3b12_db_after.json`, `p3b12_db_snapshot.py`,
`p3b12_db_compare.py`, `p3b12_liveverify.py`, `p3b12_persist_probe.py`,
`p3b12_field_tabs.py`, `p3b12_browser.py`, `p3b12_overwrite_probe.py`,
`p3b12_block_probe.py`, `p3b12_server_out.log`, `p3b12_server_err.log`,
`p3b12_reg_<suite>.log` (13).

**Runtime left:** fresh server PID 27312 on `:5000` (started 2026-09-26 23:15:39).

---

## 10. Remaining Root Causes (carried forward — NOT fixed in this phase)

| ID | Defect | Impact (proven) | Where |
|---|---|---|---|
| **F1** | Sub-sector value lost by pre-fill race; `data-pending-value` never set by pre-fill | Display empty **+ silent overwrite of stored `sub_sector_id` on tab-1 save** (when group visible) | `form.js:846-871`, `131-154`, `198`, `671`, `675` |
| **F2** | District cascade has no pending-value mechanism | Stored district renders empty → **tab-1 save blocked** by `validateTab` until re-selection | `form.js:83-99`, `546`, `573-656`, `663` |
| **F3** | Pre-fill input branch skips checkboxes | Checkbox arrays never re-render **+ silent overwrite on tab-7 save** | `form.js:866-888`, `678-692` |
| F4 (semantic) | Unchecked radios omitted from payload | `NULL` radio columns unrestorable through the form (drove student-path design, §6) | `form.js:676-677` |
| — | 3B.11 known gaps unchanged | 4 mandatory-field reconciliation items, zero server-side validation, HTML-only `required` ×4 | `test_mandatory_field_reconciliation.py` |

**Recommended next-session anchor (single task, needs approval):** a dedicated
fix phase for **F1–F3 pre-fill re-render** (restore values after cascades +
check checkbox arrays from saved values), with the F1/F2/F3 probes in
`p3b12_overwrite_probe.py` / `p3b12_block_probe.py` converted into permanent
regression tests. The separate commit decision from `phase3b10-1` remains open
and unaffected by this phase.

---

## 11. STOP REPORT

1. **Stopped & refreshed:** stale PID 15996 (2026-09-23 10:20:50) → stopped;
   fresh PID **27312** (2026-09-26 23:15:39) serving current working tree, HTTP 200.
2. **Live-code verified:** 19/19 (jobs blueprint 404→401/405; JSON 139→141 keys;
   `transport`/`updated_at` readable; aliases present; `form.html`/`form.js` current).
3. **Persistence verified (API):** 32/34 — create, populated-edit, empty→filled,
   multi-value, transport, conditional, siblings-stable, `updated_at` bump, JSON
   re-read all pass; probe deleted.
4. **Render verified (browser):** 16/19 fields re-render; **F1/F2/F3 remain**.
5. **Teacher path:** PASS (minted session → tab-2 + tab-3 real UI saves → DB +
   reload + JSON → deleted).
6. **Student path:** PASS (id 10 read-only byte-identical; temp student edit →
   DB + reload + JSON → deleted; radio-NULL limitation documented).
7. **Data-loss impacts proven:** P1 tab-1 save wipes `sub_sector_id` (15/15);
   P2 tab-7 save wipes `digital_device_type[]`; F2 block probe 12/12
   (`District of Birth` alert, no request, DB untouched, recovery works).
8. **DB before/after:** 9/9 — every canonical row hash identical, integrity ok,
   no leftovers, Ayat untouched.
9. **Regression:** 440/440 across 13 suites (matches 3B.11 baselines exactly).
10. **Repo:** 0 files modified by this phase, 0 staged, HEAD `6871f81`, no commit.
11. **No fixes applied** to required/JS/server validation, labels, mappings,
    selectors, grouping, authorization, admin/dashboard, or Ayat completion —
    per phase rules; F1–F3 documented with file:line citations only.
12. **Open decisions for the user:** (a) approve a fix phase for F1–F3
    (prefill re-render), or (b) proceed with the commit sequence from
    `phase3b10-1-commit-readiness-audit.md`.
13. **Next session anchor:** one task only — F1–F3 fix phase (or the commit, if
    chosen); do not start F4/3B.11-gap work in the same session.

**STOP — awaiting instructions.**
