# Phase 3B.7 - Post-E2E Hardening and Deferred-Issue Review

Scope: exactly the three items carried from the 3B.6 STOP report. No scope drift; no 3B.8 work.

## 1. Environment

- Local Windows/PowerShell session; Python 3.12; Flask + SQLite (`femis-web/instance/femis.db`).
- User's dev server on **:5000 (PID 15996) untouched throughout.** The 3B.6 E2E instance
  on :5001 (PID 21444) was already stopped before this phase began.
- Repo: branch `main`, HEAD `6871f81`, working tree dirty (nothing staged or committed, per
  standing directive).
- Test runtime: house-style `check(name, ok, detail)` scripts at repo root; no pytest.

## 2. Preconditions (pre-flight)

- `docs/` intact (16 files, including `phase3b6-e2e-verification.md` unchanged apart from the
  previously approved remediation addendum).
- Students table: 6 rows (`3, 4, 6, 8, 9, 10`); `bot_jobs`: 0 rows; unique index
  `uq_students_b_form` present.
- **`created_at IS NULL` isolated to exactly one row: Ahmed Khan, `id=8`** (the legacy
  `insert_test_record.py` target). No other NULL `created_at`, no NULL `updated_at`.
- Git state matched the 3B.6 handoff (10 modified / 16 untracked / 0 staged).
- 3B.6 evidence in `C:\Users\faiza\AppData\Local\Temp\opencode\p3b6_*` present and untouched.

## 3. Baseline regression (pre-change)

All green before any edit: **61/61** (schema), **123/123** (bot job API), **54/54**
(bot integration), **24/24** (data integrity), **12/12** (submission status), **14/14**
(smoke), **3/3** (bot smoke).

## 4. Item 1 - Scope defect (root cause)

`test_bot_job_api.py` deleted **every** row in `bot_jobs` regardless of origin:

- `M1` cleanup: unscoped `DELETE FROM bot_jobs` (old line ~796).
- `finally` fallback: same unscoped delete (old line ~815).
- Assertions assuming an empty table: `S0` global-empty check (`n0==0`, old line ~182) and
  `A11` `total==0` (old line ~240) entangled the suite with "table must be empty at start".

This is what wiped the 3B.6 E2E job rows after evidence capture. The sibling suite
`test_bot_job_bot_integration.py:840` was already correctly scoped (`WHERE student_id=?`).

## 5. Item 1 - Fix implemented

All changes confined to `test_bot_job_api.py`:

1. **Baseline capture** - module globals `baseline_jobs` + `BASELINE_Q`
   (`SELECT bj.*, s.name AS student_name ... ORDER BY bj.id`).
2. **`S0` rewritten** - records the baseline instead of requiring emptiness; **fails** if it
   finds active foreign jobs (`pending/claimed/running`) or `P3B4 `/`P3B5 ` leftovers, and
   `sys.exit(1)` in that case: the suite refuses to run rather than claim or mutate a foreign
   pending job.
3. **`A11`** now asserts `total == len(baseline_jobs)` instead of `== 0`.
4. **`M1`** scoped: `DELETE FROM bot_jobs WHERE student_id IN (created_students)`
   (no-op when the list is empty).
5. **`M2`** now asserts `n == len(baseline_jobs)`; new **`M2b`** proves
   `all_rows(BASELINE_Q) == baseline_jobs` (byte-identity of pre-existing rows).
6. **`finally`** fallback scoped by the same `student_id IN (created_students)` predicate.
7. Docstring updated to state the isolation contract.

## 6. Item 1 - Verification (isolation proof)

New focused test `test_bot_job_api_isolation.py`: creates a sentinel student
("P3B7 ISOLATION SENTINEL") via `/api/save-tab`, creates a sentinel job through the real
operator API (`POST /api/jobs`) and drives it to terminal `cancelled`, then runs
`python test_bot_job_api.py` as a subprocess with that row present.

**Result: 13/13 passed.**

- Sentinel pre-exists: `pristine=0 → with_sentinel=1`.
- Subprocess suite: **`rc=0`, `124/124 passed`, zero `FAIL:` lines** with the sentinel present.
- Sentinel `bot_jobs` row **survived byte-identical** (full-row dict comparison before/after).
- `bot_jobs` after run `== with_sentinel` exactly (suite removed only its own rows).
- Suite removed only its own students; the sentinel student was kept; no `P3B4 `/`P3B5 `
  student leftovers.
- This file then deleted only its own sentinel; final state restored to pristine
  (0 job rows, students `3,4,6,8,9,10`).

## 7. Item 2 - `/students` 500 diagnosis

- **Pre-fix reproduction (test-owned raw-SQL row with `created_at` NULL):**
  - `GET /students` → **HTTP 500**, `jinja2.exceptions.UndefinedError: 'None' has no
    attribute 'strftime'` at `femis-web/templates/list.html:36`.
  - `GET /success/<id>` for that row → **HTTP 500**, same error at
    `femis-web/templates/success.html:14`.
  - `GET /students/<id>/json` → **200**, `created_at: null` (JSON unaffected).
- **Root cause:** the schema permits `created_at` NULL (column is nullable, no DB DEFAULT);
  every app/ORM write path sets it via `default=datetime.utcnow`, so NULL only arises from
  legacy raw-SQL scripts. `insert_test_record.py` does exactly that - it literally
  `DELETE`s and re-`INSERT`s 'Ahmed Khan' with no `created_at`, which is why `id=8` is the
  only affected row (SQLite's `CURRENT_TIMESTAMP` default is not defined on the column).
  The list/success templates then call `.strftime` on `None`.
- The `/students` route itself (`app.py:601-604`, `ORDER BY created_at DESC`) does not crash;
  SQLite sorts NULL first, so the broken row was guaranteed to be rendered.

## 8. Item 2 - Fix implemented

Minimal presentation-layer guard, matching the templates' existing `—` placeholder style:

- `femis-web/templates/list.html:36`
  → `{{ s.created_at.strftime('%d %b %Y %I:%M %p') if s.created_at else '—' }}`
- `femis-web/templates/success.html:14`
  → `{{ student.created_at.strftime('%d %B %Y at %I:%M %p') if student.created_at else '—' }}`

No route, schema, or `app.py` changes. Data-policy questions (backfilling Ahmed's
`created_at`, hardening the column to `NOT NULL`) are recorded in section 15 for admin
decision and were deliberately **not** implemented.

## 9. Item 2 - Pre/post verification

Focused test `test_students_null_created_at.py` (test-owned row created and removed by the
test itself):

- **Pre-fix: 4/8 passed** - both page checks failed with HTTP 500 (evidence captured in
  section 7); JSON and cleanup checks already passed.
- **Post-fix: 8/8 passed** -
  - `GET /students` → 200, lists the NULL-`created_at` row,
  - still renders a valid-`created_at` record (Ali Khan) formatted,
  - `GET /success/<NULL row>` → 200,
  - `GET /students/<id>/json` → 200 with `created_at` null,
  - test row deleted; students restored to `3,4,6,8,9,10`.

## 10. Item 3 - §13 CNIC paging search assessment (documented, NOT implemented)

- **Current behavior:** `src/form_filler.py` `open_form` (:96) searches the portal list
  **by name only** (the portal list has no CNIC search input - documented in §13 and the
  function docstring), then scans the rendered rows via JS and compares CNIC digits-only:
  match → open for edit, no match → create. `_recover_duplicate` (:194) simply re-runs the
  same name search when the portal returns the 422 "already been taken" response. There is
  **no pagination logic anywhere** in the bot.
- **§13 scope:** the documented procedure (search by name → "Show 100 entries" + `Ctrl+F`
  paging → report the record holder to the admin) is a **manual, admin-owned** resolution
  path for foreign records.
- **Is auto-paging required for correctness?** No, with two edges:
  1. DataTables' name search filters across **all** pages server-side-side (client-side over
     the full dataset), so a match is found regardless of paging; typical name matches fall
     on page 1 within the default page size.
  2. Edge cases: more same-name matches than one page contains, or a name recorded in our
     DB differing from the portal name - both currently degrade to "not found → create",
     with the portal's own duplicate-CNIC guard (and, since 3B.6, our 409 with holder name)
     catching the collision.
- **Risks of implementing auto-paging/auto-edit:** touching paging means touching FEMIS
  list selectors, timing, and the edit-open path - the exact selectors that just passed the
  3B.6 E2E - while §13 explicitly reserves foreign-record ownership for **manual** admin
  verification; automatic editing of an unverified foreign record would contradict that.
- **Assessment: DEFER as an optional enhancement.** Requires explicit approval before any
  implementation, together with a selector-stability and negative-path verification plan.
  No code changed in this phase.

## 11. Post-change full regression (all suites)

| Suite | Result |
|---|---|
| `test_bot_job_schema.py` | 61/61 passed |
| `test_bot_job_api.py` | **124/124 passed** (123 + new `M2b`) |
| `test_bot_job_bot_integration.py` | 54/54 passed |
| `test_data_integrity.py` | 24/24 passed |
| `test_submission_status.py` | 12/12 passed |
| `smoke_test.py` | 14/14 passed |
| `smoke_test_bot.py` | 3/3 passed |
| `test_bot_job_api_isolation.py` (new) | 13/13 passed |
| `test_students_null_created_at.py` (new) | 8/8 passed |

All exit code 0, zero `FAIL:` lines.

## 12. Files created

- `test_bot_job_api_isolation.py` - Item 1 sentinel-preservation proof (13 checks).
- `test_students_null_created_at.py` - Item 2 null-`created_at` rendering proof (8 checks).
- `docs/phase3b7-post-e2e-hardening.md` - this report.

## 13. Files modified

- `test_bot_job_api.py` - scoped cleanup + baseline-aware assertions + `M2b` (Item 1).
- `femis-web/templates/list.html` - one line: null guard on `created_at` (Item 2).
- `femis-web/templates/success.html` - one line: null guard on `created_at` (Item 2).

`git diff` on both templates shows exactly one changed line each; the rest of the working
tree is as inherited from 3B.6.

## 14. Files untouched

- `src/form_filler.py`, `src/job_runner.py`, `src/job_api_client.py` - Item 3 is
  documentation-only; the bot is unchanged.
- `femis-web/job_api.py` (production job API), `femis-web/app.py` (no route/schema change;
  the 3B.6 uniqueness work left as-is), `femis-web/static/form.js`.
- All other test suites; `docs/phase3b6-e2e-verification.md` and other phase docs;
  3B.6 temp evidence (`p3b6_*`).
- Database: no permanent data change (both new tests create and delete only their own rows;
  final students `3,4,6,8,9,10`, `bot_jobs` 0, `uq_students_b_form` intact).
- User's :5000 dev server (PID 15996); nothing staged or committed.

## 15. Decisions requiring admin approval

1. **`created_at` backfill policy** - backfill Ahmed Khan (`id=8`) with a chosen display
   timestamp, or leave NULL permanently and rely on the new template guards (current state)?
2. **Schema hardening** - make `students.created_at` `NOT NULL` with a DB default/`COALESCE`
   migration for existing rows? Requires a migration policy; not done this phase.
3. **Same-class test defect** - `test_bot_job_schema.py` contains
   `delete_raw("bot_jobs", "student_id IN (3,4,6,7,9,10)")`, which targets **real student
   ids** (including deleted id 7) rather than test-owned ids. Smaller blast radius than
   Item 1's defect, same class. Recommend scoping it to ids the suite itself created -
   **not modified in this phase** (out of the three-item scope).
4. **Item 3** - approve or reject the optional CNIC auto-paging enhancement as future work
   (assessment in section 10).
5. **Legacy script** - `insert_test_record.py` mutates the real Ahmed row via raw SQL
   (origin of the NULL). Recommend deprecating or deleting it; not touched this phase.

## 16. Scope limitations

- No job API semantics, bot selectors, field mappings, auth, retry/lease, attempt-history,
  portal-layout, or identity-rule changes.
- No dead-code cleanup, no test-suite redesign beyond the three items.
- Single-process verification only; no load/concurrency testing added.
- 3B.6 evidence and reports not altered.

## 17. Final verdict

**PASS.** Items 1 and 2 are fixed and proven by dedicated focused tests (13/13, 8/8), the
full 9-suite regression is green, and Item 3 is documented as a deferred enhancement with no
code change. All five decision points in section 15 remain with the admin.

# STOP report

### a. Files created
`test_bot_job_api_isolation.py`, `test_students_null_created_at.py`,
`docs/phase3b7-post-e2e-hardening.md`

### b. Files modified
`test_bot_job_api.py`, `femis-web/templates/list.html` (1 line),
`femis-web/templates/success.html` (1 line)

### c. Files untouched
Job API, bot, `app.py` routes/schema, other suites, phase docs, 3B.6 evidence, DB data
(6 students / 0 jobs), user's :5000 server, git index (nothing staged/committed).

### d. Test counts
Baseline: 61/61, 123/123, 54/54, 24/24, 12/12, 14/14, 3/3.
Post-change: 61/61, **124/124**, 54/54, 24/24, 12/12, 14/14, 3/3, plus new
13/13 (isolation) and 8/8 (null `created_at`) - all exit 0, zero FAIL lines.

### e. Results
- **Item 1: FIXED & PROVEN** - scoped cleanup; suite passes with a pre-existing row and
  leaves it byte-identical.
- **Item 2: FIXED & PROVEN** - both pages 200 with NULL `created_at`; pre-fix 500s captured
  as evidence; valid rows still render.
- **Item 3: ASSESSED, NOT IMPLEMENTED** - deferred with rationale (section 10).

### f. Blockers / failures
None.

### g. Was any application code changed?
Yes, presentation layer only: two single-line Jinja null guards. No Python application,
API, bot, or schema code changed.

### h. Next-session anchor (single next step)
Await admin decisions on section 15 (chiefly: `created_at` backfill + `NOT NULL` hardening,
and whether to scope `test_bot_job_schema.py`'s `delete_raw` to test-owned ids). Only after
explicit approval: Phase 3B.8.

**STOP - awaiting approval before any 3B.8 work.**
