# Phase 3B.5 — Bot Integration with Bot-Job API

Authority: Phase 3B.5 brief, `docs/phase3b4-job-api.md`, `docs/phase3b2-2-final-design-decisions.md`.

## Scope

Connects the existing FEMIS bot process to the Phase 3B.4 job lifecycle:

```
claim (snapshot) -> heartbeat thread + progress -> fill -> submit -> evidence -> complete
```

No bot redesign. The bot keeps its existing batch mode (`python -m src.main <source>`)
byte-for-byte in behavior; job mode is a new opt-in entry point:

```
set FEMIS_BOT_TOKEN=...            # fail-closed, required
set FEMIS_JOB_API_URL=http://127.0.0.1:5000
python -m src.main --jobs
```

## Files

### Created
| File | Purpose |
|---|---|
| `src/job_api_client.py` | stdlib `urllib` client for claim/heartbeat/progress/complete. Never raises: transport errors return `(0, {error_code: api_unreachable})`. Fails closed when `FEMIS_BOT_TOKEN` is unset. |
| `src/job_runner.py` | Lifecycle core: `snapshot_to_student`, `HeartbeatWorker`, `build_complete_payload`, `classify_exception`, `classify_submit_failure`, `run_job_loop`. |
| `test_bot_job_bot_integration.py` | 54 checks against the real API on a local ephemeral-port Werkzeug server (no Playwright, no live FEMIS). |
| `docs/phase3b5-bot-integration.md` | This document. |

### Modified (integration seams only — all reported per brief §22)
| File | Change |
|---|---|
| `src/main.py` | `--jobs` flag (source becomes optional), `jobs=True` branch skips `load_student_data`, calls new `_run_job_cycles(page)` after login; job results appended to the existing `self.results` report. `classify_student_result` untouched. |
| `src/form_filler.py` | Four minimal seams, all no-ops in batch mode: (1) `__init__` attrs (`progress_callback`, `abort_check`, `last_submit`, `_last_attempted_field`); (2) `_notify_progress()` helper + 5 call sites (tab fill start, save result, final save, submitting, verifying); (3) `_last_attempted_field = field_name` line in `_fill_field`; (4) `last_submit` evidence dict recorded in `submit_form` before the screenshot (reset to `None` at submit start). Return values, selectors, mapping, and success semantics unchanged. |
| `.env.example` | `FEMIS_JOB_API_URL` placeholder line. |

### Untouched (verified)
`femis-web/app.py` (routes), `femis-web/job_api.py`, `femis-web/static/form.js`,
`femis-web/templates/form.html`, `config/field_mapping.yaml`, `config/settings.yaml`,
`src/auth.py`, `src/data_sources/webform_handler.py`, all existing test files.

## Key design points

1. **Snapshot is the only data source in job mode.** `snapshot_to_student()` copies
   `student_snapshot.data` (already stripped of `id/created_at/updated_at/processed`,
   transport-aliased) and passes it to `fill_student_form`/`submit_form`. The job path
   never imports or calls `WebFormHandler` — proven by test B5 (DB accessors patched to
   raise during a full cycle). Mid-run student edits cannot change filler input (B3).

2. **Heartbeat is a plain thread doing plain HTTP** (`HeartbeatWorker`), independent of
   the Playwright event loop. Interval/lease come from API heartbeat responses and
   `FEMIS_JOB_HEARTBEAT_SECONDS` — no duplicated lease constants. It marks the claim
   lost on: fencing/invalid transition, lease expiry, or 3 consecutive API failures
   (or local lease deadline + 5s). Lost claim -> `abort_check()` -> `_notify_progress`
   raises -> fill stops at the next tab boundary; if the submit phase was already
   reached (`stage == "verifying"`), the outcome is recorded as uncertain
   (`outcome_known=false`).

3. **Success evidence only from `submit_form`.** `is_submission_success(finish, indicator)`
   already equals the API contract. Evidence dict: `{finish_clicked, indicator_detected,
   outcome_known, errors[:10], diagnostics}`. Rules:
   - no Finish click -> outcome known (nothing submitted); category `validation` (portal
     errors present) else `femis`
   - Finish without indicator -> outcome UNcertain (`outcome_known=false`); category from
     error text (`network`/`timeout`/`validation`/`femis`)
   - Finish + indicator -> success payload (`bot_result_code=success`, all flags true)
   - fill-only / indicator-only are never success (API would 422; builder never sends them)
   - a late exception (e.g. screenshot) after captured success evidence still completes
     success, because evidence describes the official submission state.

4. **Failure taxonomy mapping** (`classify_exception`): timeouts -> `timeout`,
   connection/network text -> `network`, field-mapping text -> `field_mapping`,
   `ValueError` -> `validation`, captcha text -> `captcha`, auth text -> `auth_portal`,
   Playwright errors -> `browser`, else `unknown`. Lost-claim overlays and the
   **intentional** `claim_lost` mapping:

   | `lost_reason` | category | `bot_result_code` | persisted? |
   |---|---|---|---|
   | `api_unreachable` | `network` | `claim_lost` | only if server recovers by complete-time |
   | `lease_expired` | `timeout` | `claim_lost` | almost never (complete rejected 409 `lease_expired`) |
   | `auth_rejected` (401/403) | `auth_portal` | `claim_lost` | no (complete rejected by token gate) |
   | `fencing_conflict` / `invalid_transition` / `job_not_found` | **`unknown`** | **`claim_lost`** | **no — fencing checked first in `/complete`, rejected 409** |
   | no lost reason (normal fill/submit failure) | classified | `error` / `submit_failed` | yes |

   The `fencing -> unknown + claim_lost` pair is deliberate: the approved 10-value
   taxonomy (3B.3/3B.4) has no superseded/abandoned value and must not be extended
   unilaterally; a superseded job belongs to its new claimant, so the API rejects
   our completion anyway — this is a **local report marker** only. `bot_result_code`
   `claim_lost` (<=30 chars) distinguishes "aborted due to claim loss" from generic
   `error`/`submit_failed` in logs and local reports. `H2` verifies the rejection;
   `M10` verifies the mapping.

   Heartbeat failure/expiry semantics (`HeartbeatWorker._note_result`): success
   resets the error streak and extends the local lease deadline (from the API's
   `lease_seconds`); 409 -> definitive lost (`fencing_conflict`/`lease_expired`/...);
   401/403 -> definitive `auth_rejected` (fail fast, no streak); 404
   `job_not_found` -> definitive; 5xx/transport -> transient streak, lost after 3
   consecutive (default `error_streak_limit=3`) OR when the local lease deadline
   +5s passes. The progress path mirrors this and additionally feeds
   `note_api_error()` streaks. Verified by tests `C1-C4` (live API) and `M1-M9`
   (unit: streak accumulation, reset-on-success, auth/job-loss immediacy, local
   deadline fallback, thread behavior, clean stop).

5. **Progress** posts only at tab granularity (~14 posts/job): filling, saved/save_failed,
   final_save, submitting, verifying; includes `current_tab`, `last_completed_tab`,
   `current_field` (last attempted). Server stores lines in `error_message`
   (3B.4 storage choice). First progress performs `claimed -> running`.

6. **Claim loop** (`run_job_loop`): claim-next until `no_pending_job` (clean exit);
   `claim_conflict`/`already_claimed` -> short pause, next job; `DATA_STALE` -> log,
   record `reason="DATA_STALE: ..."`, never fill, continue; auth/config errors -> stop.
   No direct `bot_jobs` writes anywhere in the bot; no auto job creation; no auto retry
   (operator retry creates the new attempt, next claim picks it up).

7. **Superseded/lost workers never create attempts**: complete with stale generation is
   rejected 409 `fencing_conflict` (test H2) and logged; job remains owned by its current
   claimant. v1 still has no lease-steal: an expired open job is unrecoverable without
   operator action (inherited 3B.4 gap, documented in `docs/phase3b4-job-api.md` §8).

## Test coverage (test_bot_job_bot_integration.py, 54/54)

- A: auth (fail-closed client, wrong token), claim contract, snapshot envelope, second claimant
- B: snapshot parity with `read_by_id`, transport alias, mid-run edit immutability,
  invalid snapshot, full cycle with DB accessors patched to raise
- C: heartbeat extends lease, stale generation -> fencing + abort, expired lease -> lost
- D: progress claimed->running, tab/field persistence, stale-gen fencing,
  failed completion preserves progress fields
- E: success only with full evidence; fill-only, Finish-only, indicator-only all failed;
  late-exception-with-evidence still success; fill-stage exception -> validation/known
- F: DATA_STALE never filled, loop continues to next job
- G: operator retry -> attempt 2 succeeds, attempt 1 preserved
- H: superseded generation cannot complete; mid-run supersede aborts + rejected complete
- I: FormFiller seams (no-op default, kwargs, abort, exception propagation,
  field tracking, evidence rules, fill-only payload never success)
- J: taxonomy units + payload bounds (message<=1000, code<=30, tab ranges)
- K: real FormFiller -> runner -> API chain (progress lines land in job row)
- L: loop exits (conflict retry then drain, auth failure stops)
- M: heartbeat failure/expiry semantics (streak accumulation, reset-on-success,
  auth/job-loss immediacy, local lease deadline fallback, thread behavior,
  clean stop, lost-reason category overlays incl. claim_lost/unknown)

## Verification status

- Unit/integration verified: everything above, all against the real 3B.4 API
  (ephemeral local server) — **54/54**.
- Regression suites unchanged and green: schema **61/61**, API **123/123**,
  integrity **24/24**, submission-status **12/12**, smoke **14/14**, smoke-bot **3/3**.
- NOT verified against official FEMIS: actual browser fill/submit in `--jobs` mode
  (requires live portal + CAPTCHA login). The Playwright-facing code path is exactly the
  existing `fill_student_form`/`submit_form` batch code; only the four reported seams
  were added.
