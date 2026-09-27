# Phase 3B.2 — Bot-Job API Contract (Design Specification)

**Mode:** DESIGN ONLY — no implementation  
**Date:** 2026-09-24  
**Branch:** `main` (HEAD at design start: `6871f81`)  
**Predecessor:** `docs/phase3b1-data-contract-audit.md` (verified field contract; 53/53 suites + 74/74 synthetic trace)  
**Prior architecture notes:** `docs/femis-separation-audit.md` (§D–G: `bot_jobs`, state machine, API shapes — aligned below where Phase 3B.1 evidence still holds)

**Out of scope (hard rules for this phase):** no `bot_jobs` table; no schema/migration; no Flask/API endpoints; no edits to `app.py`, `form.js`, `main.py`, `form_filler.py`, `webform_handler.py`, `field_mapping.yaml`; no auth/deployment/FEMIS-selector changes; no workers/queues; no commits.  
**Only repository change expected:** this file — `docs/phase3b2-bot-job-api-contract.md`.

---

## 0. Status of this document

| Item | Value |
|---|---|
| Artifact type | Design specification (normative for a future phase) |
| Implements code | **None** |
| Adds DB objects | **None** |
| Adds HTTP endpoints | **None** |
| Changes portal/student UX | **None** |
| Replaces Phase 3B.1 field mapping | **No** — field contract is frozen as verified |

Where this design and Phase 3B.1 disagree, **Phase 3B.1 wins for field identity and write semantics**. This document only specifies job lifecycle, ownership, and a future transport API.

---

## 1. Architectural boundary

### 1.1 Target diagram

```text
Student Portal
    |
    | student record + bot-job request
    v
Bot Job API / Job Store
    |
    | claimed job (+ frozen input reference)
    v
Independent FEMIS Bot
    |
    | official FEMIS interaction
    v
FEMIS
```

### 1.2 Process/application separation

| Application | Responsibility | Must not own |
|---|---|---|
| **Student Portal** (`femis-web`) | Collect/edit student data; canonical `students` row; authorize who may request a bot job; display human-facing job status | Browser automation, FEMIS selectors, CAPTCHA, browser/session state, FEMIS credentials, `field_mapping.yaml`, bot retries |
| **Bot Job API / Job Store** | Job lifecycle, claim/lease, progress/failure records, idempotency keys, dashboard queries | Rendering student forms; validating portal business rules beyond “may enqueue”; FEMIS interaction |
| **Independent FEMIS Bot** (`src/`) | Claim work; read frozen student payload; fill/Finish on FEMIS; classify completion; report job outcomes | Portal HTML/JS; portal auth; portal form validation; changing student-facing form structure; portal layout |

The portal and the bot remain **separate applications/processes**. They may share a host temporarily (same-SQLite transitional mode from the separation audit), but the **contract** is the API + job store, not ad-hoc SQL from the bot into portal tables.

### 1.3 Information the portal must not need

- Browser automation details  
- FEMIS selectors / DOM structure  
- CAPTCHA solving  
- Browser or FEMIS session state  
- FEMIS credentials / Gemini keys  
- `field_mapping.yaml` implementation (labels, `source_field` trees, notes)  
- Bot retry internals (backoff tables, internal attempt policies beyond published counters)

### 1.4 Information the bot must not become responsible for

- Rendering the student portal  
- Collecting or editing student data  
- Portal authentication (student/teacher sessions)  
- Portal form validation / `mandatoryByTab`  
- Changing student-facing form structure or layout  
- Portal final-submit semantics (`students.submitted` remains portal-owned)

### 1.5 Field contract (frozen from 3B.1 — not redesigned here)

Bot input keys remain the **canonical DB / yaml `source_field` space** already verified:

- Renames via `FORM_FIELD_MAP` (e.g. `transport_facility`→`transport`, `refugee_card_number`→`refugee_card`, `present_address`→`present_address_other`, …)  
- `WebFormHandler` injects `transport_facility` from `transport`  
- `PORTAL_NAME_ALIASES` maps bot keys → portal `input[name]` (e.g. `digital_device_type`→`digital_device_type[]`)  
- Multi-values stored as CSV in SQLite; treated as arrays only at the form.js/yaml boundary  

No contradiction was found that would require redesigning that mapping in 3B.2.

---

## 2. Job lifecycle (state machine — design only)

### 2.1 Primary states

```text
pending ──claim──► claimed ──start──► running ──finish_ok──► success
   ▲                  │                  │
   │                  │ lease_lost       │ finish_err / crash after lease
   │                  ▼                  ▼
   └────retry──────── failed ◄───────────┘
                        │
                        └──(attempts exhausted / non-retryable)──► failed (terminal)

optional: pending|claimed|running ──cancel──► cancelled
```

| State | Created by | Transitions out (who) | Meaning | Retry? | Must retain |
|---|---|---|---|---|---|
| **pending** | Portal (on explicit bot-job request, not automatically on portal final-submit) | → **claimed** (bot worker via API); → **cancelled** (authorized human) | Queued; no worker holds a lease; student data may still change until snapshot policy freezes it | n/a (initial) | `job_id`, `student_id`, `requested_at`, `idempotency_key`, input version refs |
| **claimed** | Bot (successful claim/lease) | → **running** (same worker); → **pending** (lease expiry / another claim after steal); → **failed** (claim aborted) | Exactly one worker holds a lease; work not yet reporting tab progress | Lease expiry returns to claimable | `claimed_at`, `claimed_by`, `lease_expires_at`, `attempt` |
| **running** | Bot (explicit start/first progress) | → **success** (bot, only Finish+indicator); → **failed** (bot or lease takeover); → **pending** (stale lease) | Active fill/submit attempt with heartbeat | Same as failed rules on abort | `started_at`, `current_tab`, `last_completed_tab`, `last_heartbeat_at`, progress fields |
| **success** | Bot (only via `complete_success`) | terminal (or admin-only reopen = new job / explicit new attempt — not silent overwrite) | **Official Finish clicked AND completion indicator verified** | No auto-retry | `completed_at`, evidence flags (`finish_clicked`, `indicator_detected`), attempt, student data version |
| **failed** | Bot or system | → **pending** via authorized **retry** iff retry policy allows; else terminal | Attempt ended without verified FEMIS success | Conditional | `failure_category`, `failed_tab`, `failed_field`, `error_message` (sanitized), `attempt`, timestamps |

### 2.2 States deliberately not added as first-class statuses

| Candidate | Decision | Rationale |
|---|---|---|
| `retryable_failure` | **Not a separate status** | Represented as `status=failed` + `retryable=true` (or `next_action=requeue`). Avoids dual vocabularies overlapping `failed`. |
| `permanently_failed` | **Not a separate status** | Represented as `status=failed` + `retryable=false` (attempts exhausted or non-retryable category). Terminal-ness is a flag, not a parallel enum. |
| `cancelled` | **Optional but justified** | Needed if a human/admin must stop enqueue work **before** FEMIS success is known without lying about bot outcome. Allowed from `pending` and `claimed` (if not yet materially affecting FEMIS). From `running`, prefer bot abort → `failed(category=cancelled_by_operator)` so history stays truthful. |
| `fill_success` / `submit_failed` as **job** statuses | **Not job statuses** | These are **bot attempt result codes** from Phase 2/3B.1 (`classify_student_result`). Map them into job `failed` + `failure_category` / `notes`, never into job `success`. Job success ≠ fill-only. |

### 2.3 Success semantics (non-negotiable)

A job **must NOT** become `success` merely because:

- portal fields were filled on FEMIS, or  
- a browser opened, or  
- FEMIS accepted some tabs, or  
- a fill/`Save & Next` operation completed, or  
- portal `students.submitted == true`, or  
- bot logged `fill_success`.

**True job success** requires the existing authoritative rule:

> official Finish action **and** verified FEMIS completion indicator  
> (`form_filler.is_submission_success(finish_clicked, indicator_detected)` / `classify_student_result` → `success`).

| Bot attempt result | Job status | Notes |
|---|---|---|
| `success` | **success** | Only mapping allowed to `success` |
| `fill_success` | **failed** (or still `running` only if still mid-attempt — default: `failed` with category `femis`/`incomplete_submit`) | Fill-only never completes a bot job that requested submit |
| `submit_failed` | **failed** (`femis`) | Finish requested, indicator not verified |
| `error` | **failed** (category per taxonomy) | |
| `dry_run` | **failed** or never creates a production job | Dry-run is not production success |

If the job was created for **fill-only mode** (optional future flag `mode=fill_only`), success definition must be explicitly documented as fill-complete **without** claiming FEMIS submission — default design assumes **`mode=submit`** and the Finish+indicator rule.

---

## 3. Job object (minimum record)

Fields are classified before any schema discussion. **This phase does not create columns.**

### 3.1 Classification table

| Field | Class | Required? | Why retain |
|---|---|---|---|
| `job_id` | identity | **Required** | Primary key for all API ops and audit |
| `student_id` | identity | **Required** | Link to portal-owned canonical record (FK logically; not enforced in this phase) |
| `requested_at` | input/version | **Required** | When portal enqueued work; audit + SLA |
| `requested_by` | input/version | Useful | Role/id of portal actor (student/teacher/admin) — authorization audit |
| `idempotency_key` | input/version | **Required** | Dedupe repeated create-job client retries |
| `student_data_version` | input/version | **Required** | Opaque version token for the student row used as input (e.g. `students.updated_at` ISO or monotonic counter — choice deferred to implementation phase) |
| `snapshot_ref` / embedded snapshot | input/version | **Required if Option B/C** | See §4 — what the bot actually reads |
| `mode` | input/version | Useful | `submit` (default) vs `fill_only` — changes success rule |
| `attempt` | retry/concurrency | **Required** | Starts at 1 on first claim; increments per claim |
| `max_attempts` | retry/concurrency | Useful | Policy bound; default e.g. 3 — config not specified here |
| `retryable` | retry/concurrency | Derived | Derived from `failure_category` + `attempt < max_attempts` |
| `status` | execution | **Required** | `pending\|claimed\|running\|success\|failed\|cancelled` |
| `claimed_at` | execution | Derived on claim | When lease acquired |
| `claimed_by` | execution | **Required if multi-worker** | Worker id (e.g. `hostname:pid` or API client id) |
| `lease_expires_at` | execution | **Required if lease model** | Crash/Network recovery |
| `last_heartbeat_at` | execution | **Required if lease model** | Liveness |
| `started_at` | execution | Useful | First `running` timestamp |
| `completed_at` | execution | **Required** | Terminal timestamp for success/failed/cancelled |
| `current_tab` | progress | Useful | Live progress (1–7) |
| `last_completed_tab` | progress | Useful | Resume/checkpoint |
| `failed_tab` | progress | Useful | Human diagnosis |
| `failed_field` | progress | Useful when known | Human diagnosis; may be null |
| `tabs_completed` | progress | Derived | `last_completed_tab` or count — prefer derive, do not dual-store unless denormalized for dashboard |
| `failure_category` | progress/failure | **Required on failed** | Controlled enum (§8) |
| `failure_detail` | progress/failure | Useful | Machine-safe subcode (optional) |
| `error_message` | progress | Useful | **Human-readable, sanitized** — never secrets |
| `bot_result_code` | progress | Useful | Preserve `success\|fill_success\|submit_failed\|error\|dry_run` for fidelity |
| `finish_clicked` / `indicator_detected` | progress | **Required on success** | Evidence for success rule |
| `student_updated_at_seen` | retry/concurrency | **Required** | Detect portal edits during/after claim (staleness) |
| `idempotent complete token` | retry/concurrency | Useful | Allows duplicate complete_* posts |

**Not job fields (owned elsewhere):** FEMIS credentials, browser session, selectors, CAPTCHA tokens, Playwright state, portal passwords, full HTML snapshots of FEMIS.

### 3.2 Storage guidance (design only)

- **Required** fields above are the minimum durable job record.  
- **Derived** fields should be computed in queries where possible (`retryable`, counts).  
- **Implementation-specific** (heartbeat SQL interval, JSON blob vs columns for progress) deferred to implementation phase.  
- Do **not** auto-create any of this until a later approved migration phase.

---

## 4. Input semantics (choice among Options A/B/C)

### 4.1 Options compared

| Criterion | **A: `student_id` only** (bot reads canonical DB/API) | **B: full immutable snapshot** in job | **C: hybrid** — job stores `student_id` + `student_data_version` + snapshot (or claim-time materialization) |
|---|---|---|---|
| Consistency | Weakest: student may edit between enqueue and read | Strong: frozen bytes/values | Strong once snapshot attached; version detects pre-snapshot edits |
| Auditability | Poor: cannot prove what bot saw | Excellent | Excellent |
| Retry behavior | Retry may silently pick up new student edits (good or bad?) | Retry replays same data unless new job | Policy explicit: same snapshot vs re-freeze on `updated_at` change |
| Race conditions | High (write during run) | Low for input; student still can edit portal (portal truth diverges from job) | Version token surfaces divergence (`DATA_STALE`) |
| Privacy / exposure | Bot needs broad read of `students` | Snapshot only for that job | Snapshot scoped to claimed job; bot need not list all students |
| Portal↔bot independence | Bot coupled to portal DB path or full-table API | High | High |
| Schema evolution | Bot breaks if portal columns change silently | Versioned snapshot shape isolates bot | Version field + documented snapshot schema (logical field IDs from 3B.1) |
| Alignment with 3B.1 | Matches **today’s** `WebFormHandler.read_by_id` | Matches 3B.1 §9.2 “snapshot of finalized payload” | **Best match** to 3B.1 future-API proposal + separation audit |

### 4.2 Chosen design: **Option C (hybrid)**

**Choice:** Job envelope is hybrid:

1. **Always:** `student_id`, `student_data_version` (token captured when snapshot is taken).  
2. **At create or at claim (implementation choice, document either):** materialize an **immutable input snapshot** using the **verified Phase 3B.1 key space** (DB/`source_field` keys, CSV multi-values as stored, `transport_facility` alias injection rules matching `WebFormHandler`).  
3. **Bot execution** reads **the snapshot**, not live `students`, for that attempt.  
4. **Staleness:** if portal `student_data_version` advances after snapshot, API can mark progress calls `DATA_STALE` or force a new job — does not silently mutate mid-run input.

**Rationale tied to 3B.1:**

- 3B.1 proved field identity and partial-update behavior for live DB reads — snapshot content **must use that same contract**, not a new mapping.  
- 3B.1 §9.2 already proposed the bot consume a snapshot keyed by logical field IDs and keep aliases on the bot side.  
- Same-host transitional mode may still allow bot → direct read (Option A) **without** API, but the **normative future contract is C**; A is a deployment shortcut, not the target.

**Not implemented in 3B.2.**

---

## 5. Idempotency and duplicate protection (design)

| Scenario | Required behavior | Distinguishing information |
|---|---|---|
| **Duplicate job requests** (same student submitted twice) | Create is idempotent on `idempotency_key` **or** returns existing open job for same `student_id` while one is `pending\|claimed\|running` (policy: one active job per student recommended) | `student_id` + open-status uniqueness; client-supplied `idempotency_key` |
| **Repeated API create** (timeout retry) | Same `idempotency_key` → same `job_id`, no second row | Idempotency-Key header/field |
| **Bot crash after claim, before complete** | Lease expires; job becomes claimable again (`claimed`/`running` with expired lease → stealable). Attempt already counted | `lease_expires_at`, `attempt`, `claimed_by` |
| **Browser/FEMIS uncertainty** (bot cannot know if previous Finish landed) | **Do not mark success.** Mark `failed` with `failure_category` + `outcome_known=false` / human-review. Never invent success | `finish_clicked`, `indicator_detected` must both be true for success; else `unknown_outcome` |
| **Retry after failure** | Only if `retryable`; increments `attempt`; may re-snapshot or reuse snapshot per policy | `attempt`, `max_attempts`, `failure_category`, `student_data_version` |

### 5.1 Safety classes

| Class | Meaning | API rule |
|---|---|---|
| **Safe retry** | Known non-start on FEMIS, or known failed before Finish click, or idempotent re-run with probe/edit-mode resume **and** category allows | `failed` + `retryable=true` → `pending` |
| **Unsafe retry** | Outcome unknown after Finish may have occurred | Require human review (`failure_category=unknown_outcome`); no auto-retry |
| **Duplicate request** | Same idempotency key / same open job | Return existing job; **no** second concurrent claim |
| **Unknown FEMIS outcome** | Crash/network between Finish click and indicator check | Terminal-for-bot `failed` + `outcome_known=false`; success **forbidden** |

**Honesty constraint:** existing FEMIS behavior does **not** establish that blind retries after an uncertain Finish are safe (possible duplicate submission or partial server state). This design therefore **does not claim** such retries are safe.

---

## 6. Claiming / concurrency (design)

### 6.1 Flow

```text
GET/list pending jobs
        ↓
claim (atomic)
        ↓
lease + heartbeat
        ↓
run (progress updates)
        ↓
complete success | complete failure
```

### 6.2 Exclusion (two workers, one student)

- **At most one live lease** per `job_id` (and practically per `student_id` if one-job-per-student).  
- Claim is **compare-and-set**: transition `pending` → `claimed` **or** steal only when `lease_expires_at < now` and status in (`claimed`,`running`).  
- Second worker’s claim → **409 Conflict** (no job mutation).  
- Same-host SQL equivalent: single `UPDATE ... WHERE id=? AND status='pending'` (or lease-expired predicate) with rowcount check — design-level only.

### 6.3 Failure modes

| Event | Behavior |
|---|---|
| Lease expires | Job remains `claimed`/`running` in storage but is **claimable** by another worker; prior worker’s subsequent complete/progress → **409** unless it first renews a valid lease |
| Worker crashes | Heartbeat stops → lease expiry → steal → new `attempt` |
| Network disappears mid-run | Heartbeat fails; worker should locally abort → if it can report, `failed(network)`; if not, lease expiry |
| Worker reconnects | Must re-claim or present valid `claimed_by`+unexpired lease; cannot resume progress writes on expired lease without steal |
| Another worker sees expired job | May claim (steal); must treat prior FEMIS work as **unknown** until it probes/resumes; may not assume prior success |

**Design-only:** lease duration, heartbeat interval, and clock source left to implementation phase (examples in separation audit used ~30s heartbeat; not binding here).

---

## 7. API operations (minimum future surface)

No endpoints are implemented in 3B.2. Proposed surface stays small.

| Operation | Purpose | Caller | Request (essential) | Response (essential) | AuthN / AuthZ | Idempotency | Allowed transitions | Failure responses |
|---|---|---|---|---|---|---|---|---|
| **Create job** | Enqueue bot work | Portal server (on behalf of authorized user) | `student_id`, optional `idempotency_key`, `mode` | `job_id`, `status`, `student_data_version` | Portal session → service; **not** student forging arbitrary ids | Key or open-job dedupe | Creates **pending** only | 403 not owner/role; 404 student; 409 duplicate open job if no key |
| **Get job** | Read one job | Portal dashboard; bot (own claim); admin | `job_id` | Full public job view | Session or bot token scoped | n/a | none | 401/403/404 |
| **List pending** | Queue snapshot for workers | Bot | filters (`limit`) | `job_id`s + versions | **Bot token** | n/a | none | 401 |
| **Claim job** | Atomic lease | Bot | `job_id` or claim-next; `claimed_by` | `status=claimed`, lease, **input snapshot** | Bot token | Claim is naturally exclusive | `pending`→`claimed` (or expired steal) | **409** already claimed; 404 unknown |
| **Heartbeat** | Extend lease | Bot | `job_id`, `claimed_by` | `lease_expires_at` | Bot token + lease holder | Safe repeat | none (stays claimed/running) | 409 lease lost |
| **Progress** | Tab checkpoints | Bot | `job_id`, `current_tab`, `last_completed_tab`, optional `portal_mode` | ack + lease | Bot token + valid lease | Repeatable | `claimed`→`running`; `running`→`running` | 409 lease; 409 `DATA_STALE` if version advanced (policy) |
| **Complete success** | Terminal success | Bot | `job_id`, `finish_clicked=true`, `indicator_detected=true`, `bot_result_code=success`, timestamps | `status=success` | Bot token + valid lease | Duplicate complete → same success, 200/201 idempotent | `running`→`success` | **422** if evidence flags not both true; 409 lease |
| **Complete failure** | Terminal/failure attempt | Bot | `job_id`, `failure_category`, optional tab/field, `error_message`, `bot_result_code` | `status=failed`, `retryable` | Bot token + valid lease | Repeat last failure OK | `claimed\|running`→`failed` | 409 lease |
| **Request retry** | Requeue | Human/admin (portal) | `job_id` | `status=pending`, `attempt` unchanged until next claim | **Admin/teacher policy** (not bot) | Careful: one requeue | `failed`→`pending` if retryable | 409 not retryable / not failed |
| **Cancel** | Stop pre-success work | Human/admin | `job_id` | `status=cancelled` | Admin | n/a | `pending`→`cancelled`; limited from `claimed` | 409 if `success` or mid-FEMIS policy forbids |
| **Stats** (optional) | Dashboard counts | Portal | none | counts by status | Session/admin | n/a | none | 401/403 |

**Explicit non-goals:** HATEOAS, many resource sub-collections, public unauthenticated read, bot endpoints that mutate `students`.

**Transitional note (separation audit Phase 3):** same-host may implement the same **semantics** via atomic SQL on a future job table without HTTP; the operation set above remains the contract for cross-host (PythonAnywhere portal ↔ local bot).

---

## 8. Progress reporting model

### 8.1 Machine-readable fields (status logic may parse only these)

| Field | Type / example | Purpose |
|---|---|---|
| `status` | enum §2 | Queue/dashboard primary state |
| `attempt` / `max_attempts` | int | Retry display |
| `current_tab` | 1–7 \| null | “on which tab” |
| `last_completed_tab` | 0–7 | How far it got |
| `failed_tab` | 1–7 \| null | Failure location |
| `failed_field` | string \| null | When bot knows logical/DB field key |
| `failure_category` | enum §9 | Taxonomy |
| `failure_detail` | string \| null | Subcode |
| `outcome_known` | bool | Unknown FEMIS outcome flag |
| `bot_result_code` | Phase 2 enum | Fidelity to bot classifier |
| `retryable` | bool | UI “Retry” button enablement |
| `requested_at`, `claimed_at`, `started_at`, `last_heartbeat_at`, `completed_at` | timestamps | Timeline |
| `student_data_version` | string | Consistency display |

### 8.2 Human-readable diagnostic text

- Field: `error_message` (or `notes`) — free text for operators.  
- **Must not** be parsed to derive `status`, `failure_category`, or success.  
- **Must not** contain passwords, tokens, full URLs with secrets, CAPTCHA solutions, or raw stack traces with local paths if avoidable (sanitize at API boundary).

Dashboard derives: current status, latest attempt, completed tabs, failure location, error category, timestamps — **only** from machine fields + sanitized message.

---

## 9. Failure taxonomy (controlled)

Justified by existing bot architecture: portal/network login to FEMIS, Playwright browser errors, yaml field mapping/`source_field`, CAPTCHA path, Finish/indicator timeouts, validation of claimed student payload.

| `failure_category` | Meaning (existing architecture) | Retryable? | Human review? | Unknown outcome? |
|---|---|---|---|---|
| `validation` | Input snapshot missing required keys / wrong types before fill | Yes (after data fix) sometimes | Often | No |
| `field_mapping` | `source_field` missing, alias mismatch, portal rejects mapped value | Usually no until mapping fixed | **Yes** | No |
| `browser` | Playwright/browser crash, selector vanished mid-run | Yes with backoff | If repeated | Sometimes |
| `network` | Connectivity to FEMIS or API | Yes | If persistent | Only if Finish may have sent |
| `femis` | FEMIS app error, Save rejected, Finish rejected (`submit_failed`) | Limited | Yes after N | Only if indicator ambiguous |
| `captcha` | CAPTCHA solve limit / manual captcha required | Config-dependent | Often | No (usually pre-submit) |
| `timeout` | Explicit waits exceeded (progress, Finish indicator) | Yes if pre-Finish; else unknown | Yes if post-Finish | **Yes if post-Finish** |
| `auth_portal` | Job API auth failed (bot token) | After credential fix | Ops | No |
| `cancelled_by_operator` | Human cancel | n/a | No | No |
| `unknown` | Unclassified exception | Conservative: no auto-retry | **Yes** | **Yes** |

**Success is not a failure category.**  
**Never expose:** FEMIS credentials, Gemini keys, CAPTCHA tokens, browser dumps, `field_mapping.yaml` raw nodes.

Map bot codes:

| `bot_result_code` | Typical category |
|---|---|
| `submit_failed` | `femis` |
| `error` + network stack | `network` |
| `error` + selector stack | `browser` / `field_mapping` |
| `fill_success` on a submit job | `femis` (incomplete) or policy `failed` with detail `fill_only` |

---

## 10. Portal-facing status model (dashboard)

### 10.1 Display states (projection — not raw job enum duplication)

| Portal display | Derived from job store |
|---|---|
| **Not submitted to bot** | No job row for student (and/or portal never requested) |
| **Queued** | Latest job `status=pending` |
| **Processing** | `claimed` or `running` |
| **Completed** | Latest terminal job `status=success` |
| **Failed** | Latest job `failed` and not yet requeued |
| **Needs retry/review** | `failed` + (`retryable=true` or `outcome_known=false` or `failure_category` in human-review set) |

Portal **must not** depend on bot internals (selectors, yaml, browser). It only reads job projections + optional summary fields listed in §8.

### 10.2 Dashboard queries (conceptual)

- **Current status:** latest job by `student_id` ordered by `requested_at`/`attempt`  
- **Latest attempt:** `attempt`, `completed_at`  
- **Completed tabs:** `last_completed_tab`  
- **Failure location:** `failed_tab`, `failed_field`  
- **Error category:** `failure_category` (+ sanitized `error_message`)  
- **Timestamps:** §8.1  

**Distinct from portal flags:** `students.submitted` / `students.locked` remain “portal flow” only (3B.1) — dashboard label “Sent to FEMIS bot” must use **job status**, not `submitted`.

---

## 11. Data ownership

| Data | Owner |
|---|---|
| Student-entered data | Student Portal |
| Canonical student DB record (`students`) | Portal / canonical DB |
| Job lifecycle (status, attempts, lease) | Job system |
| Bot execution state (browser, local logs, screenshots) | Bot |
| FEMIS credentials | Bot runtime |
| FEMIS browser/session | Bot runtime |
| Field mapping implementation (`field_mapping.yaml`, aliases) | Bot |
| Final FEMIS completion evidence (`finish_clicked`, `indicator_detected`) | Bot (reported into job store) |
| Human-facing job status text/enums for dashboard | Job system |
| Input snapshot for an attempt | Job system (materialized from portal data via 3B.1 contract) |
| `students.submitted` / `students.locked` | Portal only |

**One writer per table rule (from separation audit, retained):** portal → `students`; job system/bot → job table; portal **reads** jobs for display; bot **does not** write `students`.

---

## 12. Security boundary (design only — no auth implementation)

| Concern | Design |
|---|---|
| Portal → API | Existing portal session (or internal service auth) for **create/get/request_retry/cancel/stats**; do not treat student session as sufficient for admin cancel |
| Bot → API | **Machine identity:** static bot token (header), mTLS, or private network — **not** student/teacher passwords |
| Authorization | Students never claim jobs; teachers/admins only see appropriate class scope if portal shows status; bot only claims `pending`/expired leases and updates **that** job |
| Job ownership | Every mutating bot op binds `job_id` + `claimed_by` + lease |
| Replay protection | HTTPS in deployment; idempotency keys on create; lease fencing tokens on progress/complete |
| Idempotency | Create and complete operations idempotent (§5) |
| Sensitive student data | Snapshot returned **only** to authenticated bot for claimed job; no list-all-students to bot via API if snapshot model used |
| Secrets | FEMIS/Gemini/CAPTCHA secrets only in bot runtime env — never in job store or API responses |
| Audit trail | Retain `requested_at/by`, `claimed_by`, attempts, terminal category, timestamps |

**Retained classification (3B.1):**  
`sqlite3.OperationalError: no such column: students.address` is a **deployment database-schema mismatch**, **not** an authentication diagnosis.  
**PythonAnywhere auth remediation is out of scope** for 3B.2 and must not be inferred from this design.

Portal session auth as it exists today is **not** declared sufficient for bot-job APIs; a separate bot identity and explicit authz rules are required before implementation.

---

## 13. API payload examples (documentation only)

Field names below use the **Phase 3B.1 verified** space where student data appears. Examples are not wired into application code.

### 13.1 Create job

```json
POST /api/bot-jobs
{
  "student_id": 9,
  "idempotency_key": "portal-final-submit-9-20260924T193000Z",
  "mode": "submit"
}
```

### 13.2 Create-job response

```json
{
  "ok": true,
  "job": {
    "job_id": "job_01J8...",
    "student_id": 9,
    "status": "pending",
    "attempt": 0,
    "requested_at": "2026-09-24T19:30:01Z",
    "student_data_version": "2026-09-24T19:29:58Z"
  }
}
```

### 13.3 Claim job (response includes snapshot)

```json
POST /api/bot-jobs/job_01J8.../claim
{ "claimed_by": "bot-host-1:4242" }
```

```json
{
  "ok": true,
  "job": {
    "job_id": "job_01J8...",
    "status": "claimed",
    "attempt": 1,
    "lease_expires_at": "2026-09-24T19:31:00Z",
    "student_data_version": "2026-09-24T19:29:58Z"
  },
  "student_snapshot": {
    "student_id": 9,
    "data": {
      "name": "AYAT MUBEEN",
      "transport": "Institution Bus",
      "transport_facility": "Institution Bus",
      "bus_route": "Route-99",
      "refugee_card": "REF-998877",
      "disability_types": "Visual,Hearing",
      "digital_device_type": "Mobile,Laptop",
      "digital_device_at_home": "1",
      "internet_at_home": "0",
      "other_conditions": "Asthma",
      "achievement_details": "Recitation",
      "last_class_result": "87.5",
      "address": "House 1 Street 2",
      "present_address_other": "Temporary address"
    }
  }
}
```

### 13.4 Progress update

```json
POST /api/bot-jobs/job_01J8.../progress
{
  "claimed_by": "bot-host-1:4242",
  "current_tab": 3,
  "last_completed_tab": 2,
  "portal_mode": "edit"
}
```

```json
{
  "ok": true,
  "job": {
    "status": "running",
    "current_tab": 3,
    "last_completed_tab": 2,
    "lease_expires_at": "2026-09-24T19:31:30Z"
  }
}
```

### 13.5 Successful completion

```json
POST /api/bot-jobs/job_01J8.../complete
{
  "claimed_by": "bot-host-1:4242",
  "outcome": "success",
  "bot_result_code": "success",
  "finish_clicked": true,
  "indicator_detected": true,
  "last_completed_tab": 7,
  "completed_at": "2026-09-24T19:40:12Z"
}
```

```json
{
  "ok": true,
  "job": {
    "status": "success",
    "completed_at": "2026-09-24T19:40:12Z",
    "attempt": 1
  }
}
```

### 13.6 Failed completion

```json
POST /api/bot-jobs/job_01J8.../complete
{
  "claimed_by": "bot-host-1:4242",
  "outcome": "failed",
  "bot_result_code": "submit_failed",
  "failure_category": "femis",
  "failed_tab": 7,
  "failed_field": null,
  "outcome_known": true,
  "finish_clicked": true,
  "indicator_detected": false,
  "error_message": "Finish clicked; completion indicator not detected",
  "completed_at": "2026-09-24T19:40:12Z"
}
```

```json
{
  "ok": true,
  "job": {
    "status": "failed",
    "failure_category": "femis",
    "retryable": true,
    "attempt": 1,
    "max_attempts": 3
  }
}
```

### 13.7 Retry request

```json
POST /api/bot-jobs/job_01J8.../retry
{ "requested_by": "admin:12" }
```

```json
{
  "ok": true,
  "job": {
    "job_id": "job_01J8...",
    "status": "pending",
    "attempt": 1,
    "note": "attempt increments on next claim"
  }
}
```

---

## 14. State-transition table

| Current | Event | Next | Allowed caller | Notes |
|---|---|---|---|---|
| *(none)* | create job | **pending** | Portal (authorized) | Idempotent on key / one open job per student |
| pending | claim | **claimed** | Bot | Atomic; sets lease, `claimed_by`, `attempt+=1` on claim policy |
| pending | cancel | **cancelled** | Admin | No FEMIS work yet |
| claimed | start / first progress | **running** | Bot (lease holder) | |
| claimed | lease expire + steal | **pending** or directly **claimed** by new worker | Bot | Prefer mark claimable; second claim CAS |
| claimed | complete failure | **failed** | Bot | |
| running | heartbeat | **running** | Bot | Extends lease |
| running | progress | **running** | Bot | May 409 `DATA_STALE` |
| running | complete success + both evidence flags | **success** | Bot | **Only** path to success |
| running | complete success without evidence | **rejected** | — | API must 422; status unchanged |
| running | complete failure | **failed** | Bot | Categories §9 |
| running | lease expire + steal | claimable | Bot | Prior outcome unknown until probe |
| failed | request retry (if `retryable`) | **pending** | Admin/human | Does not by itself set success |
| failed | request retry (if not retryable) | **failed** | — | 409 |
| failed | *(attempts exhausted)* | **failed** terminal | — | `retryable=false` derived |
| success | any bot complete/fail | **success** (immutable) | — | Reopen only via explicit new job design |
| cancelled | request retry | **pending** | Admin | Optional policy |
| any | duplicate create same key | unchanged | Portal | Returns existing job |
| any | duplicate complete (same outcome) | unchanged | Bot | Idempotent 200 |
| any non-success | unknown Finish outcome report | **failed** + `outcome_known=false` | Bot | Never success |

---

## 15. Minimum implementation sequence (future phase — planning only)

1. **Schema/job-store design approval** (this document + separation audit §D refinements)  
2. **DB migration** (additive job table + optional `students.updated_at` — **not** in 3B.2)  
3. **API implementation** (create/get/claim/heartbeat/progress/complete/retry — bot-token auth)  
4. **Portal job creation/status integration** (enqueue after authorized request; dashboard projection)  
5. **Bot worker integration** (claim → snapshot → fill → complete using 3B.1 field contract)  
6. **Concurrency/lease handling** (heartbeat, steal, 409 fencing)  
7. **Failure/retry handling** (taxonomy, `retryable`, unknown outcome policy)  
8. **Integration testing** (claim atomicity; success only with Finish+indicator; fill-only never `success`)  
9. **Deployment verification** (cross-host token path; no students write from bot; backups)

No step above runs in Phase 3B.2.

---

## 16. Out of scope (explicit)

- FEMIS UI changes  
- Portal layout changes (Phase 3A.x territory)  
- Field identity changes / crosswalk edits  
- Field mapping redesign  
- CAPTCHA bypass  
- Authentication implementation  
- PythonAnywhere remediation (including auth troubleshooting)  
- Deployment migration  
- Bot selector changes  
- Browser automation changes  
- `bot_jobs` table creation  
- API endpoint creation  
- Worker/polling/queue implementation  
- Background schedulers  
- Commits of application code  

---

## 17. Verification (Phase 3B.2 gate)

| Check | Expected |
|---|---|
| Test suites | `test_data_integrity.py` 24/24 + `test_submission_status.py` 12/12 + `smoke_test.py` 14/14 + `smoke_test_bot.py` 3/3 = **53/53** |
| Tests modified to pass | **None** |
| New repo file | `docs/phase3b2-bot-job-api-contract.md` only (this phase) |
| Implementation files | Unchanged by 3B.2 |
| DB schema | Unchanged; no `bot_jobs` |
| API endpoints | None added |
| Generated artifacts in repo | None from 3B.2 |

**Pre-existing dirty tree (Phase 2 / 3A.x / 3B.1 — not this phase):**  
`audit_portal.py`, `config/field_mapping.yaml`, `femis-web/app.py`, `femis-web/static/form.js`, `femis-web/templates/form.html`, `smoke_test.py`, `src/data_sources/webform_handler.py`, `src/form_filler.py`, `src/main.py`, untracked `docs/*` (including 3B.1), `smoke_test_bot.py`, `test_data_integrity.py`, `test_submission_status.py`.

---

## 18. Unresolved design questions (for later approval)

1. **Snapshot timing:** materialize at **create** vs at **claim** (affects staleness UX vs write volume).  
2. **One open job per student** vs multiple queued attempts.  
3. **Lease durations / heartbeat interval** defaults.  
4. **Whether `cancelled` is needed in v1** or admin uses `failed(cancelled_by_operator)` only.  
5. **`mode=fill_only` jobs** in v1 or submit-only.  
6. **Same-host transitional SQL claim** (separation audit Phase 3) vs going straight to HTTP when bots leave the portal host.  
7. **Student data version token** implementation (`updated_at` column vs hash of snapshot).  
8. **Teacher vs admin** authorization for retry/cancel.  
9. **max_attempts** and backoff policy ownership (portal config vs bot config — recommend job-store policy).  
10. **Whether progress `DATA_STALE` auto-requeues** or only flags for humans.

---

## 19. Stop conditions honored

- [x] Documentation/design only  
- [x] No `bot_jobs`  
- [x] No schema/migrations/endpoints/workers  
- [x] No edits to implementation files listed in hard boundaries  
- [x] No auth/deployment/FEMIS behavior changes  
- [x] No commit  

**Next session anchor:** await approval of this contract (or revision notes) before any implementation phase (schema/API/worker). Do not start §15 sequence without explicit go-ahead.
