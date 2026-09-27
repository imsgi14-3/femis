# Phase 3B.2.1 — Bot-Job API Design Decisions

**Mode:** DESIGN ONLY — documentation only  
**Date:** 2026-09-24  
**Branch:** `main` (HEAD: `6871f81`)  
**Inputs:** `docs/phase3b1-data-contract-audit.md`, `docs/phase3b2-bot-job-api-contract.md`, `docs/femis-separation-audit.md`, live repo inspection (`app.py`, `settings.yaml`, `main.py`, schema)  
**Scope:** Resolve the 10 unresolved questions from 3B.2 §18.  
**Hard rule:** No application/bot code, no `field_mapping.yaml`, no `bot_jobs`, no schema/migrations, no API endpoints, no auth/deployment changes, no test changes, no portal/FEMIS behavior changes, no commits.  
**Only expected repository change:** this file — `docs/phase3b2-1-design-decisions.md`.

**Evidence honesty:** Where the repo does not establish a value or mechanism, text is marked **`[ASSUMPTION — needs later verification]`**. Nothing below is claimed as measured production performance unless cited from code/config.

---

## 0. Repo facts used as evidence (inspection summary)

| Fact | Evidence |
|---|---|
| Student model has `created_at`, **no `updated_at`** | `femis-web/app.py` Student model; no `updated_at` hits in model |
| Roles in portal session | `student`, `teacher` only — **no `admin` role** in `app.py` / login |
| Save path does not bump a version token | `/api/save-tab`, `/api/final-submit` set columns + `submitted`; no version column |
| Canonical DB | `femis-web/instance/femis.db` tables: `students`, `teachers` only |
| Bot completion rule | `is_submission_success` + `classify_student_result` (Finish **and** indicator → `success`; fill-only → `fill_success`) |
| Fill-only today | CLI `submit: bool` / `--submit`; not a portal job mode |
| Config knobs (bot) | `portal.timeout=30000`, `captcha.max_retries=3`, `batch.delay_between_students=2000`, Finish wait `timeout=15000` ms in `form_filler` |
| Separation audit proposals | `students.updated_at` additive; `max_attempts DEFAULT 3`; ~30s heartbeat example; `DATA_STALE` as 409 |
| Field contract | Frozen per 3B.1 (FORM_FIELD_MAP + WebFormHandler + PORTAL_NAME_ALIASES) |

---

## Decision 1 — Snapshot timing

### 1.1 Question
Materialize the immutable student snapshot at **job creation**, at **job claim**, or with a hybrid/version-checked approach?

### 1.2 Options considered
- **A. Snapshot at create** — freeze when portal enqueues.  
- **B. Snapshot at claim** — freeze when worker takes the job.  
- **C. Hybrid** — version checked at create; snapshot materialized at claim (or create) under a recorded version; bot never reads live rows mid-attempt.

### 1.3 Evidence
- 3B.1: live `read_by_id` works but student can edit anytime (partial updates, no lock by default).  
- 3B.2: chose Option C envelope (`student_id` + `student_data_version` + snapshot); timing left open.  
- Separation audit: bot should see `students.updated_at` at claim (`student_updated_at_seen`).  
- **No** existing `updated_at` on `students` today → cannot detect mid-queue edits without a future mechanism.

### 1.4 Decision
**Hybrid — snapshot materialized at claim time (Option C, claim-time freeze), with version token recorded at materialization.**

1. Create job: store `student_id`, `idempotency_key`, `requested_at`, status `pending`, and optionally record `student_data_version_at_request` if available (nullable until `updated_at` exists).  
2. **Claim:** atomically read canonical student row **once**, build immutable snapshot (3B.1 key space), set `student_data_version` + `student_updated_at_seen`, return snapshot with claim response.  
3. All progress/complete for that `attempt` use **that snapshot**; bot does not re-read `students` for field values mid-attempt.  
4. If live student version ≠ job’s recorded version at claim, see Decision 10 (`DATA_STALE`).

### 1.5 Rationale
- **Create-time freeze** wastes snapshots for jobs cancelled/retried before work; holds possibly large payloads for long queues; student often still editing until they explicitly request bot job.  
- **Claim-time freeze** guarantees the worker gets a coherent row at the moment exclusive lease is acquired (single-writer friendly), maximizes chance data is “as of work start,” and keeps create cheap.  
- **Immutability after claim** satisfies “bot must not silently process a different version than associated with the job.”  
- Aligns with 3B.2 hybrid envelope + audit’s `student_updated_at_seen` at claim.

### 1.6 Consequences
- Two jobs for the same student at different times can have different snapshots (desired).  
- Create API need not load full student payload (privacy/latency).  
- Attempt isolation is per-claim, not per-create.  
- Without `updated_at`, claim-time “version” falls back to Decision 7’s minimum mechanism.

### 1.7 Implementation must be true
- Snapshot is **immutable for the attempt** after claim succeeds.  
- Claim response includes snapshot + `student_data_version`.  
- Bot never calls portal student APIs for field values during a claimed run (except optional student metadata already in snapshot).  
- Steal/lease-expiry starts a **new claim** → **new snapshot materialization** (or explicit re-freeze), never silent reuse of a stolen worker’s in-memory copy as authoritative without new claim record.

---

## Decision 2 — One open job per student

### 2.1 Question
Multiple pending jobs per student, one open job, or one open job with historical attempts?

### 2.2 Options considered
- Multiple concurrent pending jobs.  
- Strict one open job.  
- One open job + immutable history of terminal jobs/attempts.

### 2.3 Evidence
- 3B.2 §5 recommended “one active job per student.”  
- Separation audit proposed `bot_jobs` **1:1 UNIQUE student_id** (single row lifecycle, not multi-row history).  
- Today: unlimited duplicate processing risk (no claim at all) — audit critical risk.  
- Historical attempt audit is valuable for dashboard (“attempt N of M”).

### 2.4 Decision
**One open job per student; multiple historical terminal jobs allowed if using multi-row history.**

**Definition of “open” (normative):**

> A job is **open** iff `status ∈ {pending, claimed, running}`.  
> (`cancelled`, `failed`, `success` are **closed**.)

**v1 storage choice (design):** Prefer **multi-row job history** with uniqueness enforced only among open jobs:

- Unique partial index / app rule: at most one row per `student_id` where status is open.  
- Terminal rows retained for audit (optional retention policy later).

**If a single-row job table is chosen instead** (audit’s 1:1 sketch): history lives only in attempt counters + last error on that row — **less auditability**; still enforce at most one logical open lifecycle. Multi-row preferred for Decision 9–10 audit trails.

### 2.5 Behavior matrix

| Event | Behavior |
|---|---|
| **Duplicate create** (same `idempotency_key`) | Return existing job; no new row |
| **Duplicate create** (new key, open job exists) | **409** conflict — return existing open job id; do not enqueue second |
| **Failed job (closed)** | Does **not** block a new create **unless** product wants forced retry path only — **Decision:** allow new create only after prior is `failed` with `retryable=false` **or** operator used **retry** on same job; default: **new create allowed only if no open job**; retry preferred over parallel new job for same data intent |
| **Retry** | Reuses **same** `job_id` → `pending`; does not create a second open job |
| **Successful job (closed)** | New create allowed only if product explicitly wants re-submit — **v1 default: block new open job while latest success exists unless operator creates with explicit `force_new=true`** **`[ASSUMPTION — force_new flag not in repo; needs product approval]`**. Safer default: **allow** new job only for a new student data version after human confirmation — **v1: require admin/operator confirmation flag** (Decision 8). |
| **Operator retry on failed** | Same job_id → pending (see Decision 9) |
| **Stale/expired claimed job** | Still **open** (`claimed`/`running` with expired lease) → **still blocks** new create; only claim-steal may proceed |

### 2.6 Rationale
Prevents concurrent double-fill of FEMIS while preserving failure/retry history.

### 2.7 Consequences
Create API must check open-job uniqueness. Dashboard shows latest open or latest terminal.

### 2.8 Implementation must be true
- Open-set definition as above.  
- Atomic create-or-conflict.  
- Retry never opens a second concurrent job for the same student.

---

## Decision 3 — Lease and heartbeat defaults

### 3.1 Question
Initial lease duration, heartbeat interval, grace, max execution time?

### 3.2 Options considered
- Audit example ~30s heartbeat.  
- Values derived from FEMIS bot wall-clock waits.  
- Empirically measured production values.

### 3.3 Evidence
- **No measured lease metrics in repo.**  
- Bot wall-clock anchors: Finish indicator wait **15s**; portal navigation timeout **30s**; inter-student delay **2s**; captcha retries **3**; a full 7-tab run can take **minutes** (not measured in CI).  
- Separation audit mentioned ~30s heartbeat as example only.

### 3.4 Decision — **initial implementation defaults** (not production-measured)

| Parameter | Initial default | Label |
|---|---|---|
| **Heartbeat interval** | **15 seconds** | Initial default |
| **Lease duration** | **60 seconds** | Initial default |
| **Heartbeat grace** (allow 1 missed beat before steal eligibility visible) | **Implicit in 60s lease** — steal only when `lease_expires_at < now` | Initial default |
| **Max job execution duration** (server-side) | **20 minutes** → force `failed(timeout)` / reject progress | Initial default **`[ASSUMPTION — no repo upper bound on full run]`** |

**Rationale vs bot workflow:**
- Heartbeat **15s** ≤ Finish wait **15s** and ≤ portal timeout **30s** → a single FEMIS wait does not by itself expire a 60s lease if the worker heartbeats on a background loop (**implementation assumption:** heartbeat is concurrent with Playwright waits, not blocked on the UI thread).  
- Lease **60s** = 4× heartbeat → survives brief GC/network blips without immediate steal.  
- Max **20 min** bounds zombie `running` rows; actual fill usually shorter **`[ASSUMPTION]`**.

### 3.5 Rationale
Values are **compatible** with existing timeouts but are **not** claimed as empirically tuned.

### 3.6 Consequences
Configurable in job-store settings later; clocks must be UTC/server-trusted.

### 3.7 Implementation must be true
- Heartbeat runs **independently** of Playwright awaits.  
- Steal uses server clock only.  
- Defaults documented as config keys, not hard-coded magic, when implemented.

---

## Decision 4 — `cancelled` in v1

### 4.1 Question
First-class `cancelled`, failed-with-reason, or defer from v1?

### 4.2 Options considered
- First-class state.  
- `failed` + `failure_category=cancelled_by_operator` only.  
- Defer cancel entirely.

### 4.3 Evidence
- Operational need: stop a **queued** job so bot will not claim it — `failed` is a poor fit (implies attempt error).  
- 3B.2 allowed optional `cancelled` from `pending`/`claimed`.  
- Running cancel races FEMIS (unknown Finish) — must not fake success.

### 4.4 Decision
**Retain first-class `cancelled` in v1 for `pending` only; for `claimed`/`running`, v1 does not support forced cancel mid-FEMIS.**

| State | Cancel allowed? |
|---|---|
| `pending` | **Yes** → `cancelled` |
| `claimed` | **No in v1** (work may already be on FEMIS; wait for terminal or lease outcomes) **`[ASSUMPTION — product may later want soft-abort]`** |
| `running` | **No in v1** |
| `failed` / `success` / `cancelled` | No |

**Who:** **admin/operator only** (Decision 8) — not student; not bot.  
**Race with claim:** cancel is CAS `pending → cancelled`; if claim wins first, cancel → **409**.  
**Race with completion:** N/A if cancel only from `pending`.  
**Retry from cancelled:** allowed by admin → `pending` (optional; same as failed retry gate).

### 4.5 Rationale
Need exists for queue stop without lying about bot execution; running abort cannot be honest without bot-side cooperative cancel (out of v1).

### 4.6 Consequences
Operators cannot kill a stuck worker via status alone — lease/timeout (Decision 3) handles stuck `running`.

### 4.7 Implementation must be true
- CAS on `pending` only.  
- Dashboard shows Cancelled distinctly from Failed.  
- No path `running → cancelled` in v1 state table.

---

## Decision 5 — `fill_only` mode

### 5.1 Question
Should v1 support jobs that only fill FEMIS without official Finish?

### 5.2 Options considered
- Full `mode=submit` | `mode=fill_only` in v1.  
- Defer fill_only; v1 jobs are submit-only.  
- Allow fill_only but map fill completion to job `success` (**rejected** — violates semantics).

### 5.3 Evidence
- Phase 2 / 3B.1: **fill-only is never `success`** (`fill_success`).  
- Bot already has `--submit` flag; fill-only runs exist **outside** job system.  
- **No portal/product requirement** in repo for enqueued fill-only jobs.  
- Separation audit: fill-only must never yield job COMPLETED/success.

### 5.4 Decision
**Defer `fill_only` from v1 job API.**

- v1 job `mode` is fixed **`submit`** (or field omitted and treated as `submit`).  
- Bot may still run local dry-run/`--submit=false` for manual ops — **those do not create job `success`**; if a job exists, fill-only outcome maps to **`failed`** (or job never uses fill-only).  
- No API field `mode=fill_only` in v1.

### 5.5 Rationale
No concrete v1 requirement; prevents accidental success redesign; keeps state machine single-purpose.

### 5.6 Consequences
Future fill_only needs a **different terminal success definition** (e.g. `fill_completed`) — explicitly **not** `success`.

### 5.7 Implementation must be true
- Reject `mode=fill_only` in create (400) until a later phase.  
- `bot_result_code=fill_success` never sets job `status=success`.  
- Tests keep 12/12 status semantics.

---

## Decision 6 — Claim mechanism

### 6.1 Question
Same-host DB atomic claim (A), HTTP API claim (B), or hybrid (C)?

### 6.2 Options considered
- **A** SQL CAS on shared SQLite.  
- **B** HTTP claim on Job API.  
- **C** Same semantics, transport selectable (SQL when co-located, HTTP when split).

### 6.3 Evidence
- Target architecture: Portal → Job API/Store → independent Bot (3B.2 §1).  
- PythonAnywhere portal vs local bot already cross-host (separation audit).  
- Simplicity of A must not lock architecture.

### 6.4 Decision
**Hybrid transport (C) with HTTP as the normative cross-host contract; concurrency primitive is identical.**

| Deployment | Claim transport |
|---|---|
| Same host (transitional) | Atomic SQL CAS on job table **implementing the same state machine** |
| Split hosts (target) | **HTTP `POST .../claim`** with bot token |

**Concurrency primitive (required regardless of transport):**

> Compare-and-set transition  
> `open status → claimed` **or** steal only if `lease_expires_at < now`  
> with single-writer row update; success iff **exactly one** claimant wins; losers get **409**.

### 6.5 Rationale
Preserves independent deployability; avoids same-host-only design.

### 6.6 Consequences
Two transports must share one state machine test suite later.

### 6.7 Implementation must be true
- No SELECT-then-UPDATE race.  
- HTTP and SQL paths equivalent under concurrency tests.  
- Bot never claims without CAS.

---

## Decision 7 — Version token

### 7.1 Question
`updated_at`, content hash, explicit integer, or other?

### 7.2 Options considered
- `students.updated_at` datetime (audit proposal).  
- Monotonic integer `data_version`.  
- Content hash of canonical columns.  
- Use existing `created_at` only.

### 7.3 Evidence
- **`students.updated_at` does not exist today**; only `created_at`.  
- `created_at` never changes on edit → **useless** as edit detector.  
- No version integer in schema.  
- Separation audit already justifies additive `updated_at` touched on every save-tab/final-submit.  
- Content hash possible but heavier and needs stable serialization of 140 columns.

### 7.4 Decision
**Primary: additive `students.updated_at` (UTC datetime) touched on every portal write path that mutates student fields (`save-tab`, `final-submit`, legacy `submit`, file upload if it changes student row).**

- Job stores `student_data_version` as **ISO-8601 of `updated_at`** (opaque string to bot).  
- Also store `student_updated_at_seen` for staleness compares (same value at snapshot).  
- **Content hash:** optional secondary integrity check later — **not required for v1**.  
- **Explicit integer:** not chosen (more invasive than datetime for this codebase).  
- **Until `updated_at` exists:** version token is **unavailable** — claim must either (a) block job system until migration, or (b) use snapshot-only with `student_data_version=null` and rely on Decision 10 conservative path. **v1 job system requires `updated_at` migration first** (implementation prerequisite).

### 7.5 Rationale
Matches audit design; minimal additive column; compares cleanly for `DATA_STALE`.

### 7.6 Consequences
Migration must backfill `updated_at = created_at` where null; all write paths must touch it (**implementation assumption:** easy to miss `/submit` and upload).

### 7.7 Implementation must be true
- Every student-row mutation bumps `updated_at`.  
- Clock consistency: store UTC; compare on server.  
- Job snapshot records the token used.

---

## Decision 8 — Roles / retry & cancel authority

### 8.1 Question
Who may create, claim, heartbeat, progress, complete, retry, cancel, inspect diagnostics?

### 8.2 Options considered
- Reuse student/teacher only.  
- Add admin/operator role.  
- Bot token only for bot ops; portal roles for human ops.

### 8.3 Evidence
- Portal roles today: **`student` | `teacher`** — **no admin**.  
- Teacher: class/section scope, lock/unlock.  
- Student: own row only.  
- Bot: needs machine identity (3B.2 §12) — **not implemented**.  
- Retry/cancel of **global** job queue exceeds single-teacher class scope **`[ASSUMPTION — product may accept teacher-retry for own class]`**.

### 8.4 Decision — minimum role matrix (design; **auth not modified this phase**)

| Operation | student | teacher | admin/operator **(future)** | bot token |
|---|---|---|---|---|
| Create job | **No** (portal may auto-create later only under approved product rule — **v1: not student-direct**) | **Yes**, own class/section students | **Yes** | No |
| Get job / view diagnostics | Own student projection only **`[ASSUMPTION]`** | Own class | **Yes** | Own claimed job |
| List pending | No | No | **Yes** | **Yes** |
| Claim / heartbeat / progress / complete | No | No | No | **Yes** (lease holder) |
| Request retry | No | **Optional v1: No** (defer) | **Yes** | No |
| Cancel (`pending` only) | No | No | **Yes** | No |
| Stats | No | Class-limited optional | **Yes** | No |

**v1 human create/retry/cancel authority: `admin/operator` only**, until an admin role exists.  
**Dependency:** portal currently has **no admin role** — **future implementation dependency**: add operator/admin capability (or out-of-band ops tool) **before** exposing retry/cancel in UI. Teacher may later gain create-for-class after approval.

**Bot** never uses student/teacher sessions.

### 8.5 Rationale
Students must not enqueue FEMIS submissions ad hoc; bot must be machine-identified; repo lacks admin → must be called out.

### 8.6 Consequences
Auth work is a hard prerequisite for human retry/cancel endpoints.

### 8.7 Implementation must be true
- Enforce matrix at API boundary.  
- Document admin role addition as separate approved change (not done here).  
- No silent reuse of student session for bot claims.

---

## Decision 9 — Retry / backoff ownership

### 9.1 Question
Who owns `max_attempts`, retryable rules, backoff; is auto-retry in v1?

### 9.2 Options considered
- Job system / API owns policy.  
- Bot worker owns retries internally.  
- Operator-only manual retry.  
- Hybrid: bot internal short retries for transient UI; job-level attempts owned by job store.

### 9.3 Evidence
- Separation audit: `max_attempts DEFAULT 3`; after max → FAILED until human requeue.  
- Bot already has **internal** captcha retries (3) and edit-mode save retry — operational, not job attempts.  
- No backoff table in repo.  
- Unknown Finish must not auto-retry (3B.2 §5).

### 9.4 Decision
**Hybrid ownership:**

| Layer | Owns | v1? |
|---|---|---|
| **Job store / API** | `attempt`, `max_attempts`, `retryable` derivation, **operator-triggered** retry (`failed → pending`) | **Yes** |
| **Bot worker** | In-attempt transient retries (click/save/captcha) that do **not** increment job `attempt` | **Yes** (existing behavior) |
| **Automatic job-level requeue** (system backoff loop) | Auto `failed → pending` without human | **No in v1** |
| **Backoff schedule between job attempts** | Config when auto-retry exists later | Deferred with auto-retry |

**Defaults (implementation config — approval required to change):**

- `max_attempts`: **3** (matches separation audit default **`[not measured in production]`**).  
- `retryable=true` only if: `attempt < max_attempts` **AND** `failure_category` in retry-allowed set (3B.2 §9) **AND** `outcome_known ≠ false` for Finish-uncertain failures.  
- **After max attempts:** `status=failed`, `retryable=false`, terminal until **admin operator** resets (explicit `force_retry` that resets attempt or increments beyond max **`[ASSUMPTION — needs product rule]`**).

### 9.5 Rationale
Bot already retries micro-steps; job-level auto-retry risks duplicate FEMIS submits; audit prefers human requeue at max.

### 9.6 Consequences
v1 queue drains only via success, terminal fail, or human retry.

### 9.7 Implementation must be true
- Job `attempt` increments on **claim**, not on every Playwright click retry.  
- Auto-retry off by default flag `auto_retry_enabled=false`.  
- Unknown outcome never auto-retryable.

---

## Decision 10 — `DATA_STALE` behavior

### 10.1 Question
When snapshot/version ≠ current student record version: auto-requeue, fail for review, auto new job, or other?

### 10.2 Options considered
- **A** Automatically requeue with fresh data.  
- **B** Fail/`409 DATA_STALE` and require review.  
- **C** Automatically create a new job.  
- **D** Ignore / continue with old snapshot.

### 10.3 Evidence
- Student edits during bot run are possible (no default lock).  
- Blind reprocess can duplicate FEMIS submissions or fill outdated data.  
- Separation audit mentioned requeue **or** `DATA_STALE` flag — not settled.  
- 3B.2: progress may 409 `DATA_STALE`; auto reprocess not proven safe.

### 10.4 Decision — **v1: Option B (fail closed for that attempt)**

| Moment | Behavior |
|---|---|
| **At claim** | If live `updated_at` ≠ expected (or create-time token mismatches policy), still may snapshot **live** value as new attempt input **only if** job was `pending` with no prior attempt — record new version. If job is **retry of failed** and student changed since prior snapshot: **require operator choice** — default **do not auto-use new data without explicit `refresh_snapshot=true` on retry**. |
| **During running (progress/heartbeat sees version advanced)** | **409 `DATA_STALE`** — job transitions to **`failed`**, `failure_category`/`detail=DATA_STALE`, `retryable=true` only via operator with explicit snapshot refresh. **No automatic requeue.** |
| **At complete success** | If version advanced mid-run: still record success evidence for what was submitted **but** set `stale_input=true` flag for review **`[ASSUMPTION — completing may still be correct if FEMIS already accepted]`** — **do not** auto-start another job. |
| **Option A/C rejected for v1** | Auto requeue/new job could double-submit FEMIS. |

**Operator path:** retry with `refresh_snapshot=true` → new claim materializes **new** snapshot and new `student_data_version`.

### 10.5 Rationale
Auditability and avoiding accidental duplicate FEMIS submissions outweigh convenience; student edits are intentional signals requiring human or explicit refresh decision.

### 10.6 Consequences
Dashboard must surface `DATA_STALE` clearly; portal may warn “student edited while processing.”

### 10.7 Implementation must be true
- Compare tokens server-side on progress/complete.  
- Never silently swap snapshot mid-attempt.  
- No auto A/C in v1 code paths.

---

## 11. Final decision matrix

| # | Question | Decision | v1? | Implementation consequence |
|---|---|---|---|---|
| 1 | Snapshot timing | **Hybrid; materialize at claim; immutable per attempt** | Yes | Claim loads student once; stores version+snapshot |
| 2 | One open job/student | **Yes — open = pending\|claimed\|running; multi-row history preferred** | Yes | Partial unique index / create 409; retry reuses job_id |
| 3 | Lease/heartbeat | **HB 15s, lease 60s, max run 20min — initial defaults, not measured** | Yes | Async heartbeat; server clock; config keys |
| 4 | Cancelled | **First-class; cancel only from `pending`; admin only** | Yes | CAS pending→cancelled; no running→cancelled |
| 5 | Fill-only | **Deferred; jobs are submit-only; fill_success ≠ success** | Yes (submit-only) | Reject mode=fill_only; status tests unchanged |
| 6 | Claim mechanism | **Hybrid transport; HTTP normative cross-host; CAS primitive** | Yes | Same state machine for SQL + HTTP |
| 7 | Version token | **`students.updated_at` (missing today → migration prerequisite)** | Yes (needs migration) | Touch on all student writes; ISO token on job |
| 8 | Roles | **Bot token for bot ops; admin/operator for retry/cancel; no student create; no admin role in portal yet** | Partial | **Auth dependency:** add operator capability before UI retry/cancel |
| 9 | Retry/backoff | **Job store owns attempts; max_attempts=3 default; no auto job-retry in v1; bot keeps micro-retries** | Yes | retryable derivation; force_retry later |
| 10 | DATA_STALE | **Fail closed 409/failed; operator refresh_snapshot retry; no auto requeue/new job** | Yes | Stale checks on progress/complete |

---

## 12. Ready for implementation

Settled enough for a future implementation phase **after** explicit go-ahead on the overall implementation sequence (3B.2 §15):

1. Snapshot-at-claim + immutable attempt input  
2. One open job per student (open-state definition)  
3. Lease/heartbeat initial defaults (configurable)  
4. `cancelled` only from `pending`  
5. v1 submit-only (no fill_only job mode)  
6. Hybrid claim with shared CAS primitive  
7. `updated_at` as version token (**requires additive migration**)  
8. Retryable/attempt rules with **no auto job-level retry** in v1  
9. `DATA_STALE` fail-closed + explicit snapshot refresh  
10. Success still only Finish + indicator (unchanged from Phase 2/3B.1)

## 13. Still requires explicit approval

Do **not** treat these as decided by repository evidence alone:

1. **Admin/operator role existence** and who holds it (portal has no admin today).  
2. **Whether teachers may create/retry jobs for their class** in v1.  
3. **Product rule for new job after `success`** (`force_new` / always allow / never).  
4. **Exact `max_attempts` and whether 3 is approved** (audit default, not measured).  
5. **Whether heartbeat can truly run parallel to Playwright** in the chosen worker design (implementation verification).  
6. **20-minute max execution** bound (assumption).  
7. **Multi-row history vs 1:1 single-row** physical schema (design prefers multi-row; audit sketched 1:1).  
8. **Auto-create job on portal final-submit** vs explicit operator/teacher action only (3B.2 pending = explicit request — confirm product).  
9. **Force-retry after attempts exhausted** semantics.  
10. **PythonAnywhere / deployment schema remediation** — still out of band (`students.address` = deployment mismatch, not auth).

---

## 14. Preserve existing architecture (unchanged)

This phase does **not** alter:

| Area | Status |
|---|---|
| Portal field identities / `FORM_FIELD_MAP` | **Unchanged** (3B.1 frozen) |
| Canonical student DB semantics | **Unchanged** (except future approved `updated_at` — **not added now**) |
| Phase 2 persistence fixes (Tab7, transport, refugee, disability, `[]`) | **Unchanged** |
| Phase 2 submission-success semantics (`fill_success` / `success` / `submit_failed` / `error`) | **Unchanged** |
| FEMIS selectors | **Unchanged** |
| `field_mapping.yaml` | **Unchanged** |
| CAPTCHA handling | **Unchanged** |
| Existing portal authentication | **Unchanged** (no auth code) |
| Existing FEMIS bot behavior | **Unchanged** |

No architectural drift: decisions only refine the **future** job API design.

---

## 15. Verification

| Check | Result |
|---|---|
| `test_data_integrity.py` | 24/24 |
| `test_submission_status.py` | 12/12 |
| `smoke_test.py` | 14/14 |
| `smoke_test_bot.py` | 3/3 |
| **Total** | **53/53** |
| Tests modified | **None** |
| New file this phase | `docs/phase3b2-1-design-decisions.md` only |
| Implementation files changed by 3B.2.1 | **None** |
| DB schema | Unchanged; tables still `students`, `teachers`; **no `bot_jobs`** |
| API routes `/api/bot*` | **None** |
| Commits | **None** |

**Pre-existing dirty tree (Phases 2 / 3A / 3B.1 / 3B.2 docs — not this phase):**  
`audit_portal.py`, `config/field_mapping.yaml`, `femis-web/app.py`, `femis-web/static/form.js`, `femis-web/templates/form.html`, `smoke_test.py`, `src/data_sources/webform_handler.py`, `src/form_filler.py`, `src/main.py`, untracked `docs/*` (incl. 3B.1, 3B.2), `smoke_test_bot.py`, `test_data_integrity.py`, `test_submission_status.py`.

---

## 16. Stop conditions

- [x] Documentation only  
- [x] No `bot_jobs` / schema / endpoints / auth / tests / commits  
- [x] All 10 questions answered with evidence or marked **`[ASSUMPTION]`**  
- [x] Architecture preserved  

**STOP.** Await approval before any implementation of 3B.2 §15 sequence.
