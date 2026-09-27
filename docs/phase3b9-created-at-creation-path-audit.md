# Phase 3B.9 - Student Creation-Path Audit + `created_at` Hardening Decision

Audit-first phase. **No schema change, no data change** - read-only analysis plus one
focused test file and this document.

## 1. Purpose

Audit every code path that can create a `students` row, determine whether each can store a
NULL `created_at`, and produce an evidence-based recommendation on whether a future phase
can safely enforce `students.created_at NOT NULL`. The constraint itself is **not**
implemented in this phase.

## 2. Scope

- Every `Student(...)` construction, `db.session.add(...)`, `INSERT INTO students`, seed,
  fixture, and migration/bootstrap touch in the repository (all `*.py` files searched;
  targeted greps for `Student(`, `add_all`, `INSERT INTO students`, `INTO students`).
- Model definition, live SQLite DDL, current NULL records, `insert_test_record.py`.
- Excluded (unchanged by definition of this phase): schema, data, routes, bot, job API.

## 3. Complete creation-path inventory

Nine touch points found; **four actually create student rows in production**:

| # | Path | Location | Creates rows? |
|---|---|---|---|
| 1 | `POST /api/save-tab` create branch | `femis-web/app.py:500-506` (`api_save_tab`) | Yes (ORM) |
| 2 | `POST /api/final-submit` | `femis-web/app.py:519-544` | **No** - update-only (404 on unknown id) |
| 3 | `POST /submit` legacy form | `femis-web/app.py:570-592` (`submit`) | Yes (ORM) |
| 4 | `POST /login` student auto-create | `femis-web/app.py:661-669` (`login`) | Yes (ORM) |
| 5 | `insert_test_record.py` | repo root, raw `sqlite3` | Yes (raw SQL) |
| 6 | `test_students_null_created_at.py:65` | raw `sqlite3` INSERT | Yes (intentional NULL fixture) |
| 7 | `test_created_at_creation_paths.py` D1 (new) | raw `sqlite3` control | Yes (intentional NULL control) |
| 8 | Bootstrap/migration block | `femis-web/app.py` ~336-360: `db.create_all()`, column `ALTER`s, `UPDATE students SET updated_at=COALESCE(...)` | **No rows** - DDL only; `updated_at` backfill never writes `created_at` |
| 9 | Everything in `src/` (bot, `job_runner.py`, `job_api_client.py`, `webform_handler.py`), `femis-web/job_api.py`, teacher/admin routes (`/api/register-teacher`, `/api/setup-teacher`) | - | **No** - grep confirms no student creation; `job_api.py` writes only `bot_jobs` |

Not-a-path negatives confirmed: no `db.session.add_all(...)` anywhere; no SQLAlchemy Core
`insert()` against `students`; no other raw `INSERT INTO students` anywhere in the repo
(only #5, #6, #7).

## 4. Classification of each path

| Path | Classification |
|---|---|
| 1. `POST /api/save-tab` create | **1 - Production/legitimate** |
| 2. `POST /api/final-submit` | 1 - Production (no create) |
| 3. `POST /submit` legacy create | **1 - Production/legitimate** (legacy route, still live and reachable) |
| 4. `POST /login` auto-create | **1 - Production/legitimate** |
| 5. `insert_test_record.py` | **4 - Legacy/deprecated** (no code/test invokes it; only historical doc references: `docs/db-canonical.md:24,45`, `docs/femis-separation-audit.md:60,116,710`) |
| 6. null-created_at test fixture | 3 - Development/test utility |
| 7. audit test control (new) | 3 - Development/test utility |
| 8. bootstrap/migration | 1 - Production (DDL only) |
| 9. bot/job/src writers | 2 - Bot/E2E (no student writes; `job_api.py` writes `bot_jobs` with FK to existing students only) |

No "Unknown - requires review" paths remain after the searches in section 3.

## 5. `created_at` behavior for each path

- **Path 1 (save-tab create):** `Student(**mapped)` where `_map_form_data` forwards *any*
  payload key matching a `Student` attribute - so a crafted JSON body can inject
  `created_at`. Proven empirically (flush + rollback probe, zero rows persisted) and by the
  focused test: **explicit `created_at: null` still gets the model default** - SQLAlchemy's
  column `default` fires whenever the value would be NULL. A non-datetime value (e.g.
  `""` or a string) raises `StatementError` at flush -> HTTP 500, never NULL. **Cannot
  produce NULL.**
- **Path 3 (legacy `/submit`):** form keys filtered by `hasattr(Student, ...)`, so a
  crafted `created_at=""` reaches the model -> SQLite DateTime bind raises `StatementError`
  -> 500, **no row stored** (test B3 proves it). Normal forms never send the key -> default
  applies. **Cannot produce NULL** (fails loudly instead).
- **Path 4 (`/login` auto-create):** `created_at` is never passed -> default always
  applies. **Cannot produce NULL.**
- **Path 5 (`insert_test_record.py`):** raw `sqlite3` INSERT never names `created_at`;
  the DDL has no column DEFAULT -> **NULL guaranteed.**
- **Paths 6/7 (test fixtures):** raw INSERT, `created_at` deliberately omitted -> NULL by
  design (proves the bypass; rows removed by the tests themselves).

## 6. Model/default analysis

From `femis-web/app.py:39` (unchanged, not modified this phase):

```python
created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

- **Python-side default:** yes - `datetime.utcnow`, applied at INSERT when no value is
  set **or set to None** (verified empirically: explicit `None` -> default fires).
- **`onupdate`:** none for `created_at` (`updated_at` has its own
  `default=datetime.utcnow, onupdate=datetime.utcnow` - separate column).
- **Database-level default:** none (`server_default` not specified).
- **Raw SQL bypass:** yes - raw `sqlite3` inserts skip the ORM entirely, so no default is
  evaluated; the column stores NULL (how Ahmed's row was created).
- **Live DDL agrees with model:** yes (section 7).
- Probe results (temp script, rollback only, nothing persisted):
  `explicit None -> datetime(2026-09-26, ...)`;
  `unset -> datetime(...)`;
  `_map_form_data({"created_at": None})` forwards the key -> default still fires;
  `created_at="" -> StatementError (SQLite DateTime type only accepts Python datetime)`.

## 7. Live SQLite DDL verification

Read from `femis-web/instance/femis.db` (`PRAGMA`/`sqlite_master`, no changes made):

- `students.created_at DATETIME` - **nullable** (notnull flag 0), **no `DEFAULT` clause**
  in the `CREATE TABLE` statement. Matches the model (no `server_default`, no
  `nullable=False`).
- Index list unchanged: `uq_students_b_form`, `uq_bot_jobs_open_per_student`,
  `ix_bot_jobs_*`, bot_jobs auto-indexes. No schema or index was created, altered, or
  dropped in this phase.

## 8. Existing NULL-record analysis

```sql
SELECT id, created_at FROM students WHERE created_at IS NULL;
```

- **Count: exactly 1.**
- **id = 8, Ahmed Khan** (`b_form=35202-1234567-1`).
- Origin: legacy raw-SQL insert via `insert_test_record.py`, already documented at
  `docs/db-canonical.md:45` and `docs/femis-separation-audit.md:60`.
- **Known legacy/test data - not produced by any legitimate production creation path.**
  All five other rows (ids 3, 4, 6, 9, 10) have valid timestamps.
- **No row backfilled. Ahmed's value remains NULL** (asserted by focused test check D2).

## 9. `insert_test_record.py` analysis

- **Mechanism:** direct `sqlite3` cursor - `INSERT INTO students (...) VALUES (...)`
  (plus a `DELETE ... WHERE name IN ("Test Student", "Ahmed Khan")` preamble). It never
  touches the ORM.
- **Why NULL:** the column list omits `created_at`, and the live DDL has no column-level
  default, so SQLite stores NULL. It also leaves `submitted` NULL for the same reason.
- **Still used?** No executable reference anywhere - no test, script, route, or import
  invokes it. Only historical mentions in `docs/` (classified there as a "Test-data
  helper"; `femis-separation-audit.md:710` already cites it as an example of the
  "undocumented writer" problem).
- **Safe to leave unchanged?** Yes for now: it is inert (never executed) and its output
  (NULL) is handled by the 3B.7 template guards. It is **not** safe under a future
  `NOT NULL` constraint - its INSERT would be rejected outright (loud failure).
- **Future replacement/deprecation (recorded, not performed):** retire or rewrite it to
  use the ORM (or add `created_at` with an explicit timestamp) before any `NOT NULL`
  migration. Requires admin approval; explicitly out of scope here.

## 10. Tests added/run

**Added (one focused file):** `test_created_at_creation_paths.py` - **10/10 passed**

- A1/A2: `POST /api/save-tab` create **with injected `created_at: null`** -> row created,
  `created_at` non-NULL.
- B1/B2: legacy `POST /submit` create -> row created, `created_at` non-NULL (this route had
  **no test coverage** before).
- B3: crafted `POST /submit` with `created_at=""` -> HTTP 500, **no row stored** (loud
  failure, never NULL); shared-session reset afterwards (production is unaffected -
  each request gets a fresh session).
- C1/C2: `POST /login` student auto-create -> row created, `created_at` non-NULL (this
  branch had **no test coverage** before).
- D1: raw-SQL control -> `created_at` IS NULL (the only bypass; row removed).
- D2: Ahmed id 8 still NULL (decision lock - no backfill).
- E1: students restored to baseline; only this file's rows were deleted.

**Full regression (all exit 0, zero `FAIL:` lines):**

| Suite | Result |
|---|---|
| `test_bot_job_schema.py` | 62/62 |
| `test_bot_job_api.py` | 124/124 |
| `test_bot_job_bot_integration.py` | 54/54 checks |
| `test_data_integrity.py` | 24/24 |
| `test_submission_status.py` | 12/12 |
| `smoke_test.py` | 14/14 |
| `smoke_test_bot.py` | 3/3 |
| `test_bot_job_api_isolation.py` | 13/13 |
| `test_students_null_created_at.py` | 8/8 |
| `test_created_at_creation_paths.py` (new) | 10/10 |

## 11. Decision matrix

| Creation path | Classification | `created_at` guaranteed? | NULL possible? | Action required before NOT NULL? |
| --- | --- | :-: | :-: | --- |
| `POST /api/save-tab` create (`app.py:500`) | Production | **Yes** (default fires even on injected `null`; strings -> 500) | No | None |
| `POST /api/final-submit` (`app.py:519`) | Production (no create) | n/a | n/a | None |
| `POST /submit` legacy create (`app.py:570`) | Production | **Yes** (default; crafted `""` -> 500, no row) | No | None |
| `POST /login` auto-create (`app.py:661`) | Production | **Yes** (default always) | No | None |
| Bootstrap `db.create_all()`/migrations | Production (DDL only) | n/a (creates no rows) | n/a | None |
| `insert_test_record.py` | Legacy/deprecated | **No** - NULL guaranteed | **Yes** | **Retire or rewrite** before enforcement (currently inert) |
| `test_students_null_created_at.py` fixture | Test utility | Deliberately NULL | Yes (by design) | Update/remove the fixture when the constraint lands |
| `test_created_at_creation_paths.py` D1 control | Test utility | Deliberately NULL | Yes (by design) | Update the control when the constraint lands |
| All `src/` bot/job writers | Bot/E2E (no student writes) | n/a | n/a | None |

## 12. Recommended next action

### **A. Ready for future NOT NULL phase**

Every legitimate **production** creation path is proven safe (three ORM create paths, each
with direct test evidence; empirical probe showing even injected `created_at: null` cannot
bypass the default, and non-datetime injections fail loudly without writing a row). The
only NULL producer is the inert legacy script - a classification-4 path, not a production
defect.

Prerequisites for that future phase (migration work, **not done here**):
1. Admin decision + execution for the one existing NULL row (Ahmed id 8) - backfill or
   another resolution; a SQLite `NOT NULL` migration cannot proceed while it exists.
2. Retire or rewrite `insert_test_record.py` (section 9).
3. Update the two intentional-NULL test fixtures (checks D1 / null-test) to the new world.
4. SQLite table-rebuild migration mechanics + full regression re-run.

## 13. No backfill was performed

No `UPDATE students SET created_at = ...` (or any equivalent) was issued. Ahmed Khan's
`created_at` is still **NULL**, verified after all tests (focused check D2 + final DB read:
`NULL created_at ids: [8]`).

## 14. No `NOT NULL` constraint was added

No `ALTER TABLE`, no `CREATE TABLE`, no model edit, no index change. Live DDL re-read after
testing: `created_at DATETIME` still nullable (notnull flag 0), no `DEFAULT` clause, index
list identical.

## 15. Files changed

- `test_created_at_creation_paths.py` - **created** (the only code file added; no existing
  file was edited in this phase).
- `docs/phase3b9-created-at-creation-path-audit.md` - **created** (this report).

## 16. Files confirmed untouched

- `femis-web/app.py` (all four production routes, model definition, migration block),
  `femis-web/job_api.py`, `insert_test_record.py` (not deleted, not rewritten),
  `src/form_filler.py`, `src/job_runner.py`, `src/job_api_client.py`,
  all templates and prior test suites, all prior phase docs,
  the database (no backfill, no schema/index change), user's :5000 dev server,
  git index (nothing staged or committed).

## 17. STOP status

Audit complete: 9 touch points inventoried and classified, 4 production creation paths
proven NULL-proof, 1 legacy NULL producer identified with a recorded retirement action,
1 existing NULL row verified untouched, decision matrix produced with recommendation **A**.
All 10 suites green; DB state and schema state verified unchanged.

**STOP - awaiting approval; no remediation will be implemented without it.**
