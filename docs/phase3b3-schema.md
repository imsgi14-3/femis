# Phase 3B.3 — Schema Implementation (students.updated_at + bot_jobs)

Status: **implemented (schema only)**. No API, no bot claiming, no routes changed.
Authority: decisions in `phase3b2-2-final-design-decisions.md` (A–O).

## What changed

| File | Change |
|---|---|
| `femis-web/app.py` | `Student.updated_at` column; new `BotJob` model (table `bot_jobs`); schema bootstrap block moved after model registration (it previously ran before any model existed, so `db.create_all()` created nothing on import); `updated_at` ALTER + backfill added to the existing lightweight migration |
| `test_bot_job_schema.py` | new schema-only test suite (61 checks) |
| `backup/2026-09-24/phase3b3-pre-migration/femis.db` | pre-migration backup (SHA-256 `34ce9c3c…e50f1a`, byte-identical to live DB at backup time) |
| `docs/phase3b3-pre-migration-state.json` | recorded pre-state: tables, 140 student columns, 7 students `[3,4,6,7,8,9,10]`, 1 NULL `created_at` |

No migration framework exists in this repo (no Alembic/Flask-Migrate), so the project's
existing pattern was extended: `db.create_all()` + `PRAGMA table_info()` + `ALTER TABLE`
in `app.py` (same mechanism that added `sub_sector_id`).

## students.updated_at

- UTC, naive (`datetime.utcnow`), same convention as `created_at`.
- Set by `default=` on insert, bumped by `onupdate=` on any ORM UPDATE (save-tab,
  final-submit, upload rename). Raw-SQL writes bypass `onupdate` (documented limitation;
  no such write path touches student rows today except `mark_processed`, which only
  touches `processed`).
- Backfill: `COALESCE(created_at, CURRENT_TIMESTAMP)` for all existing rows — migration
  time for the 1 row with NULL `created_at`; `created_at` elsewhere. **Migration time is
  not historical edit time** (decision E: this is a version marker, not an audit trail).
- Version/staleness marker only. It does NOT replace bot-job snapshots — snapshots are
  materialized separately at claim time (decision A).

## bot_jobs — one row per attempt (one-to-many per student)

30 columns. Field classification:

**Required (identity/lifecycle)**
`id`, `student_id` (FK→students, ON DELETE CASCADE), `attempt_number` (>=1), `status`
(default `pending`), `created_at`.

**Snapshot/version (materialized at claim; NULL until then)**
`student_data_version`, `snapshot_json` (immutable JSON TEXT), `snapshot_materialized_at`.
CHECK: `snapshot_json` requires `student_data_version` (never store a snapshot without the
version it was taken against).

**Claim/lease (values runtime-configurable — not baked into schema)**
`claimed_by`, `lease_expires_at`, `last_heartbeat_at`, `claim_generation` (fencing token,
default 0). No hard-coded 15s/60s/20min anywhere (decision K).

**Progress**
`current_tab`, `last_completed_tab`.

**Failure/outcome**
`failure_category` (CHECK: the 10 approved taxonomy values or NULL), `failed_tab`,
`failed_field`, `error_message`, `outcome_known` (Boolean, NULL allowed pre-completion),
`bot_result_code`.

**Success evidence (DB-enforced — `fill_success` is never success)**
`finish_clicked`, `indicator_detected`.
CHECK: `status='success'` requires `outcome_known=1 AND finish_clicked=1 AND indicator_detected=1`
(COALESCE-guarded — SQLite treats NULL as pass, so NULLs are coerced to 0).

**Retry/audit (nullable — API phase will populate)**
`prior_attempt_id` (self-FK, ON DELETE SET NULL), `created_by`, `requested_at`,
`retry_requested_at`, `idempotency_key` (UNIQUE; multiple NULLs allowed by SQLite).

### Constraints

| Constraint | Enforces |
|---|---|
| `uq_bot_jobs_student_attempt` UNIQUE(student_id, attempt_number) | stable attempt numbering; retry = new row, never overwrite |
| `uq_bot_jobs_open_per_student` UNIQUE(student_id) WHERE status IN ('pending','claimed','running') | **at most one open job per student, race-safe at DB level** (decision C) |
| `ck_bot_jobs_status` | exactly the 6 statuses: pending, claimed, running, success, failed, cancelled — no `retrying`/`fill_only`/`unknown_outcome` (decisions D, J) |
| `ck_bot_jobs_failure_category` | the 10-value taxonomy or NULL (decision I) |
| `ck_bot_jobs_attempt_number` | attempt_number >= 1 |
| `ck_bot_jobs_success_evidence` | success ⇒ Finish + indicator + outcome known (decision F) |
| `ck_bot_jobs_snapshot_requires_version` | snapshot ⇒ version present (decision A) |
| FK student_id → students.id | job cannot reference missing student |
| FK prior_attempt_id → bot_jobs.id | retry chain integrity |

Uncertain outcome = `status='failed'` + `outcome_known=0` (decision H) — allowed by schema.
Lease expiry, claim CAS, heartbeat cadence, retry scheduling are **runtime behavior for
Phase 3B.4+ — not implemented here.**

### Indexes

- `uq_bot_jobs_open_per_student` (partial unique, above)
- `ix_bot_jobs_status_created` — queue listing by status
- `ix_bot_jobs_lease` — (status, lease_expires_at) reclaim scans
- `ix_bot_jobs_student_created` — history per student (plus implicit student_id index)
- UNIQUE(student_id, attempt_number) auto-index

## Migration record

- Pre-state: `docs/phase3b3-pre-migration-state.json` (SHA-256 before: `34ce9c3ccef009d966d67a95e187277e92622a9afb9b95e1509bb58914e50f1a`)
- Backup: `backup/2026-09-24/phase3b3-pre-migration/femis.db` (identical SHA-256)
- Post-state: students 141 columns (140 + `updated_at`), `updated_at` NULL count 0,
  students/teachers untouched (7 rows, IDs `[3,4,6,7,8,9,10]`), `bot_jobs` created with
  all constraints verified by constraint-level probes (both in `test_bot_job_schema.py`
  and an independent pre-release verification script).

## Tests

- `test_bot_job_schema.py` — **61/61** (schema-only; cleans up all rows it creates)
- Baseline regression — **53/53** (`test_data_integrity` 24, `test_submission_status` 12,
  `smoke_test` 14, `smoke_test_bot` 3), unchanged, none modified

## Out of scope (Phase 3B.4+, explicitly NOT done)

API endpoints, job creation/cancel, claim/heartbeat/retry runtime, DATA_STALE handling,
roles/auth, admin UI, `form.js`/portal/mapping changes, auto job on final-submit.
