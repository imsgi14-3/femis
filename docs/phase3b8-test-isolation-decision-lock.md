# Phase 3B.8 - Test Cleanup Isolation + Decision Lock

Narrow hardening phase. Scope: exactly the four items in the approved brief.

## 1. Purpose

1. Scope `test_bot_job_schema.py` raw-SQL cleanup so it can only remove rows the test
   itself created, using the same isolation principle already in `test_bot_job_api.py`
   (snapshot -> identify own rows -> clean own rows only -> prove pre-existing intact).
2. Lock three decisions **without changing behavior**:
   - `created_at` backfill: deferred / not performed,
   - `created_at NOT NULL`: deferred,
   - CNIC paging: deferred.

## 2. Files changed

- `test_bot_job_schema.py` (untracked test file, edited in place) - the only code file
  changed in this phase.
- `docs/phase3b8-test-isolation-decision-lock.md` - this report (created).

No other file was created or modified.

## 3. Raw cleanup identified

Full audit of every `DELETE FROM` / `delete_raw` call across the repo's test scripts:

| Location | Finding | Action |
|---|---|---|
| `test_bot_job_schema.py:421` `delete_raw("bot_jobs", "student_id IN (3, 4, 6, 7, 9, 10)")` | **Unscoped defect (same class as 3B.7 Item 1).** Deleted every `bot_jobs` row for six real student ids regardless of origin - pre-existing, E2E, or foreign test rows - and even for deleted student 7. | **Fixed** (see section 4) |
| `test_bot_job_schema.py:237` `delete_raw(..., "student_id=? AND attempt_number=5 AND status='pending'")` | Effectively scoped: only reachable when the test's own insert succeeded, and the `(student_id, attempt_number)` UNIQUE constraint guarantees the matched row is the test's own. | Left unchanged (minimum change) |
| `test_bot_job_api.py:819, 852, 853` | Scoped to `student_id IN (created_students)` (3B.7 fix). | Unchanged |
| `test_bot_job_bot_integration.py:840, 841` | Scoped to own ids. | Unchanged |
| `test_bot_job_api_isolation.py:171, 172`; `test_students_null_created_at.py:57, 100, 101` | Scoped to own sentinel ids/names. | Unchanged |

`K3` also asserted the whole `bot_jobs` table was **empty** after cleanup (`n == 0`) - the
same "empty-table" entanglement fixed in 3B.7 - so the suite could never pass with any
pre-existing row present.

## 4. Exact isolation mechanism applied

All in `test_bot_job_schema.py`:

1. **Snapshot before any insert** - `baseline_jobs = all_jobs()` captured as the first
   action inside the app context (full `SELECT * FROM bot_jobs ORDER BY id`).
2. **Precise own-row identification** - `insert_raw()` now records `cursor.lastrowid` on
   every successful insert into `created_job_ids` (all of its call sites insert `bot_jobs`).
3. **`ours_where(prefix="")` helper** - returns `AND id IN (<our ids>)` (params tuple), or
   `AND 0=1` when no rows were created, so statements can never match a pre-existing row.
   Prefix parameter exists because one query joins `bot_jobs j` to `bot_jobs p` (`j.id`).
4. **All four mid-test UPDATEs scoped** with `ours_where`:
   - closing sid3's pending job (`status='failed'`), - closing F-section open statuses
     (`status='cancelled'`, by `attempt_number`),
   - the two I-section updates on student 9's attempt 1 (`running` then `cancelled`).
   Previously these matched by `student_id` alone and would have mutated a pre-existing
   pending row of a real student.
5. **Read-backs scoped** so the suite never asserts against a foreign row:
   - D5 history count and D6 `prior_attempt_id` join (added `ours_where("j.")` to fix an
     ambiguous `id` in the join),
   - I2-I5 snapshot fetch (`student_id=9 AND attempt_number=1` + ours).
6. **Cleanup scoped** - the `student_id IN (3, 4, 6, 7, 9, 10)` delete was replaced with
   `DELETE FROM bot_jobs WHERE id IN (created_job_ids)` (no-op when the list is empty).
7. **Guaranteed cleanup (`try`/`finally`)** - the whole test body now runs inside
   `try: ... finally:` so own rows and own test student are removed **even if a check
   raises mid-run** (crash no longer leaves residue). Post-cleanup assertions run only on
   the success path.
8. **Assertions strengthened, none weakened**:
   - `K3` changed from `n == 0` to `count == len(baseline_jobs)`,
   - **new `K3b`**: byte-identity of the full table against `baseline_jobs`
     (`all rows == baseline rows`), the direct proof that pre-existing rows survived,
   - `K4` now positively verifies each created student id is actually gone,
   - every pre-existing check (A-I, J, K1) is unchanged in substance; the suite grew from
     61 to 62 checks (K3b added).

During development, a bug in an intermediate edit (unqualified `id` in the D6 join) crashed
the run and left residue (student 11 + 4 `bot_jobs` rows). That residue was **detected by
the new baseline mechanism on the next run**, confirmed as this suite's own profile, and
removed; the `try`/`finally` restructure guarantees this cannot recur.

## 5. Pre-existing-row protection

Dedicated sentinel proof (temp script, not added to the repo): a terminal E2E-style
`bot_jobs` row for the designated test student (Ahmed, `id=8`, `status='success'` with full
evidence columns) was inserted while the table was otherwise empty, then
`test_bot_job_schema.py` was run as a subprocess with that row present.

- Suite: **`rc=0`, `62/62 passed`, zero `FAIL:` lines.**
- `K3` detail shows `baseline=1 after=1`; `K3b` shows `baseline_ids=[1] after_ids=[1]`.
- The sentinel row survived **byte-identical** (full-dict comparison).
- Students table unchanged by the suite (its own test student cleaned).
- Sentinel then removed by the proof script; DB returned to pristine.

## 6. Tests run and results

Focused first, then full regression (all `check()` house-style scripts, exit 0, zero
`FAIL:` lines):

| Order | Suite | Result |
|---|---|---|
| 1 (focused) | `test_bot_job_schema.py` | **62/62 passed** (61 + new K3b) |
| 2 | `test_bot_job_schema.py` (re-run in full regression) | 62/62 passed |
| 3 | `test_bot_job_api.py` | 124/124 passed |
| 4 | `test_bot_job_bot_integration.py` | 54/54 checks passed |
| 5 | `test_data_integrity.py` | 24/24 passed |
| 6 | `test_submission_status.py` | 12/12 passed |
| 7 | `smoke_test.py` | 14/14 passed |
| 8 | `smoke_test_bot.py` (bot smoke) | 3/3 passed |
| 9 | `test_bot_job_api_isolation.py` | 13/13 passed |
| 10 | `test_students_null_created_at.py` | 8/8 passed |

Plus the sentinel proof of section 5: **8/8 passed**.

## 7. `created_at` backfill decision: **deferred / NOT performed**

Ahmed Khan (`id=8`) still has `students.created_at = NULL`. No UPDATE/INSERT was issued
against any existing student row. The 3B.7 template null guards
(`femis-web/templates/list.html`, `success.html`) remain the active mitigation, and
`test_students_null_created_at.py` (8/8) continues to prove `/students` and `/success`
render correctly with the NULL value. Backfill remains blocked on an admin decision about
what timestamp to display.

## 8. `created_at NOT NULL` decision: **deferred**

No migration, no `ALTER TABLE`, no model change. Verified from live schema DDL:
`created_at DATETIME` (NOT NULL flag = 0, i.e. still nullable). Decision explicitly
deferred until every legitimate student-creation path has been audited and confirmed to
always supply a valid timestamp.

## 9. CNIC paging decision: **deferred**

No CNIC paging implemented; no lookup behavior, selector, or bot code touched
(`src/form_filler.py` unmodified in this phase). The 3B.7 assessment (section 10 of
`phase3b7-post-e2e-hardening.md`) stands: paging remains deferred until the appropriate
browser-automation / FEMIS interaction phase, and any future implementation requires
explicit approval plus selector-stability and negative-path verification.

## 10. Database/data state after verification

Final read of `femis-web/instance/femis.db`:

- **Students: exactly 6 rows** - `3 Ali Khan`, `4 Test2`, `6 Ayat Mubeen`,
  **`8 Ahmed Khan` intact** (`b_form=35202-1234567-1`, `created_at=NULL` preserved,
  `updated_at` present), `9 Ayat Mubeen`, `10 Portal Verify Student`.
- **`bot_jobs`: 0 rows.** No unexpected rows created; no unrelated rows deleted.
- `NULL created_at` ids: `[8]` - unchanged from the 3B.7 baseline (not backfilled).
- `students.created_at` column: still nullable (no `NOT NULL` added).
- Indexes: `uq_students_b_form` intact; `uq_bot_jobs_open_per_student` and all
  `ix_bot_jobs_*` intact; no new indexes added.
- Only test-owned rows were ever created and removed during this phase (the schema test's
  own student/job rows, the sentinel, and the mid-phase crash residue of section 4).

## 11. Files explicitly confirmed untouched

- **Production application routes:** `femis-web/app.py` - not modified in this phase
  (its working-tree diff is inherited from 3B.6/earlier phases).
- **Bot selectors / CNIC lookup:** `src/form_filler.py` - not modified in this phase.
- **Job runner / API client:** `src/job_runner.py`, `src/job_api_client.py` - untouched.
- **Bot-job API contract:** `femis-web/job_api.py` - untouched.
- **Database schema:** no `ALTER`/`CREATE TABLE`/`CREATE INDEX` issued; schema DDL
  verified unchanged (section 10).
- **Templates:** `list.html` / `success.html` keep only their 3B.7 one-line guards; not
  touched in this phase.
- All other test suites; all prior phase docs; user's :5000 dev server; git index
  (nothing staged or committed).

## 12. Remaining follow-up items

1. **`created_at` backfill** - awaiting admin decision (chosen display timestamp for
   Ahmed's NULL value, or keep guard-only forever).
2. **`created_at NOT NULL`** - deferred pending a full audit of student-creation paths
   (app ORM paths already set it; legacy raw-SQL scripts do not - `insert_test_record.py`
   remains the known NULL producer and is recommended for deprecation).
3. **CNIC paging** - deferred to the browser-automation / FEMIS interaction phase;
   requires explicit approval before any selector or bot change.
4. **Known constraint (documented, by design):** the schema suite's D-section inserts
   `(student_id, attempt_number)` attempts 1-4 for student 6, and E/F/G/I/K sections pin
   rows to students 3, 4, 7, 9, 10. If any future run leaves pre-existing `bot_jobs` rows
   for those students, the UNIQUE constraint makes the affected inserts fail **loudly**
   (assertion failure) rather than corrupt data - the suite refuses to pass, it does not
   silently mutate foreign rows.
5. Pre-existing backlog items from 3B.7 §15 not in this phase's scope remain open.

## 13. STOP status

All approved 3B.8 work is complete: the schema-test cleanup is isolated (proven against a
pre-existing row), all 9 regression suites pass, the three decisions are locked as
**deferred / not performed**, and the database/E2E state is verified unchanged.

**STOP - awaiting approval for the next phase.**
