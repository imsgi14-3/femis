"""Phase 3B.4 — Bot-Job API (human/admin + bot-machine endpoints).

Store/lifecycle layer only. No browser automation, no bot execution, no admin UI,
no FEMIS credentials, no automatic job creation on final-submit.

Authority: docs/phase3b2-2-final-design-decisions.md (A–O), Phase 3B.4 brief.
Auth model, DATA_STALE representation, lease config: docs/phase3b4-job-api.md.

This module deliberately has NO top-level `from app import ...` (the app imports
this blueprint); core objects are resolved lazily per request so both `python app.py`
and `from app import app` entry points work.
"""
import hmac
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, session
from sqlalchemy.exc import IntegrityError

try:  # local dev convenience; never overrides already-set environment variables
    from dotenv import load_dotenv
    _dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    if _dotenv_path.exists():
        load_dotenv(_dotenv_path)
except Exception:  # pragma: no cover
    pass

bp = Blueprint("job_api", __name__)

# Runtime configuration (NOT design constants — see docs/phase3b4-job-api.md).
# The candidate values 15s/60s from 3B.2.1 Decision 3 are development defaults only.
DEFAULT_LEASE_SECONDS = 60
DEFAULT_HEARTBEAT_SECONDS = 15


def _core():
    """Resolve the application module holding db/models (entry-point agnostic)."""
    for name in ("app", "__main__"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BotJob"):
            return mod
    import app as app_mod  # normal import path
    return app_mod


def _config_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _now():
    return datetime.utcnow()


def _iso(dt):
    if dt is None:
        return None
    return dt.isoformat(sep=" ", timespec="microseconds")


def _sanitize(value, limit=1000):
    """Strip control characters, collapse whitespace, truncate. Never raise."""
    if value is None:
        return None
    s = str(value)
    s = "".join(ch if (ch >= " " or ch in "\t") else " " for ch in s)
    s = re.sub(r"\s+", " ", s).strip()
    if limit is not None and len(s) > limit:
        s = s[:limit]
    return s


def _err(message, code, http):
    return jsonify({"ok": False, "error": message, "error_code": code}), http


def _fail(message, code, http):
    """Service-layer result form: plain (payload, status) for wrapper jsonify."""
    return {"ok": False, "error": message, "error_code": code}, http


def _payload():
    return request.get_json(silent=True) or {}


def _as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


# ---------------------------------------------------------------------------
# Authentication / authorization
# ---------------------------------------------------------------------------

def _require_operator():
    """Human/admin gate: portal session (role=teacher or admin) + operator token.

    The narrowest approved boundary: an authenticated portal session that is
    a teacher or admin, PLUS the focal-person operator token from the
    environment. Fails closed when the token is not configured.
    """
    configured = (os.environ.get("FEMIS_OPERATOR_TOKEN") or "").strip()
    if not session.get("role"):
        return _err("Authentication required.", "authentication_required", 401)
    if session.get("role") not in ("teacher", "admin"):
        return _err(
            "Job administration is restricted to the portal operator.",
            "forbidden_role",
            403,
        )
    if not configured:
        return _err(
            "Operator job API is not configured.",
            "operator_token_not_configured",
            403,
        )
    presented = request.headers.get("X-Operator-Token", "")
    if not presented or not hmac.compare_digest(presented, configured):
        return _err("Valid operator token required.", "operator_token_invalid", 403)
    return None


def _require_bot():
    """Bot-machine gate: dedicated machine token from the environment.

    Fails closed when the token is not configured. Never FEMIS credentials.
    """
    configured = (os.environ.get("FEMIS_BOT_TOKEN") or "").strip()
    if not configured:
        return _err("Bot job API is not configured.", "bot_token_not_configured", 403)
    presented = request.headers.get("X-Bot-Token", "")
    if not presented or not hmac.compare_digest(presented, configured):
        return _err("Valid bot machine token required.", "invalid_bot_token", 401)
    return None


def _operator_identity():
    return _sanitize(session.get("user_name") or "operator", 100) or "operator"


# ---------------------------------------------------------------------------
# Queue pause state (admin Bot Management; stored in app_settings)
# ---------------------------------------------------------------------------

BOT_QUEUE_KEY = "bot_queue"


def queue_paused():
    """True when an administrator paused the claim queue (app_settings row)."""
    core = _core()
    AppSetting = getattr(core, "AppSetting", None)
    if AppSetting is None:  # pragma: no cover - app.py always defines the model
        return False
    db = core.db
    try:
        row = db.session.get(AppSetting, BOT_QUEUE_KEY)
    except Exception:
        db.session.rollback()
        return False
    return bool(row is not None and row.value == "paused")


def set_queue_paused(paused):
    """Persist queue pause state ('paused' | 'running'); returns the stored value."""
    core = _core()
    db, AppSetting = core.db, core.AppSetting
    value = "paused" if paused else "running"
    row = db.session.get(AppSetting, BOT_QUEUE_KEY)
    if row is None:
        db.session.add(AppSetting(key=BOT_QUEUE_KEY, value=value))
    else:
        row.value = value
    db.session.commit()
    return value


# ---------------------------------------------------------------------------
# Version tokens (students.updated_at)
# ---------------------------------------------------------------------------

def _parse_version_token(token):
    """Parse a client version token -> (datetime | None, exact: bool).

    Accepts ISO-8601 (microsecond round-trip when a fraction is present) and
    RFC-822 HTTP-date (second precision, e.g. what /students/<id>/json emits).
    """
    if not isinstance(token, str) or not token.strip():
        return None, False
    t = token.strip()
    try:
        if "," in t:  # RFC-822 (email/HTTP date)
            dt = parsedate_to_datetime(t)
            if dt is None:
                return None, False
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt, False
        if t.endswith(("Z", "z")):
            t = t[:-1]
        t = t.replace("T", " ")
        return datetime.fromisoformat(t), "." in t
    except (ValueError, TypeError):
        return None, False


def _version_matches(token_dt, exact, current):
    if current is None or token_dt is None:
        return False
    if exact:
        return token_dt == current
    return token_dt.replace(microsecond=0) == current.replace(microsecond=0)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _job_dict(job):
    core = _core()
    now = _now()
    lease = job.lease_expires_at
    status = job.status
    data_stale = job.bot_result_code == "DATA_STALE"
    return {
        "job_id": job.id,
        "student_id": job.student_id,
        "attempt_number": job.attempt_number,
        "status": status,
        "created_at": _iso(job.created_at),
        "requested_at": _iso(job.requested_at),
        "retry_requested_at": _iso(job.retry_requested_at),
        "claimed_at": _iso(job.claimed_at),
        "claimed_by": job.claimed_by,
        "started_at": _iso(job.started_at),
        "completed_at": _iso(job.completed_at),
        "last_heartbeat_at": _iso(job.last_heartbeat_at),
        "lease_expires_at": _iso(lease),
        "lease_active": bool(
            lease is not None and lease > now and status in core.BOT_JOB_OPEN_STATUSES
        ),
        "claim_generation": job.claim_generation,
        "student_data_version": _iso(job.student_data_version),
        "snapshot_materialized_at": _iso(job.snapshot_materialized_at),
        "has_snapshot": job.snapshot_json is not None,
        "current_tab": job.current_tab,
        "last_completed_tab": job.last_completed_tab,
        "failed_tab": job.failed_tab,
        "failed_field": job.failed_field,
        "failure_category": job.failure_category,
        "error_message": _sanitize(job.error_message, 1000),
        "outcome_known": job.outcome_known,
        "bot_result_code": job.bot_result_code,
        "finish_clicked": job.finish_clicked,
        "indicator_detected": job.indicator_detected,
        "prior_attempt_id": job.prior_attempt_id,
        "created_by": job.created_by,
        "idempotency_key": job.idempotency_key,
        "retryable": status in ("failed", "cancelled"),
        "data_stale": data_stale,
    }


# ---------------------------------------------------------------------------
# Service layer (shared by the HTTP endpoints below and the admin Bot Queue)
# ---------------------------------------------------------------------------
# Every svc_* returns a plain (payload, http_status) tuple so both endpoint
# wrappers (jsonify) and in-process admin callers (app.py) use one code path.

def svc_create(payload, identity):
    """Create a pending submit-mode job for one student."""
    core = _core()
    db, Student, BotJob = core.db, core.Student, core.BotJob

    mode = payload.get("mode")
    if mode not in (None, "submit"):
        return _fail("Only submit-mode jobs are supported in v1.", "unsupported_mode", 400)

    student_id = _as_int(payload.get("student_id"))
    if student_id is None:
        return _fail("student_id is required and must be an integer.", "validation_error", 422)

    student = db.session.get(Student, student_id)
    if student is None:
        return _fail("Student not found.", "student_not_found", 404)

    token_dt, exact = _parse_version_token(payload.get("student_data_version"))
    if token_dt is None:
        return _fail(
            "student_data_version is required (ISO-8601 or HTTP-date).",
            "validation_error",
            422,
        )
    current = student.updated_at
    if current is None:
        return _fail(
            "Student record has no version (updated_at) yet.",
            "student_version_unavailable",
            422,
        )
    if not _version_matches(token_dt, exact, current):
        return _fail(
            "student_data_version does not match the current student record.",
            "version_mismatch",
            422,
        )

    idempotency_key = payload.get("idempotency_key")
    if idempotency_key is not None:
        idempotency_key = _sanitize(idempotency_key, 120)
        if not idempotency_key:
            idempotency_key = None
    if idempotency_key:
        existing = BotJob.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return {"ok": True, "job": _job_dict(existing), "idempotent": True}, 200

    open_job = BotJob.query.filter(
        BotJob.student_id == student_id,
        BotJob.status.in_(core.BOT_JOB_OPEN_STATUSES),
    ).first()
    if open_job is not None:
        return (
            {
                "ok": False,
                "error": "An open job already exists for this student.",
                "error_code": "open_job_exists",
                "existing_job": _job_dict(open_job),
            },
            409,
        )

    highest = (
        db.session.query(db.func.max(BotJob.attempt_number))
        .filter(BotJob.student_id == student_id)
        .scalar()
    )
    job = BotJob(
        student_id=student_id,
        attempt_number=(highest or 0) + 1,
        status="pending",
        student_data_version=current,  # exact expected version (decision A/K)
        requested_at=_now(),
        created_by=_sanitize(identity, 100) or "operator",
        idempotency_key=idempotency_key,
    )
    db.session.add(job)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # Concurrent create: unique partial open index or idempotency key won.
        if idempotency_key:
            existing = BotJob.query.filter_by(idempotency_key=idempotency_key).first()
            if existing:
                return {"ok": True, "job": _job_dict(existing), "idempotent": True}, 200
        open_job = BotJob.query.filter(
            BotJob.student_id == student_id,
            BotJob.status.in_(core.BOT_JOB_OPEN_STATUSES),
        ).first()
        if open_job is not None:
            return (
                {
                    "ok": False,
                    "error": "An open job already exists for this student.",
                    "error_code": "open_job_exists",
                    "existing_job": _job_dict(open_job),
                },
                409,
            )
        return _fail("Job could not be created due to a concurrent update.", "create_conflict", 409)

    return {"ok": True, "job": _job_dict(job)}, 200


@bp.route("/api/jobs", methods=["POST"])
def create_job():
    guard = _require_operator()
    if guard:
        return guard
    data, status = svc_create(_payload(), _operator_identity())
    return jsonify(data), status


def svc_list(args):
    """List jobs with optional filters/paging (args: request.args-like mapping)."""
    core = _core()
    BotJob = core.BotJob

    query = BotJob.query

    student_id = args.get("student_id")
    if student_id is not None:
        sid = _as_int(student_id)
        if sid is None:
            return _fail("student_id filter must be an integer.", "validation_error", 422)
        query = query.filter(BotJob.student_id == sid)

    status_filter = args.get("status")
    if status_filter is not None:
        if status_filter not in core.BOT_JOB_STATUSES:
            return _fail("Unknown status filter.", "validation_error", 422)
        query = query.filter(BotJob.status == status_filter)

    order = (args.get("order") or "desc").lower()
    if order not in ("asc", "desc"):
        return _fail("order must be 'asc' or 'desc'.", "validation_error", 422)

    limit_raw = args.get("limit")
    limit = _as_int(limit_raw) if limit_raw is not None else None
    if limit_raw is not None and limit is None:
        return _fail("limit must be an integer.", "validation_error", 422)
    if limit is None:
        limit = 50
    if not (1 <= limit <= 200):
        return _fail("limit must be between 1 and 200.", "validation_error", 422)
    offset_raw = args.get("offset")
    offset = _as_int(offset_raw) if offset_raw is not None else None
    if offset_raw is not None and offset is None:
        return _fail("offset must be an integer.", "validation_error", 422)
    if offset is None:
        offset = 0
    if offset < 0:
        return _fail("offset must be >= 0.", "validation_error", 422)

    total = query.count()
    direction = BotJob.created_at.asc() if order == "asc" else BotJob.created_at.desc()
    jobs = (
        query.order_by(direction, BotJob.id.desc()).offset(offset).limit(limit).all()
    )
    return (
        {
            "ok": True,
            "jobs": [_job_dict(j) for j in jobs],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        200,
    )


@bp.route("/api/jobs", methods=["GET"])
def list_jobs():
    guard = _require_operator()
    if guard:
        return guard
    data, status = svc_list(request.args)
    return jsonify(data), status


@bp.route("/api/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id):
    guard = _require_operator()
    if guard:
        return guard
    core = _core()
    job = core.db.session.get(core.BotJob, job_id)
    if job is None:
        return _err("Job not found.", "job_not_found", 404)
    return jsonify({"ok": True, "job": _job_dict(job)})


def svc_retry(job_id, payload, identity):
    """Explicit operator retry: appends a NEW attempt, never overwrites history."""
    core = _core()
    db, BotJob, Student = core.db, core.BotJob, core.Student

    job = db.session.get(BotJob, job_id)
    if job is None:
        return _fail("Job not found.", "job_not_found", 404)
    if job.status not in ("failed", "cancelled"):
        return _fail(
            "Retry is only allowed for failed or cancelled attempts.",
            "invalid_transition",
            409,
        )

    # A requeue must run on the LATEST student data (operator requirement):
    # refresh the expected version by default so the next claim re-materializes
    # a fresh snapshot from the current row.  Pass refresh_snapshot=false
    # explicitly to pin an approved version instead — the claim then fails
    # closed as DATA_STALE if the student changed since.
    refresh_snapshot = bool(payload.get("refresh_snapshot", True))

    student = db.session.get(Student, job.student_id)
    if refresh_snapshot:
        if student is None:
            return _fail("Student not found.", "student_not_found", 404)
        if student.updated_at is None:
            return _fail(
                "Student record has no version (updated_at) yet.",
                "student_version_unavailable",
                422,
            )
        new_version = student.updated_at
    else:
        # Retain the approved expected version; if the student changed since,
        # the next claim fails closed as DATA_STALE until refresh is explicit.
        new_version = job.student_data_version

    other_open = BotJob.query.filter(
        BotJob.student_id == job.student_id,
        BotJob.status.in_(core.BOT_JOB_OPEN_STATUSES),
    ).first()
    if other_open is not None:
        return (
            {
                "ok": False,
                "error": "An open job already exists for this student.",
                "error_code": "open_job_exists",
                "existing_job": _job_dict(other_open),
            },
            409,
        )

    highest = (
        db.session.query(db.func.max(BotJob.attempt_number))
        .filter(BotJob.student_id == job.student_id)
        .scalar()
    )
    new_job = BotJob(
        student_id=job.student_id,
        attempt_number=(highest or 0) + 1,
        status="pending",
        student_data_version=new_version,
        requested_at=_now(),
        retry_requested_at=_now(),
        created_by=_sanitize(identity, 100) or "operator",
        prior_attempt_id=job.id,
    )
    db.session.add(new_job)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _fail("Concurrent retry conflict.", "retry_conflict", 409)

    return (
        {
            "ok": True,
            "job": _job_dict(new_job),
            "prior_attempt": _job_dict(job),
            "refresh_snapshot": refresh_snapshot,
        },
        200,
    )


@bp.route("/api/jobs/<int:job_id>/retry", methods=["POST"])
def retry_job(job_id):
    guard = _require_operator()
    if guard:
        return guard
    data, status = svc_retry(job_id, _payload(), _operator_identity())
    return jsonify(data), status


def svc_cancel(job_id):
    """v1 cancellation: pending -> cancelled only (CAS)."""
    core = _core()
    db, BotJob = core.db, core.BotJob

    job = db.session.get(BotJob, job_id)
    if job is None:
        return _fail("Job not found.", "job_not_found", 404)

    now = _now()
    updated = BotJob.query.filter(
        BotJob.id == job_id, BotJob.status == "pending"
    ).update(
        {
            "status": "cancelled",
            "completed_at": now,
            "failure_category": "cancelled_by_operator",
            "outcome_known": True,  # nothing was sent to FEMIS — outcome is known
            "error_message": "Cancelled by operator before claim.",
        },
        synchronize_session=False,
    )
    if updated != 1:
        db.session.rollback()
        db.session.refresh(job)
        if job.status in core.BOT_JOB_OPEN_STATUSES:
            return _fail(
                "Job is no longer pending (claim may have won the race).",
                "cancel_conflict",
                409,
            )
        return _fail("Job is already terminal.", "invalid_transition", 409)
    db.session.commit()
    db.session.refresh(job)
    return {"ok": True, "job": _job_dict(job)}, 200


@bp.route("/api/jobs/<int:job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    guard = _require_operator()
    if guard:
        return guard
    data, status = svc_cancel(job_id)
    return jsonify(data), status


# ---------------------------------------------------------------------------
# Bot-machine endpoints
# ---------------------------------------------------------------------------

@bp.route("/api/jobs/claim", methods=["POST"])
def claim_job():
    """Atomic CAS claim: pending -> claimed, version check, snapshot materialization.

    Single transaction: CAS -> read student -> version compare -> snapshot.
    Any failure rolls back so the job remains claimable.
    """
    guard = _require_bot()
    if guard:
        return guard
    if queue_paused():
        return _err(
            "Job queue is paused by an administrator.",
            "queue_paused",
            409,
        )
    core = _core()
    db, BotJob, Student = core.db, core.BotJob, core.Student

    payload = _payload()
    claimed_by = _sanitize(payload.get("claimed_by"), 80)
    if not claimed_by:
        return _err("claimed_by is required.", "validation_error", 422)

    requested_id = _as_int(payload.get("job_id"))
    if requested_id is not None:
        job = db.session.get(BotJob, requested_id)
        if job is None:
            return _err("Job not found.", "job_not_found", 404)
        if job.status != "pending":
            code = "already_claimed" if job.status in core.BOT_JOB_OPEN_STATUSES else "invalid_transition"
            return _err(f"Job is {job.status}; only pending jobs are claimable.", code, 409)
    else:
        job = (
            BotJob.query.filter(BotJob.status == "pending")
            .order_by(BotJob.created_at.asc(), BotJob.id.asc())
            .first()
        )
        if job is None:
            return _err("No pending job available.", "no_pending_job", 404)

    now = _now()
    lease_seconds = _config_int("FEMIS_JOB_LEASE_SECONDS", DEFAULT_LEASE_SECONDS)

    # 1) atomic CAS (single UPDATE guarded on status — no SELECT-then-UPDATE race)
    won = BotJob.query.filter(BotJob.id == job.id, BotJob.status == "pending").update(
        {
            "status": "claimed",
            "claimed_at": now,
            "claimed_by": claimed_by,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "last_heartbeat_at": now,
            "claim_generation": BotJob.claim_generation + 1,
        },
        synchronize_session=False,
    )
    if won != 1:
        db.session.rollback()
        return _err("Job was claimed by another worker.", "claim_conflict", 409)
    db.session.expire_all()
    job = db.session.get(BotJob, job.id)

    # 2) version check BEFORE snapshot materialization (fail closed — decision L)
    student = db.session.get(Student, job.student_id)
    current = student.updated_at if student is not None else None
    if student is None:
        job.status = "failed"
        job.completed_at = now
        job.failure_category = "validation"
        job.outcome_known = True
        job.lease_expires_at = None
        job.error_message = "Student record missing; cannot materialize snapshot."
        db.session.commit()
        return _err("Student record missing; attempt failed closed.", "student_not_found", 409)

    if current is None or current != job.student_data_version:
        expected = _iso(job.student_data_version)
        observed = _iso(current)
        job.status = "failed"
        job.completed_at = now
        job.failure_category = "validation"  # taxonomy-compatible representation
        job.bot_result_code = "DATA_STALE"  # machine-readable stale marker (no schema change)
        job.outcome_known = True  # no FEMIS work started — outcome is known
        job.lease_expires_at = None
        job.error_message = (
            f"DATA_STALE: expected student version {expected}, current {observed}."
        )
        db.session.commit()
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Student data changed after the job was created; attempt failed closed.",
                    "error_code": "DATA_STALE",
                    "job": _job_dict(job),
                }
            ),
            409,
        )

    # 3) materialize the immutable snapshot from the canonical row (3B.1 key space)
    row = db.session.execute(
        db.text("SELECT * FROM students WHERE id = :id"), {"id": job.student_id}
    ).mappings().first()
    if row is None:  # pragma: no cover - FK-consistent DBs cannot hit this
        db.session.rollback()
        return _err("Student record missing; cannot materialize snapshot.", "student_not_found", 409)

    data = dict(row)
    for meta in ("id", "created_at", "updated_at", "processed"):
        data.pop(meta, None)
    for secret_key in [k for k in data if re.search(r"password|token|secret|credential", k, re.I)]:
        data.pop(secret_key, None)  # defensive: snapshots never carry credentials
    if "transport" in data:
        data.setdefault("transport_facility", data.get("transport"))  # WebFormHandler alias

    snapshot = {
        "student_id": job.student_id,
        "version": _iso(current),
        "materialized_at": _iso(now),
        "data": data,
    }
    job.snapshot_json = json.dumps(snapshot, default=str, ensure_ascii=False)
    job.snapshot_materialized_at = now
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _err("Claim transaction failed; job remains claimable.", "claim_conflict", 409)

    return jsonify({"ok": True, "job": _job_dict(job), "student_snapshot": snapshot})


def _authorize_claimant(job, payload):
    """Fencing checks shared by heartbeat/progress/complete.

    Returns an error response tuple, or None when the caller is the live claimant.
    """
    core = _core()
    now = _now()

    claimed_by = _sanitize(payload.get("claimed_by"), 80)
    if not claimed_by:
        return _err("claimed_by is required.", "validation_error", 422)
    generation = _as_int(payload.get("claim_generation"))
    if generation is None:
        return _err("claim_generation is required.", "validation_error", 422)

    if job.claimed_by != claimed_by or job.claim_generation != generation:
        return _err(
            "Claim superseded by another worker (stale fencing token).",
            "fencing_conflict",
            409,
        )
    if job.status not in core.BOT_JOB_OPEN_STATUSES or job.status == "pending":
        return _err("Job is not active.", "invalid_transition", 409)
    lease = job.lease_expires_at
    if lease is None or lease <= now:
        return _err("Lease has expired.", "lease_expired", 409)
    return None


@bp.route("/api/jobs/<int:job_id>/heartbeat", methods=["POST"])
def heartbeat(job_id):
    guard = _require_bot()
    if guard:
        return guard
    core = _core()
    db, BotJob = core.db, core.BotJob

    job = db.session.get(BotJob, job_id)
    if job is None:
        return _err("Job not found.", "job_not_found", 404)

    payload = _payload()
    denied = _authorize_claimant(job, payload)
    if denied:
        return denied

    now = _now()
    lease_seconds = _config_int("FEMIS_JOB_LEASE_SECONDS", DEFAULT_LEASE_SECONDS)
    heartbeat_seconds = _config_int(
        "FEMIS_JOB_HEARTBEAT_SECONDS", DEFAULT_HEARTBEAT_SECONDS
    )
    job.last_heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    db.session.commit()
    db.session.refresh(job)
    return jsonify(
        {
            "ok": True,
            "job": _job_dict(job),
            "lease_seconds": lease_seconds,
            "heartbeat_seconds": heartbeat_seconds,
        }
    )


@bp.route("/api/jobs/<int:job_id>/progress", methods=["POST"])
def progress(job_id):
    """Structured progress: claimed -> running on first update; tabs + diagnostics."""
    guard = _require_bot()
    if guard:
        return guard
    core = _core()
    db, BotJob = core.db, core.BotJob

    job = db.session.get(BotJob, job_id)
    if job is None:
        return _err("Job not found.", "job_not_found", 404)

    payload = _payload()
    denied = _authorize_claimant(job, payload)
    if denied:
        return denied

    current_tab = payload.get("current_tab")
    if current_tab is not None:
        current_tab = _as_int(current_tab)
        if current_tab is None or not (1 <= current_tab <= 7):
            return _err("current_tab must be 1..7.", "validation_error", 422)

    last_completed = payload.get("last_completed_tab")
    if last_completed is not None:
        last_completed = _as_int(last_completed)
        if last_completed is None or not (0 <= last_completed <= 7):
            return _err("last_completed_tab must be 0..7.", "validation_error", 422)

    current_field = _sanitize(payload.get("current_field"), 200)
    detail = _sanitize(payload.get("detail"), 500)

    now = _now()
    if job.status == "claimed":
        job.status = "running"  # first progress starts the run (state machine)
        if job.started_at is None:
            job.started_at = now
    # status stays 'running' — progress never jumps the lifecycle

    if current_tab is not None:
        job.current_tab = current_tab
    if last_completed is not None:
        job.last_completed_tab = last_completed

    if current_field or detail:
        parts = []
        if current_tab is not None:
            parts.append(f"tab={current_tab}")
        if current_field:
            parts.append(f"field={current_field}")
        if detail:
            parts.append(detail)
        line = "progress: " + " ".join(parts)
        existing = _sanitize(job.error_message, 1000)
        job.error_message = _sanitize(
            f"{existing} || {line}" if existing else line, 1000
        )

    job.last_heartbeat_at = now
    job.lease_expires_at = now + timedelta(
        seconds=_config_int("FEMIS_JOB_LEASE_SECONDS", DEFAULT_LEASE_SECONDS)
    )
    db.session.commit()
    db.session.refresh(job)
    return jsonify({"ok": True, "job": _job_dict(job)})


@bp.route("/api/jobs/<int:job_id>/complete", methods=["POST"])
def complete_job(job_id):
    """Terminal completion: success (Finish+indicator evidence) or structured failure."""
    guard = _require_bot()
    if guard:
        return guard
    core = _core()
    db, BotJob = core.db, core.BotJob

    job = db.session.get(BotJob, job_id)
    if job is None:
        return _err("Job not found.", "job_not_found", 404)

    payload = _payload()

    # Fencing FIRST: a superseded worker must never complete (even terminal jobs).
    claimed_by = _sanitize(payload.get("claimed_by"), 80)
    generation = _as_int(payload.get("claim_generation"))
    if not claimed_by:
        return _err("claimed_by is required.", "validation_error", 422)
    if generation is None:
        return _err("claim_generation is required.", "validation_error", 422)
    if job.claimed_by != claimed_by or job.claim_generation != generation:
        return _err(
            "Claim superseded by another worker (stale fencing token).",
            "fencing_conflict",
            409,
        )

    outcome = payload.get("outcome")
    if outcome not in ("success", "failed"):
        return _err("outcome must be 'success' or 'failed'.", "validation_error", 422)

    # Terminal + same outcome from the live claimant => idempotent ack.
    if job.status in core.BOT_JOB_TERMINAL_STATUSES:
        if job.status == outcome:
            return jsonify({"ok": True, "job": _job_dict(job), "idempotent": True})
        return _err("Job is already terminal with a different outcome.", "invalid_transition", 409)

    if job.status == "pending":
        return _err("Job has not been claimed.", "invalid_transition", 409)

    # Lease must still be valid for an active job.
    now = _now()
    lease = job.lease_expires_at
    if lease is None or lease <= now:
        return _err("Lease has expired.", "lease_expired", 409)

    last_tab = payload.get("last_completed_tab")
    if last_tab is not None:
        last_tab = _as_int(last_tab)
        if last_tab is None or not (0 <= last_tab <= 7):
            return _err("last_completed_tab must be 0..7.", "validation_error", 422)

    if outcome == "success":
        result_code = payload.get("bot_result_code")
        if result_code == "fill_success":
            return _err(
                "Fill-only is never a job success (Finish + indicator required).",
                "fill_only_is_not_success",
                422,
            )
        if result_code != "success":
            return _err(
                "bot_result_code must be 'success' for a successful completion.",
                "validation_error",
                422,
            )
        evidence_ok = (
            payload.get("finish_clicked") is True
            and payload.get("indicator_detected") is True
            and payload.get("outcome_known") is True
        )
        if not evidence_ok:
            return _err(
                "Success requires finish_clicked=true, indicator_detected=true and outcome_known=true.",
                "missing_success_evidence",
                422,
            )
        job.status = "success"
        job.completed_at = now
        job.outcome_known = True
        job.finish_clicked = True
        job.indicator_detected = True
        job.bot_result_code = "success"
        job.failure_category = None
        if last_tab is not None:
            job.last_completed_tab = last_tab
        db.session.commit()
        db.session.refresh(job)
        return jsonify({"ok": True, "job": _job_dict(job)})

    # --- structured failure (validate everything BEFORE mutating the job) ---
    category = payload.get("failure_category")
    if not isinstance(category, str) or category not in core.BOT_JOB_FAILURE_CATEGORIES:
        return _err(
            "failure_category must be one of the approved taxonomy values.",
            "invalid_failure_category",
            422,
        )
    outcome_known = payload.get("outcome_known")
    if not isinstance(outcome_known, bool):
        return _err(
            "outcome_known must be an explicit boolean for failures.",
            "validation_error",
            422,
        )
    failed_tab = payload.get("failed_tab")
    if failed_tab is not None:
        failed_tab = _as_int(failed_tab)
        if failed_tab is None or not (1 <= failed_tab <= 7):
            return _err("failed_tab must be 1..7.", "validation_error", 422)

    job.status = "failed"
    job.completed_at = now
    job.failure_category = category
    job.outcome_known = outcome_known  # preserves known vs uncertain FEMIS outcome
    if failed_tab is not None:
        job.failed_tab = failed_tab

    failed_field = payload.get("failed_field")
    if failed_field is not None:
        job.failed_field = _sanitize(failed_field, 200)

    if last_tab is not None:
        job.last_completed_tab = last_tab

    message = payload.get("error_message")
    if message is not None:
        job.error_message = _sanitize(message, 1000)

    result_code = payload.get("bot_result_code")
    if result_code is not None:
        job.bot_result_code = _sanitize(result_code, 30)

    for flag in ("finish_clicked", "indicator_detected"):
        value = payload.get(flag)
        if isinstance(value, bool):
            setattr(job, flag, value)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        db.session.refresh(job)
        return _err("Completion rejected by schema constraints.", "validation_error", 422)
    db.session.refresh(job)
    return jsonify({"ok": True, "job": _job_dict(job)})
