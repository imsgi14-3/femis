# Phase 3B.13 — Prefill Re-render Fix (F1–F3, +F5)

**Date:** 2026-09-27
**Status:** COMPLETE — STOP
**Scope rule honored:** user-approved fix of the three 3B.12 prefill/cascade
re-render defects (F1–F3) in `femis-web/static/form.js` only, verified by a new
permanent regression test **before any commit**. A fourth defect (F5) was
discovered during verification and explicitly approved by the user mid-phase.
**No changes** to `validateTab`/`mandatoryByTab`, labels, selectors,
grouping/visibility logic, `required` attributes, server code (`app.py`),
authorization, admin/dashboard, or Ayat completion. **Nothing staged. Nothing
committed** — commit remains gated on the 3B.10.1 manifest approval.

---

## 0. Outcome Summary

| Question | Answer |
|---|---|
| F1 — sub-sector silent wipe on tab-1 save? | **FIXED** — prefill now stashes `data-pending-value` when a select's value can't stick yet (`form.js:860-862`); the sector cascade applies/removes it and shows `#sub_sector_group` (existing rescue, `form.js:131-149`) |
| F2 — birth district never re-renders → tab-1 save blocked? | **FIXED** — `loadDistricts` now reads/applies/removes `data-pending-value` after populating options (`form.js:94-105`); benefits all 3 district cascades (`form.js:118-120`) |
| F3 — checkbox arrays never re-checked → silent wipe on tab-7 save? | **FIXED** — new prefill branch handles `name="…[]"` checkbox groups: checks wanted values, dispatches change (`form.js:871-879`) |
| F5 (new, discovered in this phase) — mother language never re-renders → tab-1 save blocked? | **FIXED with user approval** — `reverseMap` entry was `"language_id": "mother_language"` (an element **ID**, not a control name); corrected to identity `"language_id": "language_id"` (`form.js:817`) |
| Permanent regression test added? | **Yes** — `test_prefill_rerender.py`, **30/30 checks passed** (self-contained: fixture, Playwright, DB assertions, probe cleanup) |
| Prior browser suite still green / now complete? | **43/43** (`p3b12_browser.py`; was 42/43 pre-fix — the single FAIL was the F1–F3 render gaps) |
| Regression suites? | **440/440** across all 13 baseline suites (identical to 3B.12 baselines) |
| Canonical data intact? | **Yes** — final `p3b12_db_compare.py` **9/9**: all 6 student row hashes + 3 teacher hashes byte-identical, Ayat `updated_at` unchanged, no probe leftovers |
| Server restart needed? | **No** — static `form.js` served with `Cache-Control: no-cache`; served sha256 verified equal to disk sha256 after every edit (PID 27312 unchanged) |
| Repo touched? | `M femis-web/static/form.js`, `?? test_prefill_rerender.py`, `?? docs/` (this doc). Pre-existing uncommitted body unchanged; **0 staged, HEAD still `6871f81`** |

**Verdict: PASS — F1, F2, F3, F5 fixed and proven by permanent tests; regression
and canonical data clean; commit deliberately deferred.**

---

## 1. Root Causes & Fixes (all in `femis-web/static/form.js`)

### F1 — sub-sector race → silent wipe (was: impact-proven P1)

- **Cause:** prefill sets `sector_id` + change (`form.js:851+`), but the
  sector→sub-sector cascade (`form.js:131-149`) resolves *after* prefill
  attempted `sub_sector_id`. Prefill never recorded a pending value, and the
  `address_type` change handler always re-hides `#sub_sector_group`
  (`form.html:149` starts `display:none`). Result: group hidden **or**
  `sub_sector_id` empty at save → payload `''` → silent wipe (invisible
  controls are skipped by collection, `form.js:680`).
- **Fix:** prefill's select branch now stashes `data-pending-value` when
  `String(sel.value) !== String(val)` before dispatching change
  (`form.js:860-862`). The existing cascade rescue reads/applies/removes it
  and shows the group (`form.js:134, 145-149`).
- **Order-independent:** stash happens during the synchronous prefill loop;
  cascades apply pending whenever their fetch resolves.

### F2 — district race → tab-1 save blocked

- **Cause:** `loadDistricts` repopulated options with no pending-value
  mechanism; the stored district (e.g. `Faisalabad`) rendered `''`; district
  is mandatory on tab-1 (`form.js:551`) → `validateTab` alert
  "District of Birth" → no save-tab request (proven in 3B.12
  `p3b12_block_probe.py` 12/12).
- **Fix:** `loadDistricts` success handler captures `data-pending-value`
  before repopulating, applies it after populating, removes the attribute
  (`form.js:94-105`). Covers all three cascade instances:
  birth, domicile, father-domicile (`form.js:118-120`).

### F3 — checkbox arrays never re-checked → silent wipe on tab-7 save

- **Cause:** prefill's input branch set only `.value` and explicitly skipped
  checkbox/radio; checkbox groups `digital_device_type[]` / `disability_types[]`
  were never re-checked. Collection builds the payload key from checked boxes —
  with all boxes unchecked the key is still emitted as `''`
  (`form.js:683-697`) → silent wipe.
- **Fix:** new prefill branch before the input fallback: for `formName`
  ending in `[]`, split the stored comma list, check matching boxes, dispatch
  change on the first (`form.js:871-879`).

### F5 — mother language never re-renders → tab-1 save blocked (new in 3B.13)

- **Discovered by** the new permanent test: its second tab-1 save (after
  reload) fired no request; diagnostic captured the validation dialog
  `Please fill the following mandatory fields: … Mother Language` and
  `language_id == ""` after reload while DB had `Urdu`.
- **Cause:** `reverseMap["language_id"] = "mother_language"` — but
  `form.html:293` control is `select[name="language_id"]` (its **id** is
  `mother_language`, matching the FEMIS official radio naming). Prefill looked
  for `name="mother_language"` → no control → skip. `language_id` is mandatory
  on tab-1 (`form.js:551`) → save blocked until the user re-picks.
  Persistence itself was fine (API round-trip verified: `language_id='Urdu'`).
- **Fix:** `form.js:817` → identity mapping `"language_id": "language_id"`
  (consistent with neighbouring identity entries). `reverseMap` is referenced
  only by prefill (`form.js:854`) — change is isolated to prefill render.
- **Approval:** presented to the user as a scope question mid-phase; user
  chose **"Include F5 one-line fix"**.
- **Full audit:** all **70** `reverseMap` entries checked against control
  names in `form.html`; only F5 was impactful. Two harmless no-ops remain
  (documented, untouched): `roll_no` (no control — roll is not editable in
  the form, not mandatory) and `major_disability_text` (no such control in
  our form; not referenced by validation).

---

## 2. Verification Evidence

### 2.1 Serve freshness

After each `form.js` edit: `sha256(disk) == sha256(GET /static/form.js)`
(final: `72ac20b478860024…`) — no server restart required
(`Cache-Control: no-cache`, PID 27312).

### 2.2 New permanent regression test — `test_prefill_rerender.py` (30/30)

Self-contained (fixture row via `/api/save-tab`, student session via
`/login`, Playwright + Chromium, direct SQLite assertions, fixture deleted in
`finally`, canonical-state check). Covers:

| # | Check group | Result |
|---|---|---|
| 1 | Fixture row created (province `1`, district `Faisalabad`, address `Sector`, sector `34`, sub-sector `I-14/3`, devices `Mobile Phone,Laptop`, disability `Visual,Hearing`) | PASS |
| 2 | **F1/F2/F3 re-render on open:** district, sub-sector, both checkbox arrays | PASS |
| 3 | **F1 visibility:** `#sub_sector_group` has `offsetParent` (cascade finished, group shown — the exact wipe precondition) | PASS |
| 4 | Tab-1 fill + save: save-tab fires `ok:true`, **zero validation dialogs** (F2 block cleared) | PASS |
| 5 | After save: district `Faisalabad` + sub-sector `I-14/3` preserved in DB (**no silent wipe**), devices untouched (control) | PASS |
| 6 | Tab-7 fill + save (final-submit, HTTP 200, no dialogs): `digital_device_type` **preserved** (F3 no-loss); disability/sub-sector/district controls intact | PASS |
| 7 | Reload after both saves: all three values re-render again | PASS |
| 8 | **Intentional clear preserved:** clear sub-sector (tab-1 save) → DB `''`; uncheck all 5 device boxes (tab-7 save) → DB `''` | PASS |
| 9 | Probe deleted; canonical 6 rows `[3,4,6,8,9,10]` remain | PASS |

```
30/30 checks passed
```

(Test-side fixture bug found during the phase and corrected: it originally used
disability value `'Speech'`, which is not one of the six options in
`portal_options.json` — switched to `'Hearing'`.)

### 2.3 Prior browser suite — `p3b12_browser.py`

**43/43** (pre-fix baseline: 42/43; the single FAIL was the F1–F3 render gap).
Section A now reports `failed=[]` with all 19 fields rendering, including
`sub_sector_id` and `birth_district_id`. Teacher path, student path, canonical
DB state all still PASS.

### 2.4 Regression — 13 suites, fresh processes, run individually

| Suite | Result |
|---|---|
| test_bot_job_schema.py | 62/62 |
| test_bot_job_api.py | 124/124 |
| test_data_integrity.py | 24/24 |
| test_submission_status.py | 12/12 |
| test_bot_job_api_isolation.py | 13/13 |
| smoke_test.py | 14/14 |
| smoke_test_bot.py | 3/3 |
| test_bot_job_bot_integration.py | 54/54 |
| test_students_null_created_at.py | 11/11 |
| test_created_at_creation_paths.py | 11/11 |
| test_created_at_not_null_integrity.py | 26/26 |
| test_persistence_roundtrip.py | 29/29 |
| test_mandatory_field_reconciliation.py | 57/57 |
| **TOTAL** | **440/440 (all exit=0)** |

### 2.5 Canonical data — final `p3b12_db_compare.py`: **9/9**

Integrity `ok`; students 6 `[3,4,6,8,9,10]`; bot_jobs 0; teachers 3 with
unchanged hashes; every canonical student row hash byte-identical (incl. Ayat
id6/id9, id10); Ayat `updated_at` still
`2026-09-26 13:42:48.243900`; no probe leftovers. File sha differs only from
probe insert/delete churn (expected).

---

## 3. Known Issues NOT Fixed (documented only)

| ID | Issue | Why out of scope |
|---|---|---|
| **F4** | Unchecked radios are omitted from the payload (`form.js:681-682` collects only `checked`), so a stored radio value can be set to NULL in DB but **not restored to NULL** through the form (id10's all-NULL radios render nothing and save can't re-clear them) | From 3B.12; not part of the approved F1–F3 set; needs a payload-semantics decision |
| — | `reverseMap` no-ops `roll_no`, `major_disability_text` | Harmless (no control to render, not validated); audited, untouched |

---

## 4. Files Changed This Phase

| File | Change |
|---|---|
| `femis-web/static/form.js` | F2: `form.js:94-105` pending-value apply in `loadDistricts`; F5: `form.js:817` identity reverseMap; F1: `form.js:860-862` prefill select pending stash; F3: `form.js:871-879` prefill checkbox-array branch |
| `test_prefill_rerender.py` | **new** — permanent F1/F2/F3 (+F5) regression test, 30 checks |
| `docs/phase3b13-prefill-rerender-fix.md` | this document |

Temp artifacts (diagnostics, probes) live outside the repo under
`C:\Users\faiza\AppData\Local\Temp\opencode\` (`p3b13_diag.py`,
`p3b13_lang.py`, `p3b13_audit_map.py`).

**Git:** 0 staged, 0 committed, HEAD `6871f81` — the pre-existing uncommitted
body (3B.1–3B.12) is untouched; this phase adds exactly `form.js` (4 hunks) +
`test_prefill_rerender.py` + this doc.

---

## 5. Next Step (single, isolated)

**Commit gate:** obtain the user's go-ahead, then execute the 3B.10.1
two-commit manifest (`docs/phase3b10-1-commit-readiness-audit.md`), folding in
this phase's `form.js` hunks, `test_prefill_rerender.py`, and the 3B.13 doc.
No further fixes or features before that decision.
