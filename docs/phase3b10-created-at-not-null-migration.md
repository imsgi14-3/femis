# Phase 3B.10 — `created_at` Remediation + NOT NULL Migration + Full Regression

**Status: PASS.** Everything below was executed; nothing was staged or committed
(HEAD remains `6871f81`, `git diff --cached` empty).

---

## 1. Scope executed

- STOP-first: verified backup + pre-migration state document **before** any mutation.
- Evidence-based backfill of Ahmed Khan's (id 8) NULL `created_at`.
- Retirement of the legacy raw-SQL writer `insert_test_record.py`.
- `students.created_at` migrated to **NOT NULL** via the documented SQLite table-rebuild
  procedure; model aligned (`nullable=False`); NULL fixtures refit; new integrity suite.
- Fresh-process verification + full regression (11 suites) + final audit.

Explicitly untouched: auth redesign, CNIC paging, FEMIS selectors, field mappings, portal
layout, bot-job API semantics, B-Form uniqueness logic, `form.html`/`form.js`/`form_filler.py`
beyond previous phases' state.

## 2. STOP-first verification (pre-mutation)

- Backup created: `backup/2026-09-26/phase3b10-pre-migration/femis.db`.
- Backup SHA-256 = live SHA-256 = `71064b829459bee80e0659b8ce65d948c6087e1c85953048c0877d338dadb946`
  (byte match, size 143 360 B). Note: PowerShell `Get-FileHash` cannot open the live file
  (the user's `:5000` server holds it) — verified with Python `hashlib` instead.
- Backup opens read-only in SQLite and holds the exact pre-state: 6 students
  `[3,4,6,8,9,10]`, exactly one NULL `created_at` (id 8), `bot_jobs` 0, integrity ok.
- Pre-state document: `docs/phase3b10-pre-migration-state.json` (full DDL, table_info,
  index/FK lists, row snapshot, git state, backup verification block).
- `PRAGMA journal_mode` = `delete`, no `-wal`/`-shm` sidecars → plain copy is a valid backup.

## 3. Pre-migration state

| Item | Value |
|---|---|
| DB SHA-256 | `71064b829459bee80e0659b8ce65d948c6087e1c85953048c0877d338dadb946` |
| students rows | 6 — ids `[3,4,6,8,9,10]` |
| NULL `created_at` | `[8]` (Ahmed Khan) only |
| students columns | 141 |
| `created_at` flags | `notnull=0`, no default |
| Tables / indexes | `bot_jobs, students, teachers`; 8 indexes incl. `uq_students_b_form` |
| FKs | `bot_jobs.student_id→students.id CASCADE`; `bot_jobs.prior_attempt_id→bot_jobs.id SET NULL` |
| bot_jobs rows | 0 |

## 4. Backfill decision (Ahmed id 8)

Full report: `docs/phase3b10-created-at-backfill-decision.md` (7 sections, produced before
the write). Summary:

- **Classification: Class B — migration-assigned.** No historically supported exact
  timestamp exists: the producing script (`insert_test_record.py`) deleted + re-inserted the
  row on every run and recorded nothing; commit times are edit times, not run times.
- Strongest evidence is only a **window**: rowid assignment bounds creation to
  **(2026-09-22 05:20:45, 2026-09-23 10:07:11) UTC** (id 6 created / id 9 created).
  Rejected: commit dates, window midpoints, `updated_at` (2026-09-26, post-creation),
  file mtime (supporting only), 3B.6 evidence times (post-creation).
- **Value written: `2026-09-26 16:59:22`** (naive UTC = decision/finalization time),
  `source = migration_backfill`. Not represented as the historical creation time; this
  document and the decision report are the authoritative provenance record.

## 5. Backfill execution evidence

Script: `p3b10_backfill.py` (temp), 5/5 checks:

1. Pre-condition: only id 8 NULL.
2. `UPDATE students SET created_at='2026-09-26 16:59:22' WHERE id=8 AND created_at IS NULL`
   → `rowcount=1`.
3. Post: 0 NULL rows.
4. id 8 now equals the documented value exactly.
5. Row-by-row diff vs pre-state snapshot: **only** `(8, created_at, None → '2026-09-26 16:59:22')`;
   every other cell byte-identical; no rows added/removed.

## 6. Legacy script retirement

- Reference search across `*.py,*.md,*.txt,*.json,*.yaml,*.bat,*.ps1,*.sh,*.cfg,*.ini,*.toml`:
  **zero executable consumers** (no import/exec/invocation) — only historical doc mentions
  (`db-canonical.md`, `femis-separation-audit.md`, phase 3B.7/3B.8/3B.9 docs) and two
  comments in `test_students_null_created_at.py`.
- **Decision: retire (delete) `insert_test_record.py`.** Justification: its sole purpose
  (seeding "Ahmed Khan") is obsolete (Ahmed exists as the designated test student), it was
  the only NULL producer, it would be schema-invalid post-migration, and the separation
  audit already flagged it as an unwanted raw writer.
- `insert_test_record.py` deleted (79 lines, tracked as ` D`, not staged). Older docs still
  mention it — they are historical phase records and were intentionally not rewritten; the
  deletion is documented here.

## 7. Migration procedure

Official SQLite table-rebuild (sqlite.org "Making Other Kinds Of Table Schema Changes"),
single transaction, `PRAGMA foreign_keys` state captured (0) and left at 0:

1. Capture DDL, table_info, index SQL, FK lists, row data (record: temp
   `p3b10_migration_record.json`).
2. Build `students_new` DDL = old DDL with exactly one change:
   `created_at DATETIME` → `created_at DATETIME NOT NULL` (verified: replacement is
   reversible; old/new differ only by NOT NULL + temp table name).
3. `INSERT INTO students_new <141 explicit columns> SELECT <141 columns> FROM students`
   → 6/6 rows copied.
4. `DROP TABLE students` → `ALTER TABLE students_new RENAME TO students`.
5. Recreate `uq_students_b_form` verbatim from recorded SQL.
6. `PRAGMA foreign_key_check` → 0 violations → `COMMIT`.

A first attempt errored safely (`table students already exists` — the temp-name replace was
missing); the transaction rolled back and a state check confirmed zero side effects before
the corrected run.

## 8. Migration verification (26/26)

`p3b10_migrate.py` checks — highlights:

- `created_at` `notnull=1`, DDL declares `DATETIME NOT NULL`.
- Column count 141 → 141; table_info identical except `created_at.notnull`
  (types/defaults/pk all unchanged).
- Index list byte-identical (all 8), `uq_students_b_form` SQL identical.
- FK list identical; FK pragma state unchanged (0).
- students 6 rows, ids unchanged; bot_jobs 0; integrity ok; no `students_new` leftover.
- Student rows byte-identical to pre-migration snapshot; every `updated_at` non-NULL.
- Raw `INSERT` with `created_at NULL` rejected (`NOT NULL constraint failed`), no row left.

## 9. Model alignment

`femis-web/app.py:39`:

```python
created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
```

One-line change; no other model/schema/route change. `db.create_all()` does not alter
existing tables, so runtime behavior depends on the migrated database (as verified below).
Empirical pre-3B.9 finding preserved: column default fires even on explicit
`created_at=None` in ORM create payloads (4c confirms: `Student(created_at=None)` stores the
default, never NULL).

## 10. Fixture refits (purpose preserved, names unchanged)

**`test_created_at_creation_paths.py`** (10 → 11 checks, 11/11):

- D1 was "raw insert produces NULL" → now "raw insert **rejected** by NOT NULL schema, no
  row" (+ new D1b: explicit-NULL insert also rejected).
- D2 was "Ahmed still NULL (no backfill)" → now "Ahmed = documented backfill value".
- A1/A2, B1/B2, B3, C1/C2, E1 unchanged in intent (all still pass).

**`test_students_null_created_at.py`** (8 → 11 checks, 11/11): the NULL-rendering scenario
is impossible post-migration, so the file was refit to the same purpose under the new
invariant: 0 NULL rows in the live DB; raw INSERT (omitted / explicit NULL) rejected;
ORM-created row carries a real timestamp; `/students`, `/success/<id>` and the student JSON
endpoint still render/serve; cleanup restores baseline. Filename kept as instructed.

## 11. New integrity suite

**`test_created_at_not_null_integrity.py`** — 26/26, three angles:

1. Schema: `table_info notnull=1`, DDL `NOT NULL`, 141 columns.
2. Data: 0 NULL rows; ids `[3,4,6,8,9,10]`; Ahmed locked to `2026-09-26 16:59:22`;
   all `updated_at` non-NULL.
3. Rejection: raw omitted/NULL inserts rejected, no partial rows; ORM insert with
   explicit NULL rejected; `Student(created_at=None)` never stores NULL; production
   `save-tab` create path still works with `created_at: null` in payload (default wins).
4. Structural locks: index set + `uq_students_b_form` SQL + FK list + exactly 3 tables +
   bot_jobs 0 + probe accounting; `integrity_check` ok; `foreign_key_check` clean.

## 12. Fresh-process verification (12/12)

Brand-new interpreter (`p3b10_fresh_verify.py`), independent of the test files:

- Fresh `import app`; model `nullable is False`; default still `datetime.utcnow`.
- Runtime schema `notnull=1`; 0 NULL rows.
- `GET /students`, `/success/8`, `/students/8/json` → 200; `GET /` → 302 (auth redirect,
  expected); Ahmed rendered with `26 Sep 2026`; JSON `created_at` non-null
  (`Sat, 26 Sep 2026 16:59:22 GMT`).
- Fresh process: NULL insert rejected by schema.

## 13. Full regression (11 suites, all green, each run individually)

| # | Suite | Result |
|---|---|---|
| 1 | `test_bot_job_schema.py` | **62/62** |
| 2 | `test_bot_job_api.py` | **124/124** |
| 3 | `test_data_integrity.py` | **24/24** |
| 4 | `test_submission_status.py` | **12/12** |
| 5 | `test_bot_job_api_isolation.py` | **13/13** |
| 6 | `smoke_test.py` | **14/14** |
| 7 | `smoke_test_bot.py` | **3/3** |
| 8 | `test_bot_job_bot_integration.py` | **54/54 checks** |
| 9 | `test_students_null_created_at.py` | **11/11** |
| 10 | `test_created_at_creation_paths.py` | **11/11** |
| 11 | `test_created_at_not_null_integrity.py` | **26/26** |

Total: 354 checks passing, 0 failures, 0 regressions vs the 3B.7–3B.9 baselines.

## 14. Before / after schema

| | Before | After |
|---|---|---|
| DDL (students) | `CREATE TABLE students (` … `created_at DATETIME,` … | `CREATE TABLE "students" (` … `created_at DATETIME NOT NULL,` … |
| Diff | — | exactly two lines: name quoting added by `ALTER TABLE … RENAME`, and `NOT NULL` added |
| `created_at` flags | `notnull=0`, default NULL | `notnull=1`, default NULL |
| Columns / indexes / FKs / tables | 141 / 8 / 2 / 3 | **identical** |
| NULL rows | 1 (id 8) | **0** |
| bot_jobs | 0 rows | 0 rows |

(Full DDL text: `docs/phase3b10-pre-migration-state.json` → `students_table_info`, and
temp `p3b10_final_audit.json` → `students_ddl`.)

## 15. Final DB state

- **SHA-256: `725c3eb0bc27d04db31d362a149b0bb816d3238bcd1b623016e53cb61f595f07`**
  (pre-migration: `71064b82…dadb946`).
- 6 students `[3,4,6,8,9,10]`; Ahmed `created_at = 2026-09-26 16:59:22`; **0 NULL**;
  all `updated_at` non-NULL; `bot_jobs` 0; `journal_mode=delete`; `foreign_keys` default 0.
- `PRAGMA integrity_check` = ok; `PRAGMA foreign_key_check` = clean.
- Only difference vs pre-state snapshot: id 8 `created_at None → '2026-09-26 16:59:22'`.
- Final audit: 22/22 (`p3b10_final_audit.py`).

## 16. Rollback evidence & procedure

- Backup: `backup/2026-09-26/phase3b10-pre-migration/femis.db` — re-verified at the end:
  byte-identical to the recorded pre-state hash, opens read-only, `created_at notnull=0`,
  exactly NULL id 8 among 6 students, bot_jobs 0, integrity ok.
- Rollback = stop the app, copy the backup over `femis-web/instance/femis.db` (no
  `-wal`/`-shm` to reconcile, journal mode `delete`), restart. Model `nullable=False` would
  then only reject ORM NULL writes — the legacy test rows would still need no migration.
- Retained after success as required (not deleted).

## 17. Files changed / created / deleted / untouched

**Modified this phase:**

- `femis-web/app.py` — `created_at` gains `nullable=False` (line 39; pre-existing dirty
  lines from earlier phases unchanged).
- `test_created_at_creation_paths.py` — D1/D1b/D2 refit, docstring updated (untracked test
  file from 3B.9).
- `test_students_null_created_at.py` — full refit to post-migration invariant (untracked
  from 3B.7).

**Created this phase:**

- `docs/phase3b10-pre-migration-state.json`
- `docs/phase3b10-created-at-backfill-decision.md`
- `docs/phase3b10-created-at-not-null-migration.md` (this file)
- `test_created_at_not_null_integrity.py`

**Deleted this phase:**

- `insert_test_record.py` (tracked → ` D`, not staged).

**Database mutations:** one backfill UPDATE (id 8 only) + table-rebuild migration
(students only). Teachers/bot_jobs untouched; probe rows from test runs all cleaned up
(baseline ids `[3,4,6,8,9,10]` restored after every suite).

**Untouched:** `femis-web/templates/form.html`, `femis-web/static/form.js`,
`src/form_filler.py`, `src/job_runner.py`, `src/job_api_client.py`, `femis-web/job_api.py`,
`config/field_mapping.yaml`, auth code, bot selectors, portal layout, all other phase docs
and test files.

## 18. Git state

- HEAD `6871f81`, branch `main`. **Nothing staged, nothing committed.**
- Working tree: prior-phase dirty lines + this phase's `D insert_test_record.py`,
  `M femis-web/app.py` (1 line), the two refit test files, and the new docs/test files.

## 19. Deferred / out of scope (unchanged from plan)

- CNIC paging remains deferred (3B.7 decision).
- `list.html`/`success.html` null-guards (3B.7) kept as defense-in-depth — now unreachable
  for `created_at` since no NULL row can exist.
- Historical docs referencing the retired script left as-is (superseded by this doc).
- PythonAnywhere deployment, auth redesign, B-Form uniqueness UX: untouched.

## 20. Verdict & next session anchor

**Phase 3B.10 — PASS.**

- Final invariant holds: `students.created_at IS NOT NULL` for every row **and** the SQLite
  schema itself rejects NULL (`NOT NULL constraint failed: students.created_at`), proven by
  raw sqlite3, ORM, and fresh-process probes.
- 11/11 suites green (354 checks); fresh-process verification 12/12; final audit 22/22;
  migration verification 26/26; backfill 5/5.

**Next session anchor (single task):** obtain an explicit user decision on committing the
accumulated working tree (phases 3B.1–3B.10: `app.py`, templates, bot API files, tests,
docs, and the `insert_test_record.py` deletion) — then, only if approved, stage a clean
commit. Do not start new features before that decision.
