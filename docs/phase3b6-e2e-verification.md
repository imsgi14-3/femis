# Phase 3B.6 — Controlled End-to-End Job Execution Verification

**Date:** 2026-09-26
**Scope:** Verification only. No application code, selectors, mappings, portal HTML/JS, auth,
schema, or job API contract was changed during this phase.
**Verdict:** **PASS** (see §16)

---

## 1. Environment

| Item | Value |
|---|---|
| OS / shell | Windows, PowerShell |
| Repo | `C:\Users\faiza\OneDrive\Documents\IMSG I-14\FemisBot`, branch `main`, HEAD `6871f81` |
| Working tree | 10 modified + 16 untracked files, nothing staged — **identical before and after this phase** |
| API under test | Second `femis-web` instance on **:5001** (PID 21444), `FEMIS_BOT_TOKEN` + `FEMIS_OPERATOR_TOKEN` injected via env |
| User's dev server | :5000 (PID 15996) — **untouched**, as required |
| Bot | `python -m src.main --jobs` (run 1 PID 28956, run 2 PID 25952) |
| Portal | Official FEMIS: `https://femis.fde.gov.pk` (real environment, no mocks) |
| Portal session | `data/logs/femis_session.json`; CAPTCHA solved manually once, session reused for run 2 |
| Operator session | Cookie signed with default dev `SECRET_KEY` (teacher password unknown — see §15) |
| Tokens | Held only in session-temp file + child-process env; never written to source or logs in this repo |
| Timestamps | DB timestamps are UTC; bot/API logs are local (UTC+5). Both are shown where relevant |

## 2. Preconditions (pre-flight)

1. **Working tree state** — 10 modified, 16 untracked, 0 staged (listed in STOP report §b).
2. **3B.5 present** — `docs/phase3b5-bot-integration.md` present; job runner/client modules in tree.
3. **Regression suite run before E2E** — all green (§3).
4. **Exact pass counts recorded** — §3.
5. **Canonical DB baseline** — `femis-web/instance/femis.db`: **0** bot jobs, 7 students
   (fingerprint `ac46f88f6e878d92`), 1 teacher. No unexpected jobs.
6. **No test/student data silently modified** — the E2E subject (student 8) was already present
   from earlier admin-approved setup; no row was edited to make the test pass.

## 3. Automated regression results

All seven suites were run at pre-flight and again after the E2E runs:

| Suite | Pre-flight | Post-run |
|---|---|---|
| `test_bot_job_schema.py` | **61/61** | **61/61** |
| `test_bot_job_api.py` | **123/123** | **123/123** |
| `test_bot_job_bot_integration.py` | **54/54** | **54/54** |
| `test_data_integrity.py` | **24/24** | **24/24** |
| `test_submission_status.py` | **12/12** | **12/12** |
| `smoke_test.py` | **14/14** | **14/14** |
| `smoke_test_bot.py` | **3/3** | **3/3** |

Note: one intermediate chained execution (several suites in a single shell one after another)
reported transient dips of 59/61 and 121/123. Each suite re-run individually, and the final full
sequential run of all seven suites, was entirely green. The counts above are the authoritative ones.

## 4. Test student/job identification

**Positive path (the one controlled test student):**

| Field | Value |
|---|---|
| Job ID | **1** |
| Student ID | **8 — "Ahmed Khan"** |
| Attempt number | **1** (`prior_attempt_id = null`) |
| Initial student `updated_at` | `2026-09-26 07:10:56` (unchanged after the run) |
| Initial job status | `pending` |
| `student_data_version` | `2026-09-26 07:10:56.000000` — matches the student row |
| Created | 2026-09-26 13:21:27 UTC (18:21:27 local) via `POST /api/jobs` (operator), `created_by=mrs_ahmed` |
| Idempotency key | `phase3b6-e2e-run1` — duplicate create returned `idempotent=true` with exactly **1** row |
| Final status | `success` (see §11 vocabulary note) |

**Negative path (optional, run only after the clean positive run):**

| Field | Value |
|---|---|
| Job ID | **2** |
| Student ID | **7 — "E2E Smoke Student"** (disposable) |
| Attempt number | **1** |
| Student `updated_at` | `2026-09-23 05:21:37.840722` (unchanged after the run) |
| Created | 13:31:55 UTC (18:31:55 local), idempotency key `phase3b6-e2e-neg1` |
| Final status | `failed` / `validation` (see §13) |

## 5. Exact execution timeline (local time; UTC in brackets)

**Positive run (job 1):**

| Time | Event | Evidence |
|---|---|---|
| 18:18 | Second API instance started on :5001 | process list |
| 18:20:53–18:21:13 | Auth probes: claim no/bad token → 401, empty queue → 404, create no session → 401 | API access log |
| 18:21:27 [13:21:27] | **Job 1 created** (`POST /api/jobs` 200) | API access log, DB capture |
| 18:21:28 | Duplicate create with same idempotency key → 200 `idempotent=true`, 1 row | API access log, DB capture |
| 18:22:36 | Bot launched (`--jobs`), portal login opens | bot log |
| 18:22:47–18:25:18 | Interactive login; **user solved CAPTCHA manually** (147 s) | bot log `Interactive login successful (147s)` |
| 18:25:20 [13:25:20] | **Claim** (`POST /api/jobs/claim` 200) → `claimed`, gen 1, snapshot materialized | API access log, DB capture |
| 18:25:22 [13:25:22] | First `progress` → status `running`, `started_at` set | API access log, DB capture |
| 18:25:35 → 18:27:47 | **9 heartbeats**, ~15 s cadence, all HTTP 200 | API access log |
| 18:25:22 → 18:27:35 | Tabs 1→7 filled, Save & Next each tab OK | bot log, §8 |
| 18:27:41–18:27:45 | Final force-saves (fallback POST 405 → real save POST 200) | bot log |
| 18:27:47 | **Finish clicked** | bot log `Clicked Finish` |
| 18:27:48 [13:27:48] | **Form submitted successfully** → `POST /api/jobs/1/complete` 200 | bot log, API access log |
| 18:27:48 | Next claim → 404 (queue drained); bot exits `Job loop finished (idle)` | API access log, bot log |
| 18:27:48 | Batch summary: `Total: 1, Submitted: 1, Errors: 0` | bot log |
| 18:29:36 | Post-run capture: job `success`, fingerprint unchanged | `p3b6_postrun.json` |

**Negative run (job 2):**

| Time | Event | Evidence |
|---|---|---|
| 18:31:55 | Job 2 created (operator) | API access log |
| 18:32:44 | Bot launched; **saved session reused — CAPTCHA skipped** | bot2 log |
| 18:32:46 | Claim 200 → `claimed`, gen 1, snapshot | API access log |
| 18:33:01 → 18:35:16 | **10 heartbeats**, all 200 | API access log |
| 18:34:09 → 18:34:42 | Tabs 1–6 Save each rejected: **HTTP 422 "The B-Form Number has already been taken."** | bot2 log |
| 18:35:04–18:35:05 | Final-tab save attempts | bot2 log, API access log |
| 18:35:20 | Finish unavailable (validation errors) → complete 200 → `failed/validation` | bot2 log, API access log |
| 18:35:20 | Queue drained, bot exits | bot2 log |

**Post-run probes:**

| Time | Event | Evidence |
|---|---|---|
| 18:45:41 | Heartbeat on terminal job → **409 `invalid_transition`** (lease cannot outlive terminal) | probe output, API access log |
| 18:45:41 | Idempotent `complete` replay → **200 `idempotent=true`**, job unchanged | probe output, API access log |

## 6. Claim / snapshot / version evidence

- `POST /api/jobs/claim` returned **200** at 18:25:20; `claimed_by=femis-bot-FaizaMir-PC-28956`,
  `claim_generation=1`, `claimed_at=13:25:20.343735`.
- **Snapshot materialized** at claim: `snapshot_materialized_at=13:25:20.343735`,
  `has_snapshot=true`, envelope keys exactly `{student_id, version, materialized_at, data}`,
  `snapshot_student_id=8`.
- **Version match:** `student_data_version = 2026-09-26 07:10:56.000000` = student 8's
  `updated_at`; the student row was not edited during the run (byte-level diff vs pre-run
  capture: **NONE**).
- **Lease fields populated** at claim: `lease_expires_at = last_heartbeat + 60 s`, updated on
  every heartbeat/progress call.
- **No second job accidentally created:** job count stayed 1 throughout; duplicate-create with the
  same idempotency key returned the existing job (`idempotent=true`); the post-completion claim
  returned 404 `no_pending_job`.
- First `progress` call performed the designed `claimed → running` transition
  (`started_at=13:25:22.132745`).

## 7. Heartbeat / lease evidence

- Job 1: **9 heartbeats** — 18:25:35, 18:25:50, 18:26:05, 18:26:20, 18:26:35, 18:26:50,
  18:27:05, 18:27:20, 18:27:35 — **all HTTP 200**, ~15 s cadence.
- Timestamps advanced monotonically: `last_heartbeat_at=13:27:47.973690`;
  `lease_expires_at=13:28:47.973690` (60 s lease, always ahead of the heartbeat at every poll).
- `claim_generation` remained **1** for the whole run — no fencing conflict, no supersede.
- The job was **never marked lost**; no `DATA_STALE`, no `lease_expired`, no false timeout
  (no 409/5xx on any heartbeat/progress call — API access log).
- **Lease vs terminal:** a heartbeat sent after completion returns
  **409 `invalid_transition` (`Job is not active.`)** — the lease cannot be used past terminal
  state. `lease_active=false` on the completed job.
- Job 2: 10 heartbeats, all 200, same behavior up to its failure at 18:35:20.

## 8. Per-tab progress evidence

`POST /api/jobs/1/progress` accepted **15** updates (all 200): start, each Save & Next
transition, final save, submitting, verifying. Stored progress chain in the final job row:

```
progress: tab=1 filling
progress: tab=1 field=is_hafiz saved
progress: tab=2 filling
progress: tab=2 field=income_per_month saved
progress: tab=3 filling
progress: tab=3 field=avail_institutional_meal saved
progress: tab=4 filling
progress: tab=4 field=internet_at_home saved
progress: tab=5 filling
progress: tab=5 field=internet_at_home saved
progress: tab=6 filling
progress: tab=6 field=internet_at_home saved
progress: tab=7 filling
progress: tab=7 final_save
progress: tab=7 submitting
progress: tab=7 verifying
```

Bot-side Save & Next confirmations (all `advanced, errors=0, invalid=0`):

| Tab | Save OK at |
|---|---|
| 1 Personal Details | 18:26:18 |
| 2 Parents / Guardian | 18:26:43 |
| 3 Educational Details | 18:27:07 |
| 4 Emergency Contact | 18:27:17 |
| 5 IDPs Details | 18:27:22 |
| 6 Health Details | 18:27:35 |
| 7 Digital Access | final force-save 18:27:42, before Finish 18:27:45 |

**Form behavior unchanged:** progress events are transport-only (`form_filler._notify_progress`
seam → `job_runner.on_progress` → API); field mapping, selectors and save flow executed exactly
as in 3B.5 (same fill/save/submit code path; regression suites confirm no behavioral drift).

## 9. Finish-click evidence

- Bot log `18:27:47 Clicked Finish` (direct observation, not inferred).
- Final saves immediately before Finish: portal returned **POST 200** twice against
  `https://femis.fde.gov.pk/students/d9c06221-b9ad-11f1-bd9c-fefcfe7ff8dc` at 18:27:45.
- Job row: `finish_clicked = 1`.

## 10. Completion-indicator evidence

- Bot log `18:27:48 Form submitted successfully` — the portal's success indicator was detected
  after the Finish click (the bot only logs this on the observed indicator, not on fill success).
- Job row: `indicator_detected = 1`, `outcome_known = 1`, `bot_result_code = success`.
- `job_runner` logs `Job 1: completed -> success` **only when the complete API answered
  200 `ok=true`** — completion was acknowledged by the API, not inferred locally.

## 11. Final job state

Final row for job 1 (captured 18:29:36, re-confirmed by idempotent replay at 18:45:41):

| Field | Value |
|---|---|
| `status` | `success` |
| `completed_at` | `2026-09-26 13:27:48.316181` |
| `outcome_known` | `1` |
| `finish_clicked` | `1` |
| `indicator_detected` | `1` |
| `bot_result_code` | `success` |
| `failure_category` | `null` — no erroneous failure category |
| `error_message` | progress chain retained (evidence, §8) |
| `current_tab` / `last_completed_tab` | `7` / `6` (observation below) |
| `attempt_number` / `prior_attempt_id` | `1` / `null` — exactly one attempt |
| `claim_generation` / `claimed_by` | `1` / `femis-bot-FaizaMir-PC-28956` |
| `lease_active` | `false` |
| `lease_expires_at` | retains `13:28:47.973690` (observation below) |
| Completion API | original `POST …/complete` 200 at 18:27:48; replay 18:45:41 → **200 `idempotent=true`**, no state change |

**Design-conformance observations (not defects):**

1. **`completed` vs `success`:** the brief's "final status = `completed`" maps to the schema's
   terminal success vocabulary: `status='success'` + `completed_at` set
   (`BOT_JOB_TERMINAL_STATUSES = ("success","failed","cancelled")`, `app.py:222-224`).
2. **`lease_expires_at` retained after success:** the complete-success path intentionally does
   not null the column; the lease is rendered inactive by terminal status
   (`lease_active=false`), and every lease-holder endpoint on a terminal job returns
   409 `invalid_transition` (verified live, §7). Only DATA_STALE/abort paths null it
   (`job_api.py:629,642`). No design doc or test requires nulling on success.
3. **`last_completed_tab = 6`:** the filler reports `last_completed` only at Save & Next
   transitions; tab 7 has no Save & Next (final save + Finish instead). Tab-7 completion is
   represented by `current_tab=7` plus the `final_save`/`submitting`/`verifying` progress lines
   and the Finish/indicator flags.

## 12. Final DB verification

**Captured immediately after the run (18:29:36) — `p3b6_postrun.json`:**

1. **Exactly the expected job/attempt:** 1 job, id 1, `attempt_number=1`, status `success`.
2. **Student data unchanged:** students fingerprint `ac46f88f6e878d92` **pre-run = post-run**;
   student 8 row diff vs pre-run = **NONE** (`updated_at` still `2026-09-26 07:10:56`).
3. **No duplicate job:** duplicate-create replay returned the same row (`idempotent=true`).
4. **No unrelated rows modified:** 7 students, 1 teacher, only job rows (none at that point)
   existed; fingerprint equality proves no student mutation.
5. **Snapshot immutable:** snapshot present with `version` = creation-time
   `student_data_version`; schema CHECK `ck_bot_jobs_snapshot_requires_version` + API test D8
   confirm immutability semantics; snapshot was never rewritten during the run.
6. **Attempt history intact:** `attempt_number=1`, `prior_attempt_id=null`, idempotency keys
   unique across jobs.
7. **Existing integrity preserved:** all seven data-integrity/submission-status suites green
   (§3).

**After the negative run:** 2 jobs — `success=1`, `failed=1`, attempts `[1, 2]`, one row per
job; student 7 and student 8 both unchanged.

**Incident (reported, not patched — verification-only phase):**
the post-run regression execution of `test_bot_job_api.py` performs an **unconditional
`DELETE FROM bot_jobs`** in its cleanup (`test_bot_job_api.py:796` and `finally` at `:815`,
commented "this file's artifacts only" but not scoped to test-created rows). This removed **both
E2E job rows** from the canonical DB after the captures above were saved. The row-level evidence
for both jobs survives in the captures/logs listed in §15. The test-cleanup scoping is a
**test-suite defect to fix in a follow-up** (out of 3B.6 scope; not modified here).

**Separate observation:** student 6's `updated_at` changed at 13:42:48 UTC — caused by an
external browser session against :5001 (local `save-tab`/`final-submit` activity at 18:41–18:42,
operator manually using the local portal). Not caused by either bot run; the E2E subject
(student 8) and student 7 were untouched.

## 13. Negative-path result (performed after the clean positive run)

**Setup:** one disposable job (id 2) for student 7 "E2E Smoke Student".

**Observed failure:** every tab Save returned portal **HTTP 422
"The B-Form Number has already been taken."** (18:34:09–18:34:42). Finish was never available;
submit diagnostics listed the portal's validation messages. Final completion:

| Field | Value |
|---|---|
| `status` | `failed` |
| `bot_result_code` | `submit_failed` |
| `failure_category` | `validation` |
| `failed_tab` / `failed_field` | `7` / `internet_at_home` |
| `finish_clicked` | `0` — Finish never clicked |
| `outcome_known` | `1` |
| `attempt_number` | `1` |

**Verdict on the negative path: a known failure was classified correctly and did NOT become a
false success.** No portal record was corrupted (all saves were rejected); student 7's local row
was unchanged.

**Root cause (confirmed):** our local DB held **two students with the same B-Form/CNIC
`35202-1234567-1`** — student 7 (smoke) and student 8 (Ahmed). Job 1 had already submitted
Ahmed's record to the portal, so the portal's unique-CNAC constraint rejected job 2's saves. The
bot's existing duplicate-recovery searched the portal list **by name** ("E2E Smoke Student"),
correctly found no CNIC match (the portal record is under "Ahmed Khan"), and therefore stayed in
create mode — exactly the scenario the admin identified.

**Admin-directed resolution procedure (for future real records when the portal reports
"CNIC/B-Form already used"):**

1. Go to **Students** and search **by name** (FEMIS does not support search by CNIC).
2. If a record matches **name + CNIC**, **edit** that record and fill the latest info
   (do not create a second record).
3. If the name search does not find it: select **Show 100 entries**, press **Ctrl+F** and find
   the required CNIC among the visible 100. If it is not there, click **next** for the next 100
   and repeat until the CNIC is located.
4. Report **the name of the student the CNIC is used against** to the admin in the error info —
   real-world CNIC ownership needs **manual verification** before any record is edited.

**Data decision applied (admin-approved):** student 7 (E2E Smoke Student) was **deleted** from
our DB; **student 8 (Ahmed Khan) kept** and is the designated test student for future runs
(job-row evidence for student 7 was captured before deletion — `p3b6_student7_evidence.json`).
**No pseudo CNICs will be used from now on** (FEMIS does not allow record deletion, so a
duplicate CNIC creates an unrecoverable conflict).

**Prevention (approved next step, executed after this report):** enforce CNIC/B-Form uniqueness
in our own DB — see §16/STOP report.

## 14. Failures / blockers

- **None blocking the positive path.** CAPTCHA required one manual interaction (147 s), after
  which the saved session covered run 2. No boundary was simulated.
- **Test-cleanup incident** — post-run regression wiped the E2E job rows from the canonical DB
  (§12). Evidence preserved in captures; defect reported for a follow-up fix; **not patched in
  this phase**.
- **Pre-existing template bug observed (unrelated, untouched):** `GET /students` returns 500
  when a student has `created_at=NULL` (`femis-web/templates/list.html:36` calls
  `.strftime` on `None`). Not triggered by the E2E, not modified (verification-only).
- **Transient chained-suite dip** (59/61, 121/123) — resolved; individual and final full runs
  green (§3).

## 15. Scope limitations

- **One controlled test student** (Ahmed Khan, id 8) for the positive path; one disposable
  student (id 7) for the negative path.
- Real official portal environment was used — job 1 created/updated a real portal record for the
  controlled student (intended by the phase design).
- Operator session was minted by signing a Flask cookie with the default dev `SECRET_KEY`
  (teacher password unknown). Affects only how the admin API was called, not bot behavior.
- The portal-side record for job 2 could not exist (all saves were rejected), so no portal-side
  verification applies to the negative path.
- E2E job rows no longer exist in the canonical DB (test-cleanup incident, §12); row-level
  evidence is preserved in: `p3b6_prerun.json`, `p3b6_postrun.json`,
  `p3b6_student7_evidence.json`, `p3b6_bot_out.log`, `p3b6_bot2_out.log`,
  `p3b6_api_err.log` (all under `C:\Users\faiza\AppData\Local\Temp\opencode\`), plus
  `data/output/report_20260926_182748.json`, `data/output/report_20260926_183521.json` and
  `data/logs/run_*.log`.
- Heartbeat cadence was verified from the API access log timestamps (every request logged),
  not from a database poll every second.

## 16. Final verdict

# **PASS**

The complete real E2E path was observed end-to-end against the official FEMIS portal with
concrete evidence at every major transition:

`admin creates job (18:21:27) → bot claims + snapshot/version materialized (18:25:20) →
running + 9 heartbeats (18:25:35–18:27:47) → tabs 1–7 filled and saved (18:25:22–18:27:45) →
Finish clicked (18:27:47) → success indicator detected (18:27:48) → completed with evidence
(status=success, finish_clicked=1, indicator_detected=1, completed_at set, completion API 200)
→ queue drained (18:27:48)`.

The optional negative path also ran cleanly: a known portal validation failure was classified
`failed/validation` with `finish_clicked=0` — **no false success** — and its root cause (duplicate
CNIC in our own DB) has been confirmed and approved for prevention.

No application code, selector, field mapping, portal asset, authentication behavior, DB schema or
job API contract was changed during this phase.

---

# STOP report

### a. Files created

- `docs/phase3b6-e2e-verification.md` — this report (only repo file created)
- Session-temp evidence (outside repo, `C:\Users\faiza\AppData\Local\Temp\opencode\`):
  `p3b6_tokens.txt`, `p3b6_prerun.json`, `p3b6_postrun.json`, `p3b6_student7_evidence.json`,
  `p3b6_bot_out.log`, `p3b6_bot2_out.log`, `p3b6_bot2_err.log`, `p3b6_api_out.log`,
  `p3b6_api_err.log`, `userbrief_prt_0dd8c479c001MdNcjKJFfOHkgK.md`
- Bot-generated runtime artifacts (gitignored `data/`): `data/output/report_20260926_182748.json`,
  `data/output/report_20260926_183521.json`, `data/logs/run_*.log`,
  `data/logs/femis_session.json` (session refreshed)

### b. Files modified

- **None.** `git status` before and after this phase is identical (10 modified, 16 untracked,
  0 staged): `.env.example`, `audit_portal.py`, `config/field_mapping.yaml`, `femis-web/app.py`,
  `femis-web/static/form.js`, `femis-web/templates/form.html`, `smoke_test.py`,
  `src/data_sources/webform_handler.py`, `src/form_filler.py`, `src/main.py` (all modified in
  earlier phases, unchanged here) + 16 untracked files (`docs/`, `femis-web/job_api.py`,
  `smoke_test_bot.py`, `src/job_api_client.py`, `src/job_runner.py`, 5 test files).

### c. Files untouched

- All application source, templates, static assets, `config/field_mapping.yaml`, `.env`,
  canonical schema, the user's :5000 server (PID 15996), student/form data (except the
  admin-approved deletion of smoke student 7 recorded in §13).

### d. Test counts

61/61 · 123/123 · 54/54 · 24/24 · 12/12 · 14/14 · 3/3 (schema, api, bot-integration,
data-integrity, submission-status, smoke, smoke-bot) — pre-flight and post-run.

### e. E2E result

**PASS** — positive path fully observed with evidence (§16); negative path correctly classified
as `failed/validation`, no false success (§13).

### f. Blockers / failures

- No blockers. Observations: test-cleanup wipes canonical `bot_jobs` rows (defect to fix in
  follow-up, not patched here); pre-existing `/students` 500 on `created_at=NULL` (untouched);
  one transient chained-suite dip (re-run green).

### g. Was any application code changed?

**No.** Zero application/test/source files changed in this phase.

### h. Next-session anchor (single next step)

Execute the admin-approved CNIC prevention step: **delete smoke student 7 (keep Ahmed as the
designated test student), then enforce B-Form/CNIC uniqueness in our DB**
(partial unique index on `students.b_form` for non-empty values + write-path validation that
reports the holding student's name on conflict), followed by a full regression run. Await
approval before any 3B.7 work.

---

## Post-Approval Remediation Addendum (executed after �16 STOP)

Admin-approved follow-up to the STOP report above. Scope: exactly two items � delete smoke
student 7, enforce B-Form/CNIC uniqueness (scope `b_form` only; father/mother/guardian CNIC
remain non-unique by design, since siblings legitimately share them).

### R1. Smoke student 7 deleted, Ahmed retained

- Deleted `id=7 'E2E Smoke Student'` (`b_form=35202-1234567-1`) from
  `femis-web/instance/femis.db`. Row had no referencing `bot_jobs` (queue was empty), so no
  FK orphaning. Evidence for the deleted row was already preserved pre-deletion in
  `p3b6_student7_evidence.json`.
- Ahmed Khan (`id=8`, `b_form=35202-1234567-1`) retained � **designated test student for all
  future runs.** No other student rows touched.
- Final students table (6 rows): 3 Ali Khan, 4 Test2, 6 Ayat Mubeen, 8 Ahmed Khan, 9 Ayat
  Mubeen, 10 Portal Verify Student. `bot_jobs`: 0 rows.

### R2. B-Form/CNIC uniqueness enforced in our DB (`femis-web/app.py`)

Two cooperating layers, both digits-only normalized (`35202-1234567-1` == `3520212345671`):

1. **DB-level partial unique index** `uq_students_b_form`, created idempotently at startup
   (`CREATE UNIQUE INDEX IF NOT EXISTS` in the existing lightweight-migration block �
   `db.create_all()` never adds indexes to pre-existing tables). Applies only to non-empty
   `b_form` values, so students without a B-Form are exempt. This is the hard backstop: it
   also blocks differently-formatted duplicates via raw SQL.
2. **Write-path validation** with holder-name error, at all three local write paths:
   - `POST /api/save-tab` (create + update branches, self-exclusion on update),
   - `POST /api/final-submit` (self-exclusion),
   - `POST /submit` (legacy form route ? flash + redirect, creates no row).
   Conflict response: HTTP **409** JSON `{"ok": false, "error": "B-Form/CNIC <value> is
   already used by student '<name>' (id <id>). The portal keeps one record per CNIC � edit
   that record instead of creating a duplicate."}` � the holder's name is surfaced to the
   operator, mirroring the �13 portal procedure. `IntegrityError` on commit is caught and
   mapped to the same 409 (race backstop); `form.js` already renders `res.error` in its
   save-failure alert, so no front-end change was needed.

### R3. Verification

- **Dedicated uniqueness probe: 16/16 passed** (`p3b6_uniqueness_check.py`, temp dir � not
  added to the repo): index exists; digits-only conflict detection; self-update with own
  `b_form` allowed; duplicate create / formatted-duplicate create / `final-submit` dup /
  legacy `/submit` dup all rejected with holder name; empty-`b_form` rows exempt; raw-SQL
  duplicate blocked by the index; distinct CNIC accepted; test rows cleaned up.
- **Full regression after the change: all 7 suites green** � 61/61, 123/123, 54/54, 24/24,
  12/12, 14/14, 3/3 (no test sets `b_form`, so the index affects none of them).
- Ahmed's record restored to its original `35202-1234567-1` format after the probe's
  self-update test (digits were never altered; formatting normalized back to match the
  portal submission).

### R4. Files changed in this addendum

- **Modified:** `femis-web/app.py` only (imports; startup migration index; `_b_form_digits` /
  `_b_form_conflict` / `_b_form_error` helpers; validation in `api_save_tab`,
  `api_final_submit`, `submit`).
- **DB data:** deleted student 7; added index `uq_students_b_form`.
- **Not changed:** job API, bot, selectors, mapping, templates, tests, your :5000 server
  (PID 15996).

### R5. Standing directives recorded for future runs

- No pseudo CNICs from now on; **Ahmed Khan (student 8) is the test student** for future
  E2E/verification runs.
- Portal "CNIC already used" resolution procedure: search Students by name ? match CNIC ?
  same record: edit it; not found by name: Show 100 entries + Ctrl+F, page through until
  found, report the holder's student name to the admin for manual real-world verification
  (�13). Our DB now rejects such duplicates up front with the holder's name in the error.

**STOP � awaiting approval before any 3B.7 work.** Known open items (not patched, need
admin decision): `test_bot_job_api.py` unscoped `DELETE FROM bot_jobs` cleanup (wiped the
E2E job rows post-capture); pre-existing `/students` 500 on `created_at=NULL`
(`templates/list.html:36`); optional bot enhancement to run the �13 CNIC paging search
automatically.
