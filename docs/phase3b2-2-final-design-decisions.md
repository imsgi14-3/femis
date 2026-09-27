# Phase 3B.2.2 — Final Bot-Job Design Decisions

**Mode:** STOP / DOCUMENTATION ONLY — authoritative decision record before implementation  
**Date:** 2026-09-24  
**Branch:** `main` (HEAD: `6871f81`)  
**Predecessors (read before this record):**  
- `docs/phase3b1-data-contract-audit.md`  
- `docs/phase3b2-bot-job-api-contract.md`  
- `docs/phase3b2-1-design-decisions.md`  

**HARD RULE:** No application code, bot code, `bot_jobs`, `students.updated_at`, DB schema, migrations, API endpoints, authentication, deployment, tests, portal behavior, FEMIS behavior, or field mappings. **No commits.**  
**Only expected repository change:** `docs/phase3b2-2-final-design-decisions.md`.

**Evidence policy:** Decisions A–O below are **operator-approved**. Repository evidence was checked for direct contradictions. **No contradiction was found** that would require changing an approved decision (see §10). Missing mechanisms in the current repo are recorded as **future implementation prerequisites**, not as reasons to alter the decisions.

---

## 1. Purpose

This document is the **authoritative design decision record** for the FEMIS **Portal → Job Queue → Independent FEMIS Bot** architecture **before** any implementation begins.

It:

1. Records approved decisions **A–O** exactly.  
2. Marks the remaining business questions as **resolved** (§3).  
3. Clarifies **retry** and **post-success edit** semantics with worked examples (§4–§5).  
4. Lists **implementation prerequisites** for schema, API, and bot (§6).  
5. Confirms **existing verified behavior is preserved** (§7).  
6. Closes with verification (§8) and an explicit **STOP** (§9).

---

## 2. Approved decisions (A–O)

### A. Student data version — `students.updated_at`

**Approved:** use **`students.updated_at`**.

**Design requirement (future implementation only — not this phase):**

- Add a normal database timestamp column on `students` during the implementation phase.  
- It represents the **latest modification time** of the student record.  
- It is **updated automatically** whenever the student record changes (all write paths).  
- The user does **not** manually manage the value.  
- Bot jobs retain the **version associated with their immutable attempt snapshot**.  
- **Do not implement the column in this phase.**

**Purpose:**

```text
current student.updated_at
        vs
job snapshot version
```

must allow **stale data** to be detected (see **L. DATA_STALE**).

**Status today:** the column **does not exist** (repo has `created_at` only). Absence is expected until the implementation phase — not a design contradiction.

---

### B. Historical bot-job attempts — one-to-many

**Approved:** one-to-many historical model:

```text
one student
    |
    +-- job/attempt 1
    +-- job/attempt 2
    +-- job/attempt 3
    +-- ...
```

- **Do not overwrite historical attempts.**  
- Exact database schema remains for the implementation phase.  
- The design must distinguish:
  - **job identity** (the logical request / work unit for a student submission context),
  - **attempt number** (1, 2, 3, … — historical, unbounded),
  - **historical attempts** (all prior rows, immutable after terminal),
  - **current/open job** (the one attempt/job lifecycle that is active now).

**Normative structure (logical):**

| Concept | Meaning |
|---|---|
| Job identity | Stable reference for “the work to submit student X to FEMIS” in a given rollout of attempts (implementation may use parent job id **or** student+sequence — **schema deferred**) |
| Attempt | One actual bot execution; append-only history |
| Open job/attempt | At most one active lifecycle per student (see **C**) |

A retry **appends**; it never rewrites attempt 1’s status, timestamps, failure reason, progress, or result.

---

### C. One open job per student

**Approved:** at most **one open job per student**.

**Open means exactly:**

```text
pending | claimed | running
```

- A student may have **many historical** failed or successful attempts.  
- **Never** multiple simultaneous open jobs for the same student.  
- **Duplicate job creation while an open job exists must be rejected safely** (e.g. HTTP 409 / create-conflict returning the existing open job — no second enqueue).

`pending`, `claimed`, `running` = open; `success`, `failed`, `cancelled` (and equivalent terminal states) = closed.

---

### D. Who creates jobs — admin only in v1

**Approved:** the **admin/focal person explicitly creates** bot jobs.

**Do NOT automatically create a bot job from student final-submit in v1.**

```text
Student completes portal
        ↓
Student record saved
        ↓
No automatic bot job
        ↓
Admin/focal person decides to send to FEMIS
        ↓
Bot job created
```

This is **intentional**. Portal submission and job creation remain separate events.

---

### E. Admin/operator

**Approved:** for v1, the operational admin/operator is the **focal person**.

- Do **not** introduce a complex teacher/admin role hierarchy.  
- Design text uses the role name: **`admin/operator`**.  
- The **existing portal authentication/role system must not be redesigned in this phase**.  
- If implementation requires an admin capability the current portal does not provide, record it as an **implementation dependency** (§6).

**Repo note (dependency, not contradiction):** portal sessions today are `student` | `teacher` only — a real admin/focal identity must be added or mapped **in a later approved implementation step**.

---

### F. Student edits after successful FEMIS submission

**Approved:** a successful FEMIS submission does **not** lock the student record forever. The student may later be edited.

However:

- Editing a student does **not** automatically create another bot job.  
- If updated data must be sent to FEMIS again, the **admin/operator explicitly creates a new bot job**.  
- This prevents accidental duplicate FEMIS submissions.

**Also:** automatic re-submission solely because `updated_at` changed is **prohibited** (see §5).

---

### G. Retry policy

**Approved:**

- Do **NOT** use an automatic `max_attempts = 3` rule (supersedes any earlier `max_attempts` blocking proposal from 3B.2 / 3B.2.1).  
- **Attempt count** is retained for **history/visibility only** — **not** an automatic stopping condition.  
- Workflow:

```text
Attempt
   ↓
Failure
   ↓
Report cause
   ↓
Investigate / rectify cause
   ↓
Admin explicitly retries
   ↓
New historical attempt
```

- Do **not** blindly retry an unresolved failure.  
- Do **not** automatically retry an uncertain FEMIS outcome.

---

### H. Failure reporting

**Approved:** each failed attempt must retain enough **structured** information for the focal person.

**At minimum, where known:**

| Field |
|---|
| failure category |
| failed tab |
| failed field |
| completed tabs / progress |
| human-readable diagnostic |
| attempt number |
| timestamps |
| whether FEMIS outcome is known |

**Do not** rely on free-form error text as the machine-readable status. Categories continue to use the Phase 3B.2 taxonomy where applicable: `validation`, `field_mapping`, `browser`, `network`, `femis`, `captcha`, `timeout`, `auth_portal`, `cancelled_by_operator`, `unknown`.

---

### I. Heartbeat and lease

**Approved design:**

- Heartbeat/lease protection **is required**.  
- Previously suggested **15-second heartbeat / 60-second lease / 20-minute max runtime** are **initial unmeasured defaults, not approved fixed values**.  
- **Make these configurable implementation parameters.** Do **not** hard-code them as architectural requirements.  
- The implementation phase must **choose initial values and test them** against the actual bot workflow.

**Purpose:**

```text
Bot claims job
      ↓
periodic heartbeat
      ↓
job remains owned
```

If the bot disappears and heartbeat stops, the **lease eventually expires** and the job can be **safely recovered** according to implementation rules.

**Invariant:** do **not** allow two workers to own the same live job/attempt simultaneously (CAS + lease / fencing).

---

### J. Fill-only mode

**Approved:** **defer `fill_only`.** v1 bot jobs are **submit-only**.

**Verified success rule (unchanged — do not weaken):**

```text
official FEMIS Finish action
    +
verified FEMIS completion indicator
    =
success
```

**These do NOT constitute job success:**

- portal submitted  
- browser opened  
- fields filled  
- `fill_success`  
- partial FEMIS tab completion  

---

### K. Snapshot (hybrid, claim-time, version-checked)

**Approved:** Phase 3B.2 hybrid approach:

- job references **`student_id`**  
- job records the relevant **`student_data_version`**  
- the attempt uses an **immutable snapshot**  
- bot does **not** re-read the live student record during the run  

**Snapshot materialization occurs at claim**, as previously designed.

**Implementation must verify the version before materializing the snapshot:**

```text
job created
    ↓
student version recorded
    ↓
claim
    ↓
compare current version
    ↓
same   → materialize immutable snapshot
different → DATA_STALE
```

**Do not silently substitute current student data for an older job version.**

---

### L. DATA_STALE — fail closed

**Approved:** **fail closed.**

If:

```text
job snapshot/version  !=  current student version
```

then:

| Result | Value |
|---|---|
| job state | **failed** |
| detail | **DATA_STALE** |

**Do NOT automatically:**

- requeue  
- create another job  
- refresh the snapshot  
- submit the newer data  

The admin/operator may **explicitly retry with `refresh_snapshot=true`** when appropriate. The implementation must make this an **explicit operator action**.

---

### M. Claim mechanism — hybrid CAS + lease

**Approved:** previously designed hybrid architecture:

- **SQL atomic claim** acceptable when portal and job store are **colocated**.  
- **HTTP API claim** is the **normative** design for independently deployed bot/portal.  
- **Both** must enforce the **same** atomic compare-and-set / lease semantics.  

**Do not** make same-host database access a requirement for the independent bot.

---

### N. Job / API responsibilities

**Approved architecture:**

```text
Portal / Admin
      |
      v
Job API / Job Store
      |
      v
Independent FEMIS Bot
```

| Owner | Responsibilities |
|---|---|
| **Job system** | job identity, lifecycle, attempts, claim/lease, progress, retry authorization, structured failure state |
| **Bot** | browser automation, FEMIS interaction, field mapping implementation, FEMIS-specific execution, final completion evidence |

---

### O. Security

**Approved:** retain the Phase 3B.2 boundary.

| Party | Rule |
|---|---|
| **Portal/admin** | Portal authentication for permitted administrative operations |
| **Bot** | Dedicated **bot machine token** |
| Credentials | **Do not** use student passwords as bot credentials |

**Do not expose through the job API:**

- FEMIS credentials  
- CAPTCHA details  
- browser/session state  
- selectors  
- internal field-mapping implementation  

---

## 3. Resolved question matrix

| Question | Final decision |
|---|---|
| `updated_at` | Add automatic student timestamp **during implementation** |
| Job history | **One-to-many** historical attempts |
| Admin/operator | **Focal person** |
| Job creation | **Admin-created only** (v1) |
| Post-success edit | **Allowed**; no automatic new job |
| Automatic max attempts | **None in v1** |
| Retry | **Explicit admin retry** after cause rectification |
| Heartbeat | **Required**; configurable |
| Lease | **Required**; configurable |
| Fill-only | **Deferred** |
| Snapshot | **Immutable per attempt**, materialized **at claim** (version-checked first) |
| Stale data | **Fail closed** as `DATA_STALE` |
| Retry after stale | **Explicit admin retry with `refresh_snapshot`** |
| Claim | **CAS + lease**; **HTTP normative cross-host** |
| Final-submit auto-job | **No** |
| FEMIS success | **Finish + verified completion indicator** |

All rows above are **RESOLVED** for this design record.

---

## 4. Clarify “retry”

A retry is **not** an overwrite.

**Example — Student 42:**

```text
Attempt 1
  failed: network

Admin investigates

Attempt 2
  failed: field_mapping

Admin rectifies

Attempt 3
  success
```

**All attempts remain historical.**

Rules:

1. A retry must **create a new attempt** while preserving the original job history.  
2. Do **not** silently erase the previous failure (status, timestamps, category, tabs, diagnostic).  
3. Attempt numbers increase monotonically for visibility; **no cap** blocks a further explicit retry.  
4. Retry is only initiated by **admin/operator** after investigating the reported cause (except operator-allowed `refresh_snapshot=true` for stale cases — still explicit).

---

## 5. Clarify successful students

**Example — Student 42:**

```text
Student 42
  Attempt 3 → success

Later:

Student 42 edited

Result:
  No automatic bot job
```

If the admin decides the changed data must be sent to FEMIS:

```text
Admin explicitly creates a new bot job
```

**The system must not automatically resubmit merely because `updated_at` changed.**

| Event | New bot job? |
|---|---|
| Student edit after success | **No** |
| `updated_at` changed | **No** (version used only for **staleness**, not auto-create) |
| Admin decides resubmission needed | **Yes** — explicit create |
| Portal final-submit | **No** auto job in v1 (decision D) |

---

## 6. Implementation prerequisites

**None of the following are implemented in 3B.2.2.** They gate the next implementation phase.

### 6.1 Required future schema work

- [ ] **`students.updated_at`** — automatic timestamp, all write paths  
- [ ] **Bot-job storage** (job identity per student submission context)  
- [ ] **Historical attempts** — one-to-many, non-overwriting  
- [ ] **Snapshot / version storage** (per attempt)  
- [ ] **Claim / lease information** (`claimed_by`, `lease_expires_at`, heartbeat fields, etc.)  
- [ ] **Structured progress / failure information** (category, tab, field, progress, outcome-known, timestamps, attempt number)

### 6.2 Required future API work

- [ ] Admin job creation  
- [ ] Job retrieval / listing  
- [ ] Claim  
- [ ] Heartbeat  
- [ ] Progress  
- [ ] Success completion (Finish + indicator evidence)  
- [ ] Failure completion (structured)  
- [ ] Explicit retry (including `refresh_snapshot` when appropriate)  
- [ ] Appropriate administrative cancellation **if retained** (pending-only remains prior design unless superseded)

### 6.3 Required future bot work

- [ ] Claim jobs  
- [ ] Materialize **immutable snapshot** (after version check)  
- [ ] Heartbeat  
- [ ] Report progress  
- [ ] Report structured failure  
- [ ] Report verified FEMIS success  
- [ ] **Never** treat fill-only as success  

### 6.4 Implementation dependency (from E)

- Portal must gain an **admin/operator** capability sufficient for job creation/retry/cancel **without** redesigning student/teacher auth in this design phase — separate approval required.

---

## 7. Existing verified behavior preserved

This decision phase does **NOT** alter:

| Area | Status |
|---|---|
| Portal field names | **Unchanged** |
| Portal grouping / layout (Phase 3A) | **Unchanged** |
| `FORM_FIELD_MAP` | **Unchanged** |
| `field_mapping.yaml` | **Unchanged** |
| Tab 7 persistence fix (Phase 2) | **Unchanged** |
| `transport` → `transport_facility` aliasing | **Unchanged** |
| `refugee_card` ↔ `refugee_card_number` | **Unchanged** |
| Disability multi-value handling (`disability_types` CSV / `[]`) | **Unchanged** |
| Final-submit persistence (`submitted=True`) | **Unchanged** |
| Finish / completion success semantics (Phase 2 / 3B.1) | **Unchanged** |
| FEMIS selectors | **Unchanged** |
| CAPTCHA behavior | **Unchanged** |
| Field contract from 3B.1 | **Frozen** |

No architectural drift: A–O refine the **future** job system only.

---

## 8. Verification

| Check | Result |
|---|---|
| `test_data_integrity.py` | 24/24 |
| `test_submission_status.py` | 12/12 |
| `smoke_test.py` | 14/14 |
| `smoke_test_bot.py` | 3/3 |
| **Total** | **53/53** |
| Tests modified | **No** |
| New/changed file this phase | **`docs/phase3b2-2-final-design-decisions.md` only** |
| Implementation code changed | **No** |
| DB schema changed | **No** |
| Migration exists | **No** |
| API endpoints exist | **No** (`/api/bot*` absent) |
| `bot_jobs` table exists | **No** (tables: `students`, `teachers`) |
| Bot-job implementation exists | **No** |
| Commits | **None** |

**Pre-existing dirty tree (not this phase — Phases 2 / 3A / 3B.1 / 3B.2 / 3B.2.1):**  
`audit_portal.py`, `config/field_mapping.yaml`, `femis-web/app.py`, `femis-web/static/form.js`, `femis-web/templates/form.html`, `smoke_test.py`, `src/data_sources/webform_handler.py`, `src/form_filler.py`, `src/main.py`, untracked `docs/*` (all prior phase docs), `smoke_test_bot.py`, `test_data_integrity.py`, `test_submission_status.py`.

---

## 9. STOP

- [x] Documentation only  
- [x] Decisions A–O recorded  
- [x] Question matrix resolved (§3)  
- [x] Retry / success-edit examples documented  
- [x] Implementation prerequisites listed (§6) — **not implemented**  
- [x] Verified behavior preserved (§7)  
- [x] **53/53**  
- [x] No contradictions requiring operator re-decision (§10)  
- [x] No commit  

**STOP.** Do not implement schema, APIs, or bot-job behavior. Await separate implementation approval after review of this record.

---

## 10. Contradiction check (required by brief)

| Decision | Repo evidence checked | Contradiction? |
|---|---|---|
| A `updated_at` | Column absent; only `created_at` | **No** — future prerequisite |
| B one-to-many history | No job tables exist | **No** |
| C one open job | No queue today (unlimited duplicates historically) | **No** — design addresses gap |
| D admin-only create | No auto-create path exists | **No** |
| E admin/operator | Roles are `student`/`teacher` only | **No design contradiction** — **implementation dependency** recorded in §6.4 |
| F–G no auto job / no max_attempts | No job logic exists; `max_attempts` only in older audit prose (withdrawn here) | **No** |
| H–I failure/lease | Bot has no job heartbeat today | **No** — prerequisite |
| J fill-only | `fill_success` already ≠ success (tests 12/12) | **Consistent** |
| K–L snapshot / DATA_STALE | Matches 3B.2 / 3B.2.1 | **Consistent** |
| M–O claim / responsibility / security | Matches 3B.2 | **Consistent** |

**No approved decision required alteration.**
