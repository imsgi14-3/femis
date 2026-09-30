"""Phase 3B.5: bot-side job lifecycle against the Phase 3B.4 bot-job API.

Responsibilities (all integration-only — no bot redesign):
  * snapshot_to_student(): claim envelope -> flat student dict (no DB re-read)
  * HeartbeatWorker: independent lease heartbeat on a background thread
  * build_complete_payload(): success/failure evidence -> /complete body
  * classify_exception / classify_submit_failure: taxonomy mapping
  * run_job_loop(): claim -> execute -> complete until the queue is drained

The Playwright-facing work is injected as an async `worker(student,
on_progress, should_abort) -> WorkResult` callable, so the lifecycle is fully
testable without a browser and `src/main.py` only supplies a thin closure.

Success contract (API-enforced): outcome=success requires bot_result_code=
"success" AND finish_clicked + indicator_detected + outcome_known all true.
A fill-only run or "Finish clicked without indicator" is NEVER a success.
"""
import asyncio
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from src.utils.logger import setup_logger

logger = setup_logger("job_runner")

STATUS_SUCCESS = "success"
STATUS_SUBMIT_FAILED = "submit_failed"
STATUS_ERROR = "error"

NETWORK_RE = re.compile(
    r"network|connection|econn|failed to fetch|socket|dns|timed? ?out|unreachable",
    re.I,
)
TIMEOUT_RE = re.compile(r"timed? ?out|timeout|deadline exceeded", re.I)
CAPTCHA_RE = re.compile(r"captcha", re.I)
AUTH_RE = re.compile(r"log ?in|session expired|not authenticated|auth(entication)? fail", re.I)
FIELD_RE = re.compile(r"field[_ ]?map|source_field|mapping", re.I)

try:  # pragma: no cover - playwright is present in the bot environment
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover
    class PlaywrightError(Exception):
        pass

    class PlaywrightTimeoutError(PlaywrightError):
        pass


@dataclass
class WorkResult:
    """Outcome of one fill+submit pass (never raises through the runner)."""

    submitted: bool = False
    evidence: dict | None = None
    error: Exception | None = None
    failed_field: str | None = None


# ---------------------------------------------------------------------------
# Snapshot adapter
# ---------------------------------------------------------------------------

def snapshot_to_student(snapshot: dict) -> dict:
    """Claim envelope -> flat student dict, exactly the shape the form filler
    consumes (WebFormHandler.read_by_id minus metadata columns).

    The API materializes the snapshot atomically inside the claim
    transaction from the canonical row; by design there is NO re-read of the
    students table anywhere in this module. A mid-run student edit therefore
    cannot change what the filler sees.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("student_snapshot is missing")
    data = snapshot.get("data")
    if not isinstance(data, dict) or not data:
        raise ValueError("student_snapshot.data is missing or empty")
    student = dict(data)  # defensive copy: filler mutations never touch the claim
    if "transport" in student and "transport_facility" not in student:
        student["transport_facility"] = student.get("transport")
    # FEMIS directive (2026-09-30): the CNIC / Form-B availability question
    # is always answered "Yes" — force it regardless of the stored value so
    # legacy "0"/NULL rows still select the Yes radio (and the filler then
    # requires a real B-Form number, which the queue gate already ensures).
    student["is_bform_available"] = "1"
    return student


# CNIC-shaped fields validated as exactly 13 digits — mirrors the server's
# _cnic_length_error rule (femis-web/app.py). Empty values pass; the portal
# tolerates absent CNICs, but a present one must be complete.
CNIC_FIELDS = (
    ("b_form", "B-Form/CNIC"),
    ("father_cnic", "Father CNIC"),
    ("mother_cnic", "Mother CNIC"),
    ("guardian_cnic", "Guardian CNIC"),
)


def cnic_data_error(student: dict) -> str | None:
    """First incomplete CNIC value in the snapshot, else None.

    Dashes/spaces are display formatting and are stripped before the length
    check; anything else non-digit or not exactly 13 digits is reported with
    its field label so the error names what a human must fix.
    """
    for key, label in CNIC_FIELDS:
        raw = student.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        digits = re.sub(r"[\s-]", "", value)
        if not digits.isdigit() or len(digits) != 13:
            return f"{label}: must be exactly 13 digits without dashes (got '{value}')"
    return None


# ---------------------------------------------------------------------------
# Evidence -> API completion payload
# ---------------------------------------------------------------------------

def outcome_known_from_evidence(finish_clicked: bool, indicator_detected: bool) -> bool:
    """Explicit outcome knowledge rule (API requires an explicit boolean).

    No Finish click  => nothing was submitted (known).
    Finish + success indicator => submitted (known).
    Finish without indicator => uncertain (NOT known).
    """
    if indicator_detected:
        return True
    return not finish_clicked


def classify_exception(exc: BaseException) -> str:
    """Map an exception to the approved failure taxonomy (best effort)."""
    text = str(exc) or type(exc).__name__
    if isinstance(exc, (PlaywrightTimeoutError, TimeoutError, asyncio.TimeoutError)) or TIMEOUT_RE.search(text):
        if NETWORK_RE.search(text) and not isinstance(exc, (PlaywrightTimeoutError, TimeoutError, asyncio.TimeoutError)):
            return "network"
        if CAPTCHA_RE.search(text):
            return "captcha"
        return "timeout"
    if isinstance(exc, ConnectionError):
        return "network"
    if isinstance(exc, OSError) and NETWORK_RE.search(text):
        return "network"
    if CAPTCHA_RE.search(text):
        return "captcha"
    if FIELD_RE.search(text):
        return "field_mapping"
    if AUTH_RE.search(text):
        return "auth_portal"
    if isinstance(exc, ValueError):
        return "validation"
    if NETWORK_RE.search(text):
        return "network"
    if isinstance(exc, PlaywrightError):
        return "browser"
    return "unknown"


def _issue_lines(evidence: dict, errors: list[str], diag) -> list[str]:
    """Field-named issue lines for classify messages, most specific first.

    Source order: per-save blockers (label-named by _save_blockers),
    finish-time errors (label-named by _collect_errors), diagnostics
    blockers, empty required controls (DOM name), diagnostic texts, and
    the fill-traversal record (which tab stalled and on what field).
    Exact duplicates are dropped; callers cap count/length.
    """
    out: list[str] = []

    def add(items):
        for e in items or []:
            e = str(e).strip()
            if e and e not in out:
                out.append(e)

    add(evidence.get("blockers"))
    add(errors)
    if isinstance(diag, dict):
        add(diag.get("blockers"))
        for x in diag.get("emptyRequired") or []:
            nm = re.sub(
                r"\s*\[(?:required empty|radio required|checkbox required)\]\s*$",
                "", str(x),
            ).strip()
            if nm:
                add([f"{nm}: This field is required."])
        add(diag.get("errorTexts"))
    add(evidence.get("traversal_issues"))
    return out


def classify_submit_failure(evidence: dict | None) -> tuple[str, str]:
    """Evidence from submit_form -> (failure_category, error_message)."""
    evidence = evidence or {}
    finish = bool(evidence.get("finish_clicked"))
    indicator = bool(evidence.get("indicator_detected"))
    errors = [str(e) for e in (evidence.get("errors") or []) if e]
    diag = evidence.get("diagnostics")
    diag_text = ""
    if isinstance(diag, dict):
        diag_text = " ".join(str(x) for x in (diag.get("errorTexts") or []))

    # Human-intervention conflict: a portal duplicate (CNIC / admission no.)
    # that beat automatic recovery. Normalized to a stable message prefix —
    # the server's auto-queue keys on "Duplicate record conflict" to keep
    # these records out of automatic runs until a human queues them.
    dup = evidence.get("duplicate_conflict") or {}
    dup_errors = [str(e) for e in (dup.get("errors") or []) if e]
    if not dup_errors:
        dup_errors = [e for e in errors + ([diag_text] if diag_text else [])
                      if "already been taken" in e.lower()]
    if dup_errors:
        detail = "; ".join(dup_errors[:3])[:380]
        tab = dup.get("tab")
        where = f" (tab {tab})" if tab else ""
        return "validation", f"Duplicate record conflict{where}: {detail}"

    named = _issue_lines(evidence, errors, diag)

    if not finish:
        if named:
            return "validation", "Finish not available: " + "; ".join(named[:3])[:380]
        if indicator:
            return "femis", "Success indicator seen without a Finish click."
        return "femis", "Finish button not available/clicked; submission did not occur."

    text = f"{' '.join(errors)} {diag_text}".strip()
    if NETWORK_RE.search(text):
        return "network", (f"Finish clicked; network error before confirmation: {text[:300]}")
    if TIMEOUT_RE.search(text):
        return "timeout", (f"Finish clicked; timed out before confirmation: {text[:300]}")
    if named:
        return "validation", ("Validation errors blocked submission: " + "; ".join(named[:3])[:380])
    return "femis", "Finish clicked but success indicator not confirmed."


LOST_REASON_CATEGORY = {
    "api_unreachable": "network",
    "lease_expired": "timeout",
    "auth_rejected": "auth_portal",
    # Intentional (Phase 3B.5): fencing_conflict/invalid_transition/job_not_found
    # keep the classified default ("unknown") with bot_result_code="claim_lost".
    # The approved taxonomy has no superseded/abandoned value, and for fencing
    # losses the API rejects /complete anyway (fencing checked first) — so this
    # is a local report marker only; nothing is persisted on a job another
    # worker now owns.
}


def build_complete_payload(
    result: WorkResult,
    error: BaseException | None = None,
    stage: str | None = None,
    current_tab: int | None = None,
    last_completed_tab: int = 0,
    failed_field: str | None = None,
    lost_reason: str | None = None,
) -> dict:
    """Build the /complete body for one attempt (without claim fields).

    Success is ONLY reported from positive evidence (Finish + indicator +
    known outcome). `result.submitted` alone, a fill-only run, or a Finish
    click without the indicator are all failures. Evidence captured before a
    late screenshot error still wins, because the official submission state
    is what the evidence describes.
    """
    evidence = result.evidence or {}
    finish = bool(evidence.get("finish_clicked"))
    indicator = bool(evidence.get("indicator_detected"))
    exc = error if error is not None else result.error

    if evidence and finish and indicator:
        return {
            "outcome": "success",
            "bot_result_code": "success",
            "finish_clicked": True,
            "indicator_detected": True,
            "outcome_known": True,
            "last_completed_tab": max(int(last_completed_tab or 0), 0),
        }

    # --- structured failure ---
    if finish:
        category, message = classify_submit_failure(evidence)
        outcome_known = outcome_known_from_evidence(finish, indicator)
        result_code = "submit_failed"
    elif exc is not None:
        category = classify_exception(exc)
        message = f"{type(exc).__name__}: {exc}"[:900]
        # Interrupted during the verify phase (post-Finish attempt) => uncertain.
        outcome_known = not (stage == "verifying")
        result_code = "claim_lost" if lost_reason else "error"
    elif evidence:
        category, message = classify_submit_failure(evidence)
        outcome_known = outcome_known_from_evidence(finish, indicator)
        result_code = "submit_failed"
    else:
        category = "validation"
        message = "Attempt produced no submit evidence."
        outcome_known = True
        result_code = "error"

    if lost_reason:
        category = LOST_REASON_CATEGORY.get(lost_reason, category)
        message = f"[{lost_reason}] {message}"[:900]
        if not exc and not finish:
            result_code = "claim_lost"

    payload = {
        "outcome": "failed",
        "failure_category": category,
        "outcome_known": bool(outcome_known),
        "finish_clicked": bool(finish),
        "indicator_detected": bool(indicator),
        "bot_result_code": str(result_code)[:30],
        "error_message": message[:1000],
        "last_completed_tab": max(int(last_completed_tab or 0), 0),
    }
    if current_tab is not None and 1 <= int(current_tab) <= 7:
        payload["failed_tab"] = int(current_tab)
    if failed_field:
        payload["failed_field"] = str(failed_field)[:200]
    return payload


# ---------------------------------------------------------------------------
# Heartbeat (background thread; never touches Playwright)
# ---------------------------------------------------------------------------

class HeartbeatWorker(threading.Thread):
    """Extends the job lease while the attempt runs.

    Runs entirely on its own thread doing plain HTTP (stdlib client), so it
    never interacts with the Playwright event loop or the browser. Marks the
    claim lost on fencing/invalid transitions (superseded or cancelled by the
    operator), on lease expiry, or after repeated API failures — the filler's
    abort check then stops the run at the next tab boundary.
    """

    def __init__(self, client, job_id: int, claimed_by: str, claim_generation: int,
                 interval: float | None = None, lease_deadline: float | None = None,
                 error_streak_limit: int = 3, clock=time.time):
        super().__init__(name=f"job-heartbeat-{job_id}", daemon=True)
        self.client = client
        self.job_id = job_id
        self.claimed_by = claimed_by
        self.claim_generation = claim_generation
        if interval is None:
            try:
                interval = float(os.environ.get("FEMIS_JOB_HEARTBEAT_SECONDS") or 15)
            except ValueError:
                interval = 15.0
        self.interval = max(float(interval), 0.01)
        self.clock = clock
        self.lease_deadline = lease_deadline
        self.error_streak_limit = error_streak_limit
        self.error_streak = 0
        self.lost_reason: str | None = None
        self._stop_evt = threading.Event()

    def stop(self):
        self._stop_evt.set()

    def should_abort(self) -> bool:
        return self.lost_reason is not None

    def note_api_error(self):
        """Transient transport failure observed by the progress path."""
        self.error_streak += 1
        if self.error_streak >= self.error_streak_limit:
            self.lost_reason = "api_unreachable"

    def _note_result(self, status: int, body: dict):
        now = self.clock()
        if status == 200 and isinstance(body, dict) and body.get("ok"):
            self.error_streak = 0
            lease_secs = body.get("lease_seconds")
            try:
                lease_secs = float(lease_secs) if lease_secs else 60.0
            except (TypeError, ValueError):
                lease_secs = 60.0
            self.lease_deadline = now + lease_secs
            return
        if status == 409:
            code = (body or {}).get("error_code") or "lease_expired"
            self.lost_reason = code
            return
        if status in (401, 403):
            # Definitive: bad/rotated bot token will not self-heal this run.
            self.lost_reason = "auth_rejected"
            return
        if status == 404 and (body or {}).get("error_code") == "job_not_found":
            # Definitive: job row gone (e.g. cascade delete) — stop beating.
            self.lost_reason = "job_not_found"
            return
        # 5xx/0 (unreachable) -> transient streak; lease fallback below
        self.error_streak += 1
        if self.error_streak >= self.error_streak_limit:
            self.lost_reason = "api_unreachable"
            return
        if self.lease_deadline is not None and now > self.lease_deadline + 5:
            self.lost_reason = "lease_expired"

    def run(self):
        while not self._stop_evt.wait(self.interval):
            if self.lost_reason is not None:
                return
            try:
                status, body = self.client.heartbeat(
                    self.job_id, self.claimed_by, self.claim_generation
                )
            except Exception as e:  # client is non-raising; belt and braces
                logger.warning(f"Heartbeat exception: {e}")
                status, body = 0, {"error_code": "api_unreachable"}
            self._note_result(status, body)
            if self.lost_reason is not None:
                logger.warning(
                    f"Job {self.job_id}: heartbeat lost claim ({self.lost_reason})"
                )
                return
        # stopped normally


def parse_lease_deadline(iso_ts: str | None, default_seconds: float = 60.0) -> float:
    """API lease_expires_at (naive ISO) -> wall-clock deadline for the worker."""
    if not iso_ts:
        return time.time() + default_seconds
    try:
        s = str(iso_ts).replace("T", " ").replace("Z", "").strip()
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return time.time() + default_seconds


# ---------------------------------------------------------------------------
# Claim -> execute -> complete loop
# ---------------------------------------------------------------------------

async def _execute_claimed(client, claim_body: dict, claimed_by: str, worker,
                           heartbeat_cls) -> dict:
    job = claim_body.get("job") or {}
    snapshot = claim_body.get("student_snapshot") or {}
    job_id = job.get("job_id")
    generation = job.get("claim_generation")
    student_id = job.get("student_id")
    name = "unknown"

    state = {"stage": None, "current_tab": None, "last_completed": 0, "field": None}

    try:
        student = snapshot_to_student(snapshot)
        name = student.get("name") or student.get("student_name") or "unknown"
    except ValueError as e:
        # Claimed but unusable snapshot: fail closed, never fill.
        logger.error(f"Job {job_id}: invalid snapshot: {e}")
        payload = {
            "outcome": "failed",
            "failure_category": "validation",
            "outcome_known": True,  # no FEMIS work started
            "bot_result_code": "error",
            "error_message": f"Invalid student snapshot: {e}"[:1000],
        }
        status, resp = client.complete(job_id, claimed_by, generation, payload)
        ok = status == 200 and bool(resp.get("ok"))
        return {
            "job_id": job_id, "student_id": student_id, "student": name,
            "status": STATUS_ERROR, "submitted": None,
            "reason": f"invalid snapshot (complete {'ok' if ok else f'failed: {status}'})",
            "complete_ok": ok,
        }

    # Incomplete CNIC/B-Form data: fail closed before any FEMIS work — the
    # portal rejects partial CNICs mid-fill (or silently creates bad records),
    # so a human must fix the field first. Mirrors the server's
    # _cnic_length_error gate for legacy rows that predate it.
    cnic_err = cnic_data_error(student)
    if cnic_err:
        logger.error(f"Job {job_id}: {cnic_err}")
        payload = {
            "outcome": "failed",
            "failure_category": "validation",
            "outcome_known": True,  # no FEMIS work started
            "bot_result_code": "error",
            "error_message": f"Incomplete CNIC — record not filled: {cnic_err}"[:1000],
        }
        status, resp = client.complete(job_id, claimed_by, generation, payload)
        ok = status == 200 and bool((resp or {}).get("ok"))
        return {
            "job_id": job_id, "student_id": student_id, "student": name,
            "status": STATUS_ERROR, "submitted": None,
            "reason": payload["error_message"],
            "failure_category": "validation",
            "complete_ok": ok,
        }

    hb = heartbeat_cls(
        client, job_id, claimed_by, generation,
        lease_deadline=parse_lease_deadline(job.get("lease_expires_at")),
    )

    async def on_progress(tab=None, stage=None, field=None, last_completed=None, detail=None):
        if stage:
            state["stage"] = stage
        if tab:
            state["current_tab"] = int(tab)
        if field:
            state["field"] = field
        if last_completed:
            state["last_completed"] = int(last_completed)
        st, resp = client.progress(
            job_id, claimed_by, generation,
            current_tab=tab, last_completed_tab=last_completed,
            current_field=field, detail=detail or stage,
        )
        code = (resp or {}).get("error_code")
        if st == 409 and code in ("fencing_conflict", "invalid_transition", "job_not_found"):
            hb.lost_reason = code
            logger.warning(f"Job {job_id}: progress rejected ({code}) — claim lost")
        elif st == 409 and code == "lease_expired":
            hb.lost_reason = "lease_expired"
            logger.warning(f"Job {job_id}: lease expired during progress")
        elif st in (401, 403):
            hb.lost_reason = "auth_rejected"
            logger.warning(f"Job {job_id}: progress rejected HTTP {st} — bot token invalid")
        elif st == 0 or (isinstance(st, int) and st >= 500):
            hb.note_api_error()
        elif st >= 400:
            logger.warning(f"Job {job_id}: progress rejected HTTP {st} {code}")

    hb.start()
    result = WorkResult()
    error: BaseException | None = None
    try:
        result = await worker(student, on_progress, hb.should_abort)
        if not isinstance(result, WorkResult):
            result = WorkResult()
    except Exception as e:  # worker should catch; runner must still complete the job
        logger.error(f"Job {job_id}: worker raised: {type(e).__name__}: {e}")
        error = e
        result = WorkResult(evidence=None)
    finally:
        hb.stop()
        hb.join(timeout=5)

    payload = build_complete_payload(
        result,
        error=error,
        stage=state.get("stage"),
        current_tab=state.get("current_tab"),
        last_completed_tab=state.get("last_completed") or 0,
        failed_field=state.get("field"),
        lost_reason=hb.lost_reason,
    )

    st, resp = client.complete(job_id, claimed_by, generation, payload)
    complete_ok = st == 200 and bool((resp or {}).get("ok"))
    if complete_ok:
        logger.info(f"Job {job_id}: completed -> {payload['outcome']}"
                    + (f"/{payload.get('failure_category')}" if payload["outcome"] == "failed" else ""))
    else:
        code = (resp or {}).get("error_code")
        if code in ("fencing_conflict", "invalid_transition"):
            logger.warning(
                f"Job {job_id}: completion rejected — superseded/finished elsewhere ({code}); "
                "no new attempt created by this worker."
            )
        elif code == "lease_expired":
            logger.warning(f"Job {job_id}: completion rejected — lease expired ({code}).")
        else:
            logger.error(f"Job {job_id}: complete failed HTTP {st} {code}: {(resp or {}).get('error')}")

    if payload["outcome"] == "success":
        local_status = STATUS_SUCCESS
    elif error is not None or hb.lost_reason:
        local_status = STATUS_ERROR
    else:
        local_status = STATUS_SUBMIT_FAILED
    return {
        "job_id": job_id,
        "student_id": student_id,
        "student": name,
        "status": local_status,
        "submitted": payload["outcome"] == "success",
        "reason": None if payload["outcome"] == "success" else payload.get("error_message"),
        "failure_category": payload.get("failure_category"),
        "complete_ok": complete_ok,
        "lost_reason": hb.lost_reason,
    }


async def run_job_loop(client, claimed_by: str, worker, heartbeat_cls=HeartbeatWorker,
                       on_result=None, claim_pause: float = 0.5) -> tuple[str, dict]:
    """Claim -> execute -> complete until no pending job remains.

    Returns (exit_reason, detail):
      "idle"       queue drained (clean exit)
      "error"      claim/auth/config failure — stop looping
    Conflict retries (another worker won the race) and DATA_STALE rows
    (API already failed them closed — never filled) continue to the next job.
    """
    while True:
        status, body = client.claim(claimed_by)
        body = body or {}
        code = body.get("error_code")

        if status == 200 and body.get("ok"):
            try:
                record = await _execute_claimed(client, body, claimed_by, worker, heartbeat_cls)
            except Exception as e:
                logger.exception(f"Claimed job execution failed before completion: {e}")
                record = {
                    "job_id": (body.get("job") or {}).get("job_id"),
                    "student_id": (body.get("job") or {}).get("student_id"),
                    "student": "unknown",
                    "status": STATUS_ERROR, "submitted": None,
                    "reason": f"runner error: {e}", "complete_ok": False,
                }
            if on_result:
                on_result(record)
            continue

        if status == 404 and code == "no_pending_job":
            logger.info("No pending jobs - queue drained.")
            return "idle", body

        if status == 409 and code == "queue_paused":
            logger.info("Job queue is paused by an administrator - nothing to claim.")
            return "idle", body

        if status == 409 and code in ("claim_conflict", "already_claimed"):
            logger.warning(f"Claim race lost ({code}); retrying next job...")
            await asyncio.sleep(claim_pause)
            continue

        if status == 409 and code == "DATA_STALE":
            # API already failed this job closed. Never fill from stale data.
            logger.warning(f"DATA_STALE: {body.get('error')}")
            job = body.get("job") or {}
            if on_result:
                on_result({
                    "job_id": job.get("job_id"),
                    "student_id": job.get("student_id"),
                    "student": "unknown",
                    "status": STATUS_ERROR, "submitted": False,
                    "reason": f"DATA_STALE: {body.get('error') or 'stale student data'}",
                    "failure_category": "validation", "complete_ok": True,
                })
            continue

        logger.error(f"Claim failed HTTP {status} {code}: {body.get('error')}")
        return "error", body
