# Phase 3B.4 — Admin-only Bot-Job API

**Status:** Implemented and tested (2026-09-26). Store/lifecycle layer only.
**Authority:** `docs/phase3b2-bot-job-api-contract.md`, `docs/phase3b2-1-design-decisions.md`,
`docs/phase3b2-2-final-design-decisions.md` (decisions A–O), `docs/phase3b3-schema.md`,
Phase 3B.4 brief.
**Code:** `femis-web/job_api.py` (blueprint), registered in `femis-web/app.py`.
**Tests:** `test_bot_job_api.py` — 123/123. Regressions unchanged: schema 61/61,
data integrity 24/24, submission status 12/12, smoke 14/14, bot smoke 3/3.

No browser automation, no bot execution, no auto-job on `/api/final-submit`, no admin UI,
no FEMIS credentials, no schema changes, no commits.

---

## 1. Endpoints

Base path: `/api/jobs` (per the 3B.4 brief; the 3B.2 contract draft used `/api/bot-jobs`
— deviation recorded in §8).

### Human/operator endpoints (focal person)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/jobs` | Create job (optional `idempotency_key`, `mode` must be `submit`) |
| GET | `/api/jobs` | List (`student_id`, `status`, `order`, `limit`, `offset`) |
| GET | `/api/jobs/<id>` | Job detail (never `snapshot_json`) |
| POST | `/api/jobs/<id>/retry` | New attempt from `failed`/`cancelled` (`refresh_snapshot`) |
| POST | `/api/jobs/<id>/cancel` | `pending` → `cancelled` (CAS) |

### Bot-machine endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/jobs/claim` | `pending` → `claimed`: CAS + version check + snapshot (one transaction) |
| POST | `/api/jobs/<id>/heartbeat` | Extend lease, prove liveness |
| POST | `/api/jobs/<id>/progress` | `claimed` → `running` on first update; tab/field diagnostics |
| POST | `/api/jobs/<id>/complete` | Terminal `success` (evidence) or structured `failed` |

## 2. Authentication model

Two independent gates, both fail-closed, both constant-time compared
(`hmac.compare_digest`). Tokens are never echoed in any response.

**Operator (human) — `_require_operator()`:**
1. No session → `401 authentication_required`
2. `session.role != "teacher"` → `403 forbidden_role` (portal has no admin role —
   decision E; the operator boundary is teacher session + token)
3. `FEMIS_OPERATOR_TOKEN` unset/empty → `403 operator_token_not_configured`
4. Missing/wrong `X-Operator-Token` → `403 operator_token_invalid`

**Bot (machine) — `_require_bot()`:**
1. `FEMIS_BOT_TOKEN` unset/empty → `403 bot_token_not_configured`
2. Missing/wrong `X-Bot-Token` → `401 invalid_bot_token`

Cross-credential tests (A9/A10) prove the two realms cannot substitute for each other.
Keys are placeholders in `.env.example`; real values live only in gitignored `.env`.

## 3. Lifecycle / state machine

```
pending ──claim (CAS)──► claimed ──progress──► running ──complete──► success
   │                        │                    │              └───► failed
   │                        └──(lease/fence applies to claimed+running)
   └──cancel──► cancelled
```

- Every transition is a compare-and-swap or an explicit status guard; terminal rows are
  immutable except an idempotent duplicate completion (same claimant + generation +
  outcome → `200 {"idempotent": true}`).
- A different outcome on a terminal job → `409 invalid_transition`.
- `retry` never mutates history: it appends `attempt_number = max+1` with
  `prior_attempt_id` set and `retry_requested_at` stamped.
- v1 lease steal does **not** exist: `claim` only takes `pending` rows (gap in §8).

## 4. Claim transaction (CAS → version → snapshot)

Single DB transaction, in this order:

1. **CAS** `UPDATE … SET status='claimed', claimed_by=?, claim_generation=gen+1,
   lease_expires_at=now+lease WHERE id=? AND status='pending'`. Rowcount 0 → `409
   claim_conflict` (loser rolls back, job stays claimable).
2. **Version check** against `students.updated_at` (exact microsecond compare). Mismatch
   or missing student → job marked `failed` with the DATA_STALE representation below;
   claim returns `409 error_code="DATA_STALE"`; nothing is materialized.
3. **Snapshot** from raw `SELECT * FROM students` (key space matches
   `WebFormHandler.read_by_id`): drops `id/created_at/updated_at/processed`, defensively
   strips password/token/secret/credential-named keys, adds the
   `transport_facility` alias. Stored once per attempt in `snapshot_json`; returned only
   in the claim response envelope
   `{student_id, version, materialized_at, data}`. Later student edits never rewrite it
   (verified: D8).

`student_data_version` accepts ISO-8601 (microsecond-exact when a fraction is present)
and RFC-822 HTTP-date (second precision, what `/students/<id>/json` emits).

## 5. DATA_STALE representation (no schema change)

| Field | Value |
|---|---|
| `status` | `failed` |
| `failure_category` | `validation` (approved taxonomy) |
| `bot_result_code` | `DATA_STALE` (machine-readable marker) |
| `outcome_known` | `true` (no FEMIS work started) |
| `lease_expires_at` | `null` |
| `snapshot_json` | `null` (never materialized) |
| `error_message` | `DATA_STALE: expected <v1>, current <v2>.` |
| API | `409 {"error_code": "DATA_STALE", "job": {...}}` (`data_stale: true` in job dicts) |

## 6. Lease and fencing (runtime config, not design constants)

- `FEMIS_JOB_LEASE_SECONDS` (dev default **60**) — claim sets, heartbeat/progress extend.
- `FEMIS_JOB_HEARTBEAT_SECONDS` (dev default **15**) — reported to the bot in heartbeat
  responses as guidance; not enforced server-side in v1.

Heartbeat, progress and complete all require the live claimant
(`claimed_by` + `claim_generation` fencing token):

- Wrong claimant or stale generation → `409 fencing_conflict`
- Expired/absent lease → `409 lease_expired`
- Non-active status → `409 invalid_transition`
- Missing `claimed_by`/`claim_generation` → `422 validation_error`

Superseded workers can therefore never heartbeat, progress, fail, or complete a job.

## 7. Completion evidence rules

**Success (`outcome="success"`)** requires ALL of:
`bot_result_code="success"` AND `finish_clicked=true` AND `indicator_detected=true`
AND `outcome_known=true`. Otherwise → `422 missing_success_evidence` (or
`422 fill_only_is_not_success` for `fill_success`, `422 validation_error` for any other
code). The DB CHECK `ck_bot_jobs_success_evidence` is the backstop.

**Failure (`outcome="failed"`)** requires the approved `failure_category` and an explicit
boolean `outcome_known`; optional structured diagnostics (`failed_tab`, `failed_field`,
`last_completed_tab`, `error_message`, `bot_result_code`, boolean flags). Invalid values
are rejected *before* any mutation (validation-then-write ordering).

`fill_success` is a valid **failed** outcome (`H9`), never a success.

## 8. Known gaps / deviations (reported, not resolved here)

1. **Path naming:** implemented `/api/jobs` per the 3B.4 brief; 3B.2 drafted
   `/api/bot-jobs`. `/api/bot/jobs` returns 404 (L5).
2. **Retry contract contradiction:** 3B.2.1 said "retry reuses job_id"; 3B.2.2 and the
   brief require a new attempt row. Implemented new-attempt (history immutable).
3. **No lease steal (v1):** a `claimed`/`running` job whose lease expired and whose
   worker died cannot be re-claimed; operator must `cancel` (only possible from
   `pending`!) — i.e. **an expired open job is currently unrecoverable without a schema-
   level intervention**. Needs a v1.1 decision: allow cancel-from-expired and/or
   lease-steal claim.
4. **No progress-detail column:** `current_field`/`detail` are persisted as sanitized
   `progress: tab=… field=… …` lines appended to `error_message` (capped 1000 chars).
   A dedicated column would be cleaner (schema change deferred).
5. **No admin list endpoint for the bot:** bot can only claim-next or claim-by-id (as
   specified); operators list via GET `/api/jobs`.
6. **`max_attempts=3` withdrawn** — no attempt cap; retry unbounded (per decision).
7. **No DATA_STALE schema value** — represented via `bot_result_code` (§5).
8. **Teacher-create row vs operator token:** create requires both a `teacher` session
   *and* `X-Operator-Token`; the session's `user_name` is recorded as `created_by`.
9. **Lease numbers are env-configurable**, documented as runtime config rather than
   frozen design constants.

## 9. Test coverage (`test_bot_job_api.py`, 123 checks)

- **A (11)** — full auth matrix, both fail-closed directions, cross-credential rejection.
- **B (12)** — create, duplicate, version mismatch/missing/unknown, mode, idempotency
  replay, RFC-822 token, no-snapshot-at-create.
- **C (10)** — list/get, filters, validation, ordering, safe fields, no `snapshot_json`.
- **D (9)** — claim-next, CAS claim, already-claimed/terminal/unknown, DATA_STALE,
  snapshot content + immutability, create-blocked-while-claimed.
- **E (8)** — heartbeat lease extension, fencing (claimant/generation), terminal job,
  expired lease blocks all three bot ops, supersession, unknown job.
- **F (8)** — claimed→running, tabs, progress lines, stale/invalid payloads, status
  cannot be injected.
- **G (11)** — success evidence rules, fill-only rejection, idempotent duplicate,
  superseded completion, terminal immutability for all four endpoints.
- **H (9)** — failure taxonomy validation, structured failure storage, uncertain outcome,
  superseded failure, fill_success-as-failure.
- **I (11)** — retry from failed/cancelled, prior immutability, refresh semantics both
  ways, blocked from success/open/claimed, unknown id, open-job guard.
- **J (5)** — cancel pending/terminal/claimed/unknown + cancel-vs-claim race.
- **K (4)** — concurrent create, double claim, double complete, claim-next race.
- **L (9)** — final-submit creates no job, login/form routes unchanged, legacy path 404,
  GET→405, canonical DB path, stale root DB absent, no secret leakage.
- **M (3)** — cleanup: jobs 0, students removed.

Every artifact the suite creates is deleted by the suite (plus a `finally` safety net);
verified canonical DB: 7 students, 0 jobs, 0 NULL `updated_at`, 0 leftover test rows.
