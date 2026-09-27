# Phase 3B.11 — Local Portal Functional Integrity & Requirements Reconciliation

**Status: DIAGNOSIS COMPLETE — STOPPED AFTER DIAGNOSIS (no fixes applied).**
Nothing staged, nothing committed, HEAD `6871f81`. No bot selectors/mappings altered.

---

## 1. Scope & rules honored

Read-only diagnostic of the working tree against four priorities (P1 persistence,
P2 mandatory fields, P3 authorization, P4 Ayat Mubeen bot-prep). No code/template/config
changes; no DB mutations except temporary isolated probe rows that were deleted; no
invented values; no real FEMIS submission; no authorization or selector changes implemented.

---

## 2. Executive summary — exact root causes

| # | Root cause | Class |
|---|---|---|
| **RC1** | The `:5000` server (PID 15996) started **2026-09-23 10:20:50** running `python femis-web/app.py` with **`app.run(debug=False)`** (`femis-web/app.py:895` → no auto-reloader). Its Python code is frozen at that instant while HTML/JS are served fresh from disk every request. The tree has since gained 4 commits (`3e447cb` Sep 23 10:33, `87c7964` Sep 24 10:12, `c99b6e7` Sep 24 13:18, `6871f81` Sep 24 16:01) plus all 3B.x working-tree edits (`app.py` mtime Sep 26 22:04). | **environmental (stale process)** |
| **RC2** | Because of RC1, the live handler's stale `FORM_FIELD_MAP` / `hasattr(Student, …)` filter silently **drops form keys it does not know**, and its stale model **omits `transport` and `updated_at` entirely** — so those values can never be written back or read out. | **consequence of RC1** |
| **RC3** | A **duplicate empty row `id 9`** ("Ayat Mubeen", created 2026-09-23 10:07:11 — 13 min before the server started) is produced by the **login auto-create path** (`app.py:661-671`) when name+class+section+roll don't match an existing row. Logging in with roll `01` lands on the empty row → the whole form appears empty. | **data + auth flow** |

**Bottom line:** current code persists and reloads correctly (proved by
`test_persistence_roundtrip.py` 29/29). The symptom is produced by a stale server
process, plus a duplicate login-created row.

---

## 3. Priority 1 — Ayat Mubeen persistence

### 3.1 The two rows (exact DB contents, nothing invented)

| | **id 6** | **id 9** |
|---|---|---|
| name / class / section / roll | Ayat Mubeen / 9 / A / **07** | Ayat Mubeen / 9 / A / **01** |
| created_at | 2026-09-22 05:20:45.030902 | 2026-09-23 10:07:11.050064 |
| updated_at | 2026-09-26 13:42:48.243900 | 2026-09-23 10:07:11.050064 |
| submitted / locked | 1 / 0 | 0 / 0 |
| content | **139 populated columns** (b_form `42501-3096791-0`, father `M. Nawaz Khan`, `transport='Institution Bus'`, `bus_route='TARNOL'`, `sub_sector_id='I-14/3'`, …) | **only** name/roll/class/section/created/updated — **all other 133 columns NULL** |

### 3.2 End-to-end trace (populated field `father_name`, and `transport`)

```
browser form.html (current)  →  form.js pre-fill  →  GET /students/6/json
   app.py:607 student_json   →  Student.to_dict()  →  browser sets input[name=father_name]
edit + "Save & Next"         →  POST /api/save-tab (app.py:470)
   _map_form_data (app.py:431) → setattr loop (app.py:498) → db.session.commit()
reload                        →  same JSON → form.js reverseMap (form.js:780) → field re-filled
```

- **`father_name` round-trips correctly** through the live server (probe: created →
  reloaded → value present; `test_persistence_roundtrip.py` proves the same on current code).
- **`transport` does NOT**: DB holds `'Institution Bus'` for id 6, but the live server's
  model has no `transport` column → `to_dict()` (`app.py:196`) returns **139 keys instead of
  141, omitting `transport` and `updated_at`** → `form.js:797` never sees `transport` →
  never checks the `transport_facility` radio → **renders empty**.
- Writes fail symmetrically: live probe saved `{transport_facility: "Institution Bus",
  refugee_card_number: …, disability_types[]: …}` → HTTP 200 `ok:true` → DB row showed
  `transport=None`, `refugee_card=None`, `disability_types=None`.

**Exact persistence failure path (RC1+RC2):**
`POST /api/save-tab` → **stale** handler → stale `FORM_FIELD_MAP` + `hasattr()` filter →
unknown keys silently dropped → commit writes only known columns → `200 ok` returned →
reload → **stale** `to_dict()` omits `transport`/`updated_at` → form.js has nothing to
pre-fill → **previously saved value appears empty**. Secondary path: wrong login roll →
row id 9 → entire form empty (RC3).

### 3.3 Accounts used (existing auth only)

- **Student**: logged in live as *Ayat Mubeen / 9 / A / 07* → resolved to **id 6** (no new row).
- **Teacher**: **not testable** — `teachers` are `Mrs. Ahmed (5A)`, `laraib (8A)`,
  `faiza (9A)` with hashed passwords; no credentials exist anywhere in the repo;
  `/api/setup-teacher` is blocked (teachers already exist) and `/api/register-teacher`
  requires an existing teacher session. **No credentials were invented**; teacher behavior
  was audited by code reading instead (§5).

### 3.4 Is `:5000` running current code / current DB?

| Question | Answer | Evidence |
|---|---|---|
| Current code? | **NO — Python layer is stale** (frozen ≥ Sep 23 10:20) | process start 09/23 10:20:50, cmdline `python.exe femis-web/app.py`, `debug=False`; live `/api/jobs*` → **404** though current `app.py:370-372` registers the blueprint; live JSON lacks `transport`/`updated_at` |
| Current HTML/JS? | **YES** | `/static/form.js` served byte-identical to disk (sha256 `1265b82650cc21a1…`, `Cache-Control: no-cache`); rendered form contains **8/8 working-tree-only markers** (e.g. `value="Institution Bus"`, "Personal Information" headings) that did **not** exist at `391699b` (`value="Bus"`) |
| Same source tree? | **YES** | relative cmdline ⇒ CWD = repo root; served static bytes match this tree exactly |
| Same (canonical) DB? | **YES** | no `DATABASE_URL` in `.env`/env; `app.py:15-16` → `femis-web/instance/femis.db`; proven empirically — rows created by the server were read from this file, and test-created rows appeared here |
| Other python processes? | none — PID 15996 is the only one | `Win32_Process` enumeration |

### 3.5 Caching — evidence, not assumption

- Server → browser: static JS `Cache-Control: no-cache` + ETag (revalidation forced);
  HTML response carries **no** `ETag`/`Last-Modified`/`Cache-Control`.
- Server-side: served bytes == disk bytes for JS and template ⇒ **no server-side staleness**.
- The stale layer is the **Python process**, not a cache. Client-side browser cache cannot be
  inspected headlessly; if the symptom persists after a server restart, inspect the browser
  cache next (documented as the only unverified cache layer).

---

## 4. Priority 2 — mandatory-field discrepancy matrix

Extracted from the **actual current** `form.html` / `form.js` / `app.py`
(automated by `test_mandatory_field_reconciliation.py`, 57/57).
Legend: **M** = enforced, **—** = not enforced.

| # | FEMIS requirement | current HTML | current JS | conditional rule | server validation | discrepancy | proposed fix (NOT applied) |
|---|---|---|---|---|---|---|---|
| 1 | sector + sub-sector when address uses sector | present, **not** required | **—** | **none** | **—** | **GAP** | add `conditionalRequired` entry `sector_id`+`sub_sector_id` ← `address_type` in `["Sector"]` |
| 2 | income per month (father) | present | M (tab1) | — | — | none | — |
| 3 | qualification (father) | present | M (tab1) | — | — | none | — |
| 4 | orphan type when orphan=yes | present | — | M ← `is_orphan=["1"]` | — | none | — |
| 5 | orphan=yes invalid when both parents alive | — | M (inline guard) | — | — | none | — |
| 6 | guardian name/CNIC/relation/WhatsApp | **required** | M (tab1) | — | **—** | none (client only) | see #X |
| 7 | guardian profession + income | **required** | M (tab1) | — | **—** | none (client only) | see #X |
| 8 | mother income unless housewife | present | M (inline `Housewife` rule) | — | — | none | — |
| 9 | date of admission **MM/DD/YYYY** | required, no `pattern` | M (presence only) | — | **—** | **GAP** | add `^\d{2}/\d{2}/\d{4}$` check in `validateTab` + server |
| 10 | class admitted ranges 1–5 / 6–10 | radios generated by JS | M (tab2) + `lo/hi` logic (`form.js:435-436`) + generated radios `required` | — | — | none | — |
| 11 | Primary Education Completion **NOT** mandatory | **not** required | **not** in mandatoryByTab | — | — | none (requirement met) | keep as-is |
| 12 | meal program | present | M (tab2) | — | — | none | — |
| 13 | transport facility | **required** | M (tab2) | `bus_route` ← `transport_facility∈[Bus, Institution Bus]` | — | none | — |
| 14 | rename Bus → **Institution Bus** | values `Institution Bus/Private/None` (no `Bus`) | legacy `Bus` tolerated in trigger | — | — | none (requirement met) | — |
| 15 | scholarship | **required** | M (tab2) | `scholarship_details` ← `scholarship=["1"]` | — | none | — |
| 16 | co-curricular activity | **required** | M (tab2) | `cocurricular_details` ← `cocurricular_activities=["1"]` | — | none | — |
| 17 | IDP/refugee status when applicable | present | M `is_refugee` (tab4) | `idp_status_id`, `is_registered_refugee`, `refugee_card_number` chain | — | none | — |
| 18 | major disability | **required** | M (tab5) | `disability_types[]` ← `has_major_disability=["1"]` | — | none | — |
| 19 | mental disability | **required** | M (tab5) | `mental_disability_type` ← `has_mental_disability=["1"]` | — | none | — |
| 20 | visually fit | **required** | M (tab5) | — | — | none | — |
| 21 | wears glasses | **required** | M (tab5) | — | — | none | — |
| 22 | glasses prescription when visually fit=no | required | — | M ← `visually_fit=["0"]` | — | none | — |
| 23 | hearing difficulty | **required** | M (tab5) | — | — | none | — |
| 24 | hearing aid when hearing difficulty=yes | required | — | M ← `has_hearing_difficulties=["1"]` | — | none | — |
| 25 | difficulty listening | **required** | M (tab5) | — | — | none | — |
| 26 | difficulty walking | **required** | M (tab5) | — | — | none | — |
| 27 | crutches/walker | **required** | M (tab5) | — | — | none | — |
| 28 | digital-device access | **required** | M (tab6) | — | — | none | — |
| 29 | device type when access=yes | present | — | M ← `digital_device_at_home=["1"]` | — | none | — |
| 30 | internet access | **required** | M (tab6) | — | — | none | — |
| **X** | (cross-cutting) server-side enforcement | — | — | — | **only B-Form uniqueness** | **GAP** | move the tab/conditional rule set into a shared server-side validator used by `api_save_tab` + `api_final_submit` |
| **Y** | (cross-cutting) HTML-only `required` | `b_form`, `house`, `street`, `shift` carry `required` | **not** in `validateTab`; JS `preventDefault`s submit | — | — | **GAP** | drop `required` from HTML or add these to `validateTab` (`b_form` should be conditional on `is_bform_available`) |

**Total requirement-level discrepancies: 4** (items 1, 9, X, Y).
26 of 30 requirements are implemented client-side exactly as specified; **none** is
enforced server-side.

---

## 5. Priority 3 — authorization / UI audit (read-only)

Live probes used the student session only; no POST was sent that could mutate data.

| Requirement | Current behavior | Evidence | Verdict |
|---|---|---|---|
| Admin full control | **No admin role exists** — login offers only `teacher`/`student`; job API documents this as decision E | `app.py:617-671`, `job_api.py:105` | **GAP** (known/documented) |
| Teacher restricted to own class | dashboard filters class+section; `api_save_tab` enforces class+section match; **but** `/form/<id>` only blocks `role=="student"` | `app.py:690-702`, `app.py:486-491`, `app.py:405` | **PARTIAL** — teacher can open any student's form by direct URL |
| Teacher cannot add teachers | `/api/register-teacher` allows **any** teacher session to create teachers | `app.py:714-717` | **GAP** |
| Teacher delete-record | **No delete route exists anywhere** (only lock/unlock) | `app.py` route list | **GAP** — capability absent |
| Student restricted to own record | `/form/<id>` redirects to own dashboard | live: `/form/9`, `/form/10` → `/student-dashboard` | **MET** |
| Student cannot see all students | `/students` and `/students/<id>/json` have **no auth at all** | live: 200 for student session **and** anonymous | **GAP** |
| Student cannot add another student | (a) login auto-creates a row on non-match; (b) `api_save-tab` create branch has **no auth check** | `app.py:661-671`; live probe created id 11 **with no session** | **GAP** |
| Completion returns to own dashboard/edit | success page's primary button → `/` → own dashboard ✔; secondary "View All" → `/students` ✗ | `form.js:746`, `success.html:18,21` | **PARTIAL** |

No authorization changes were implemented (diagnosis only).

---

## 6. Priority 4 — Ayat Mubeen bot preparation (DB contents only)

### id 6 (the populated row) — mandatory gaps from the actual DB

| # | Unfilled mandatory field (from current JS rules) | DB value |
|---|---|---|
| 1 | `guardian_name` | `None` |
| 2 | `guardian_cnic` | `None` |
| 3 | `guardian_relation` | `None` |
| 4 | `guardian_contact` (WhatsApp) | `None` |
| 5 | `guardian_profession` | `None` |
| 6 | `guardian_income` | `None` |

- **Format mismatch (not currently enforced):** `date_of_admission = '2023-04-24'`
  (ISO) does **not** match the required `MM/DD/YYYY`.
- All other required values are present, incl. `sector_id='34'`, `sub_sector_id='I-14/3'`,
  `transport='Institution Bus'`, `bus_route='TARNOL'`, `primary_education_completion_years='5'`
  (correctly non-mandatory), disability/vision/hearing set, `digital_device_type='Mobile Phone,Laptop'`.
- **Open requirement question (needs admin ruling):** both parents are alive
  (`is_father_alive='1'`, `is_mother_alive='1'`) yet current JS makes the six guardian
  fields **unconditionally** mandatory → this record cannot pass validation until either
  the data or the rule is decided.
- Placeholder strings already present in the DB (not invented here): `achievement_details='None'`,
  `scholarship_details='None'`.
- **No real FEMIS submission attempted.**

### id 9 (the duplicate) — 64 of the mandatory set empty (everything but name/class/section/roll).

---

## 7. Tests & results

| Suite | Result |
|---|---|
| `test_persistence_roundtrip.py` **(new)** | **29/29** |
| `test_mandatory_field_reconciliation.py` **(new)** | **57/57** (reports 4 discrepancies) |
| `test_bot_job_schema.py` | 62/62 |
| `test_bot_job_api.py` | 124/124 |
| `test_data_integrity.py` | 24/24 |
| `test_submission_status.py` | 12/12 |
| `test_bot_job_api_isolation.py` | 13/13 |
| `smoke_test.py` | 14/14 |
| `smoke_test_bot.py` | 3/3 |
| `test_bot_job_bot_integration.py` | 54/54 |
| `test_students_null_created_at.py` | 11/11 |
| `test_created_at_creation_paths.py` | 11/11 |
| `test_created_at_not_null_integrity.py` | 26/26 |
| **Total** | **440 checks green** |

**Transparency note:** on the *first* batch run `test_bot_job_api_isolation.py` reported
**10/13** (it re-runs `test_bot_job_api.py` in a subprocess with a 300 s timeout). The
immediate re-run of the suite alone **and** an identical re-run of the whole batch both
gave **13/13**. The failing check names were not captured in that first run — recorded
here as an observed one-off, not hidden.

---

## 8. DB state before / after

| | before 3B.11 | after 3B.11 |
|---|---|---|
| file SHA-256 | `b2158fb644e0c57c5a416c4a0302ebaab81384d67d92706b5731d75e8a56a533` (end of 3B.10.1; 3B.10 recorded `725c3eb0…`) | `d13e94fee5accb5bab22d9f1907e32382f690e5b4b014f84148fc4460b38c34c` |
| students | 6 — ids `[3,4,6,8,9,10]` | **6 — ids `[3,4,6,8,9,10]` (identical)** |
| NULL `created_at` / integrity / FK | 0 / ok / clean | **0 / ok / clean** |
| bot_jobs | 0 | **0** |
| Ayat id 6 `updated_at` | 2026-09-26 13:42:48.243900 | **unchanged** |
| Ayat id 9 | untouched | **untouched** |

Hash changes are byte-level churn from test/probe writes (SQLite), not data drift —
logical contents verified identical. **Temporary data created and deleted:** one live
probe row (id 11) and one persistence-test row (id 11); both confirmed absent; the
final id list proves no residue.

---

## 9. Files changed / created

**Created (3):**
- `docs/phase3b11-local-functional-integrity-audit.md` (this file)
- `test_persistence_roundtrip.py`
- `test_mandatory_field_reconciliation.py`

**Modified: none.** No existing test, template, JS, server, selector, mapping, or config
file was touched. Git: nothing staged, nothing committed, HEAD `6871f81`.

---

## 10. Requires admin approval (nothing done)

1. **Restart the `:5000` server** — the single fix for RC1/RC2 (PID 15996 is your dev
   server; not killed without approval). After restart, re-verify transport/updated_at.
2. **Duplicate row id 9** — merge/delete or keep? (data decision; login auto-create will
   keep making more until addressed).
3. **P2 fixes** (items 1, 9, X, Y in §4) — not implemented (stop-after-diagnosis).
4. **P3 authorization changes** (§5) — not implemented.
5. **Guardian-rule ruling** for records whose both parents are alive (§6) — requirement
   interpretation needs the admin's FEMIS source-of-truth.
6. **Teacher credentials** — needed if live teacher-path testing is wanted later.
