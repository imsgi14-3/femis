"""Phase 3B.4 API tests: admin-only bot-job endpoints (store/lifecycle only).

Covers: auth matrix (operator session+token / bot machine token, all fail-closed),
create + idempotency, list/get, atomic claim + DATA_STALE, lease + fencing,
progress, success/failure completion evidence, retry-as-new-attempt, cancel,
races (create/claim/claim-next/cancel-claim/complete), and regression guards.

No baseline file is modified. Everything created here is deleted here — cleanup is
scoped to rows created by this run (student_id IN created_students); pre-existing
rows are snapshotted at start and must survive byte-identical (3B.7 Item 1).
"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

# Must be set BEFORE importing app (fail-closed checks read env at request time).
BOT_TOKEN = "p3b4-bot-secret-7f3a9c21"
OP_TOKEN = "p3b4-operator-secret-5e2b1d44"
os.environ["FEMIS_BOT_TOKEN"] = BOT_TOKEN
os.environ["FEMIS_OPERATOR_TOKEN"] = OP_TOKEN

from app import app, db, Student, BotJob  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


DB_PATH = ROOT / "femis-web" / "instance" / "femis.db"
BOT_H = {"X-Bot-Token": BOT_TOKEN}
OP_H = {"X-Operator-Token": OP_TOKEN}

created_students = []
baseline_jobs = []
BASELINE_Q = (
    "SELECT bj.*, s.name AS student_name FROM bot_jobs bj "
    "LEFT JOIN students s ON s.id = bj.student_id ORDER BY bj.id"
)


def raw_conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def sql(query, params=()):
    c = raw_conn()
    try:
        c.execute(query, params)
        c.commit()
        return None
    except sqlite3.Error as e:
        return str(e)
    finally:
        c.close()


def one(query, params=()):
    c = raw_conn()
    try:
        row = c.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        c.close()


def all_rows(query, params=()):
    c = raw_conn()
    try:
        return [dict(r) for r in c.execute(query, params).fetchall()]
    finally:
        c.close()


def iso(dt):
    return dt.isoformat(sep=" ", timespec="microseconds")


def raw_updated(sid):
    row = one("SELECT updated_at FROM students WHERE id=?", (sid,))
    return row["updated_at"] if row else None


def job_row(job_id):
    return one("SELECT * FROM bot_jobs WHERE id=?", (job_id,))


def set_job_cols(job_id, **cols):
    parts = []
    vals = []
    for k, v in cols.items():
        parts.append(f"{k} = ?")
        vals.append(iso(v) if isinstance(v, datetime) else v)
    vals.append(job_id)
    return sql(f"UPDATE bot_jobs SET {', '.join(parts)} WHERE id = ?", vals)


def new_client(role=None, name="P3B4 Test Operator"):
    c = app.test_client()
    if role:
        with c.session_transaction() as s:
            s["role"] = role
            s["user_name"] = name
    return c


def op(role="teacher"):
    return new_client(role)


def bot():
    return new_client()


def _admin_client():
    """Internal test client with an admin session (auth covered by test_rbac)."""
    c = app.test_client()
    with c.session_transaction() as s:
        s["role"] = "admin"
    return c


def create_student(name):
    # complete record: L1 final-submit validates every tab server-side
    from form_payloads import create_full
    r = create_full(_admin_client(), name=name)
    j = r[1]
    sid = j.get("student_id") if j and j.get("ok") else None
    if sid:
        created_students.append(sid)
    return sid


def edit_student(sid, name):
    time.sleep(0.05)
    r = _admin_client().post(
        "/api/save-tab",
        json={"tab": 1, "student_id": sid, "data": {"name": name}},
    )
    j = r.get_json()
    return bool(j and j.get("ok"))


def cap(resp):
    try:
        return resp.status_code, resp.get_json()
    except Exception:
        return resp.status_code, None


def race(fns, timeout=30):
    out = [None] * len(fns)
    barrier = threading.Barrier(len(fns))

    def runner(i, fn):
        try:
            barrier.wait(10)
            out[i] = fn()
        except Exception as e:  # never TypeError downstream; 598 fails all assertions
            out[i] = (598, {"ok": False, "exception": repr(e)})

    ts = [threading.Thread(target=runner, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout)
    return out


def create_payload(sid, **extra):
    p = {"student_id": sid, "student_data_version": raw_updated(sid)}
    p.update(extra)
    return p


try:
    with app.app_context():
        # =================================================================
        # S. baseline — pre-existing rows are never deleted or mutated
        # =================================================================
        baseline_jobs = all_rows(BASELINE_Q)
        active = [r for r in baseline_jobs if r["status"] in ("pending", "claimed", "running")]
        leftovers = [
            r for r in baseline_jobs
            if (r.get("student_name") or "").startswith(("P3B4 ", "P3B5 "))
        ]
        check(
            "S0 baseline recorded; no active foreign jobs and no prior-suite leftovers",
            not active and not leftovers,
            f"baseline={len(baseline_jobs)} active={[r['id'] for r in active]} "
            f"leftovers={[r['id'] for r in leftovers]}",
        )
        if active:
            # Claim-next tests would claim/mutate a foreign active row — refuse to run.
            print("REFUSING TO RUN: pre-existing active bot_jobs would be claimed/mutated.")
            sys.exit(1)

        # All test students up front (SQ is created first => oldest job order).
        SQ = create_student("P3B4 SQ")
        S2 = create_student("P3B4 S2 HAPPY")
        S3 = create_student("P3B4 S3 STALE")
        S4 = create_student("P3B4 S4 FAILURE")
        S6 = create_student("P3B4 S6 CANCEL")
        S7 = create_student("P3B4 S7 CREATE RACE")
        S8 = create_student("P3B4 S8 CLAIM RACE")
        S9 = create_student("P3B4 S9 CANCEL RACE")
        S10 = create_student("P3B4 S10 STALE COMPLETE")
        S11 = create_student("P3B4 S11 UNCERTAIN")
        S12 = create_student("P3B4 S12 FILL FAIL")
        S13 = create_student("P3B4 S13 DOUBLE COMPLETE")
        SFS = create_student("P3B4 SFS FINAL SUBMIT")
        check(
            "S1 test students created",
            all([SQ, S2, S3, S4, S6, S7, S8, S9, S10, S11, S12, S13, SFS]),
            str(created_students),
        )

        op_c = op("teacher")
        stu_c = op("student")
        anon_c = app.test_client()

        # =================================================================
        # A. auth matrix (fail-closed both directions)
        # =================================================================
        r, b = cap(anon_c.post("/api/jobs/claim", json={"claimed_by": "x"}))
        check("A1 bot endpoint without token -> 401", r == 401 and b.get("error_code") == "invalid_bot_token", str(b))
        r, b = cap(anon_c.post("/api/jobs/claim", json={"claimed_by": "x"}, headers={"X-Bot-Token": "wrong"}))
        check("A2 wrong bot token -> 401", r == 401 and b.get("error_code") == "invalid_bot_token", str(b))
        saved = os.environ.pop("FEMIS_BOT_TOKEN")
        try:
            r, b = cap(anon_c.post("/api/jobs/claim", json={"claimed_by": "x"}, headers=BOT_H))
            check("A3 bot token not configured -> 403 fail-closed", r == 403 and b.get("error_code") == "bot_token_not_configured", str(b))
        finally:
            os.environ["FEMIS_BOT_TOKEN"] = saved
        r, b = cap(anon_c.post("/api/jobs", json={"student_id": SQ}, headers=OP_H))
        check("A4 human endpoint no session -> 401", r == 401 and b.get("error_code") == "authentication_required", str(b))
        r, b = cap(stu_c.post("/api/jobs", json={"student_id": SQ}, headers=OP_H))
        check("A5 student session -> 403 forbidden_role", r == 403 and b.get("error_code") == "forbidden_role", str(b))
        r, b = cap(op_c.post("/api/jobs", json={"student_id": SQ}))
        check("A6 teacher without operator token -> 403", r == 403 and b.get("error_code") == "operator_token_invalid", str(b))
        r, b = cap(op_c.post("/api/jobs", json={"student_id": SQ}, headers={"X-Operator-Token": "wrong"}))
        check("A7 teacher wrong operator token -> 403", r == 403 and b.get("error_code") == "operator_token_invalid", str(b))
        saved = os.environ.pop("FEMIS_OPERATOR_TOKEN")
        try:
            r, b = cap(op_c.post("/api/jobs", json={"student_id": SQ}, headers=OP_H))
            check("A8 operator token not configured -> 403 fail-closed", r == 403 and b.get("error_code") == "operator_token_not_configured", str(b))
        finally:
            os.environ["FEMIS_OPERATOR_TOKEN"] = saved
        r, b = cap(anon_c.post("/api/jobs", json={"student_id": SQ, "student_data_version": raw_updated(SQ)}, headers=BOT_H))
        check("A9 bot token does not authenticate human ops", r == 401 and b.get("error_code") == "authentication_required", str(b))
        r, b = cap(op_c.post("/api/jobs/claim", json={"claimed_by": "x"}))
        check("A10 human creds do not authenticate bot ops", r == 401 and b.get("error_code") == "invalid_bot_token", str(b))
        r, b = cap(op_c.get("/api/jobs", headers=OP_H))
        check("A11 operator positive control", r == 200 and b.get("ok") and b.get("total") == len(baseline_jobs), str(b))

        # =================================================================
        # B. create
        # =================================================================
        r, b = cap(op_c.post("/api/jobs", json=create_payload(SQ), headers=OP_H))
        sq_job = b.get("job", {}).get("job_id")
        j = b.get("job", {})
        check(
            "B1 create ok (pending, attempt 1, version stored, no snapshot)",
            r == 200 and b.get("ok") and j.get("status") == "pending"
            and j.get("attempt_number") == 1
            and j.get("student_data_version") == raw_updated(SQ)
            and j.get("has_snapshot") is False
            and j.get("retryable") is False and j.get("data_stale") is False
            and j.get("created_by") == "P3B4 Test Operator",
            json.dumps(b),
        )
        r, b = cap(op_c.post("/api/jobs", json=create_payload(SQ), headers=OP_H))
        check(
            "B2 duplicate create -> 409 open_job_exists + existing_job",
            r == 409 and b.get("error_code") == "open_job_exists"
            and b.get("existing_job", {}).get("job_id") == sq_job,
            str(b),
        )
        r, b = cap(op_c.post("/api/jobs", json={"student_id": SQ, "student_data_version": "2000-01-01 00:00:00"}, headers=OP_H))
        check("B3 wrong version -> 422 version_mismatch", r == 422 and b.get("error_code") == "version_mismatch", str(b))
        r, b = cap(op_c.post("/api/jobs", json={"student_data_version": raw_updated(SQ)}, headers=OP_H))
        check("B4 missing student_id -> 422", r == 422 and b.get("error_code") == "validation_error", str(b))
        r, b = cap(op_c.post("/api/jobs", json=create_payload(999999), headers=OP_H))
        check("B5 unknown student -> 404", r == 404 and b.get("error_code") == "student_not_found", str(b))
        r, b = cap(op_c.post("/api/jobs", json={"student_id": SQ}, headers=OP_H))
        check("B6 missing version -> 422", r == 422 and b.get("error_code") == "validation_error", str(b))
        r, b = cap(op_c.post("/api/jobs", json=create_payload(SQ, mode="fill_only"), headers=OP_H))
        check("B7 mode fill_only -> 400 unsupported_mode", r == 400 and b.get("error_code") == "unsupported_mode", str(b))
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S4, idempotency_key="p3b4-key-1"), headers=OP_H))
        s4_job = b.get("job", {}).get("job_id")
        check("B8 create with idempotency_key ok", r == 200 and b.get("ok") and s4_job is not None, str(b))
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S4, idempotency_key="p3b4-key-1"), headers=OP_H))
        n4 = one("SELECT COUNT(*) AS n FROM bot_jobs WHERE student_id=?", (S4,))["n"]
        check(
            "B9 idempotent replay returns same job, no duplicate row",
            r == 200 and b.get("idempotent") is True
            and b.get("job", {}).get("job_id") == s4_job and n4 == 1,
            f"r={r} rows={n4}",
        )
        j = one("SELECT * FROM bot_jobs WHERE id=?", (s4_job,))
        check(
            "B10 no snapshot at creation; version stored exactly",
            j["snapshot_json"] is None and j["snapshot_materialized_at"] is None
            and j["student_data_version"] == raw_updated(S4),
            str(j and j["student_data_version"]),
        )
        rjs = _admin_client().get(f"/students/{S2}/json").get_json()
        r, b = cap(op_c.post("/api/jobs", json={"student_id": S2, "student_data_version": rjs.get("updated_at")}, headers=OP_H))
        s2_job = b.get("job", {}).get("job_id")
        check("B11 create with RFC-822 version token (portal JSON) ok", r == 200 and b.get("ok"), str(b))
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S3), headers=OP_H))
        s3_job = b.get("job", {}).get("job_id")
        check("B12 create S3 ok", r == 200 and b.get("ok"), str(b))

        # =================================================================
        # C. list / get
        # =================================================================
        r, b = cap(op_c.get("/api/jobs", headers=OP_H))
        c1_text = json.dumps(b) if b else ""
        total = b.get("total") if b else 0
        check("C1 list ok, total >= 4", r == 200 and b.get("ok") and total >= 4 and len(b.get("jobs", [])) == total, f"total={total}")
        r, b = cap(op_c.get(f"/api/jobs?student_id={S2}", headers=OP_H))
        check("C2 filter student_id", r == 200 and all(x["student_id"] == S2 for x in b.get("jobs", [])) and len(b.get("jobs", [])) == 1, json.dumps(b)[:200])
        r, b = cap(op_c.get("/api/jobs?status=pending", headers=OP_H))
        check("C3 filter status", r == 200 and len(b.get("jobs", [])) >= 4 and all(x["status"] == "pending" for x in b.get("jobs", [])), str(len(b.get("jobs", []))))
        r, b = cap(op_c.get("/api/jobs?status=bogus", headers=OP_H))
        check("C4 invalid status filter -> 422", r == 422, str(b))
        r, b = cap(op_c.get("/api/jobs?limit=abc", headers=OP_H))
        check("C5a non-integer limit -> 422", r == 422, str(b))
        r, b = cap(op_c.get("/api/jobs?limit=999", headers=OP_H))
        check("C5b limit out of range -> 422", r == 422, str(b))
        r, b = cap(op_c.get("/api/jobs?order=asc&limit=200", headers=OP_H))
        asc_ids = [x["job_id"] for x in b.get("jobs", [])]
        r, b = cap(op_c.get("/api/jobs?order=desc&limit=200", headers=OP_H))
        desc_ids = [x["job_id"] for x in b.get("jobs", [])]
        check("C6 order asc vs desc", asc_ids and desc_ids and asc_ids[0] == min(asc_ids) and desc_ids[0] == max(desc_ids) and asc_ids != desc_ids, f"asc0={asc_ids and asc_ids[0]} desc0={desc_ids and desc_ids[0]}")
        r, b = cap(op_c.get(f"/api/jobs/{sq_job}", headers=OP_H))
        j = b.get("job", {})
        check(
            "C7 get job: safe fields present",
            r == 200 and j.get("attempt_number") == 1 and j.get("status") == "pending"
            and j.get("retryable") is False and j.get("data_stale") is False
            and j.get("has_snapshot") is False and j.get("lease_active") is False
            and j.get("outcome_known") is None and j.get("prior_attempt_id") is None
            and j.get("claim_generation") == 0,
            json.dumps(j)[:300],
        )
        check("C8 list never includes snapshot_json", "snapshot_json" not in c1_text, "")
        r, b = cap(op_c.get("/api/jobs/999999", headers=OP_H))
        check("C9 get unknown job -> 404", r == 404 and b.get("error_code") == "job_not_found", str(b))
        r, b = cap(op_c.get("/api/jobs?student_id=abc", headers=OP_H))
        check("C10 non-integer student filter -> 422", r == 422, str(b))

        # =================================================================
        # D. claim (CAS + snapshot + DATA_STALE)
        # =================================================================
        oldest = one("SELECT id FROM bot_jobs WHERE status='pending' ORDER BY created_at ASC, id ASC")
        check("D0 oldest pending is SQ's job", oldest and oldest["id"] == sq_job, str(oldest))
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-main"}, headers=BOT_H))
        d1_text = json.dumps(b) if b else ""
        j = b.get("job", {})
        snap = b.get("student_snapshot") or {}
        data = snap.get("data", {})
        check(
            "D1 claim-next: CAS + lease + snapshot envelope",
            r == 200 and b.get("ok") and j.get("job_id") == sq_job
            and j.get("status") == "claimed" and j.get("claimed_by") == "w-main"
            and j.get("claim_generation") == 1 and j.get("lease_expires_at")
            and j.get("last_heartbeat_at") and j.get("has_snapshot") is True
            and j.get("snapshot_materialized_at")
            and set(snap.keys()) == {"student_id", "version", "materialized_at", "data"}
            and snap.get("version") == j.get("student_data_version"),
            json.dumps(b)[:400],
        )
        secret_keys = [k for k in data if re.search(r"password|token|secret|credential", k, re.I)]
        check(
            "D1b snapshot data: portal keys, no metadata, no secrets",
            "name" in data and "id" not in data and "created_at" not in data
            and "updated_at" not in data and "processed" not in data
            and "transport_facility" in data and not secret_keys,
            f"secret_keys={secret_keys} sample={sorted(data.keys())[:8]}",
        )
        r, b = cap(op_c.post("/api/jobs", json=create_payload(SQ), headers=OP_H))
        check("D1c create blocked while job claimed", r == 409 and b.get("error_code") == "open_job_exists", str(b))
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-x", "job_id": sq_job}, headers=BOT_H))
        check("D2 claim already-claimed by id -> 409", r == 409 and b.get("error_code") == "already_claimed", str(b))
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-main", "job_id": s2_job}, headers=BOT_H))
        s2_gen = b.get("job", {}).get("claim_generation")
        s2_snap_time = b.get("job", {}).get("snapshot_materialized_at")
        s2_version = b.get("job", {}).get("student_data_version")
        check("D3 claim specific pending job ok", r == 200 and b.get("ok") and b.get("job", {}).get("status") == "claimed", str(b))
        r, b = cap(bot().post("/api/jobs/claim", json={"job_id": s3_job}, headers=BOT_H))
        check("D4 claim missing claimed_by -> 422", r == 422 and b.get("error_code") == "validation_error", str(b))
        edit_student(S3, "P3B4 S3 STALE EDITED")
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-stale", "job_id": s3_job}, headers=BOT_H))
        s3 = job_row(s3_job)
        check(
            "D5 DATA_STALE: 409 + failed closed (no snapshot)",
            r == 409 and b.get("error_code") == "DATA_STALE"
            and s3["status"] == "failed" and s3["failure_category"] == "validation"
            and s3["bot_result_code"] == "DATA_STALE" and s3["outcome_known"] == 1
            and s3["lease_expires_at"] is None and s3["snapshot_json"] is None
            and s3["completed_at"] is not None
            and str(s3["error_message"]).startswith("DATA_STALE:"),
            json.dumps(b)[:300],
        )
        s3_gen = s3["claim_generation"]
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-stale", "job_id": s3_job}, headers=BOT_H))
        check("D6 claim terminal job -> 409 invalid_transition", r == 409 and b.get("error_code") == "invalid_transition", str(b))
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w", "job_id": 999999}, headers=BOT_H))
        check("D7 claim unknown job -> 404", r == 404 and b.get("error_code") == "job_not_found", str(b))
        edit_student(S2, "P3B4 S2 HAPPY EDITED")
        r, b = cap(op_c.get(f"/api/jobs/{s2_job}", headers=OP_H))
        j = b.get("job", {})
        check(
            "D8 snapshot/version immutable after later student edit",
            r == 200 and j.get("student_data_version") == s2_version
            and j.get("has_snapshot") is True
            and j.get("snapshot_materialized_at") == s2_snap_time,
            str(j.get("student_data_version")),
        )
        check("D9 snapshot_json never serialized outside claim", "snapshot_json" not in (json.dumps(b) if b else ""), "")

        # =================================================================
        # E. heartbeat / lease / fencing
        # =================================================================
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/heartbeat", json={"claimed_by": "w-main", "claim_generation": s2_gen}, headers=BOT_H))
        lease_before = job_row(s2_job)["lease_expires_at"]
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/heartbeat", json={"claimed_by": "w-main", "claim_generation": s2_gen}, headers=BOT_H))
        lease_after = job_row(s2_job)["lease_expires_at"]
        hb = b.get("job", {})
        check(
            "E1 heartbeat ok, extends lease",
            r == 200 and b.get("ok") and hb.get("last_heartbeat_at")
            and lease_after > lease_before
            and b.get("lease_seconds") == 60 and b.get("heartbeat_seconds") == 15,
            f"{lease_before} -> {lease_after}",
        )
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/heartbeat", json={"claimed_by": "w-other", "claim_generation": s2_gen}, headers=BOT_H))
        check("E2 wrong claimant -> 409 fencing_conflict", r == 409 and b.get("error_code") == "fencing_conflict", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/heartbeat", json={"claimed_by": "w-main", "claim_generation": s2_gen + 99}, headers=BOT_H))
        check("E3 wrong generation -> 409 fencing_conflict", r == 409 and b.get("error_code") == "fencing_conflict", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/heartbeat", json={"claimed_by": "w-main"}, headers=BOT_H))
        check("E4 missing claim_generation -> 422", r == 422, str(b))
        r, b = cap(bot().post(f"/api/jobs/{s3_job}/heartbeat", json={"claimed_by": "w-stale", "claim_generation": s3_gen}, headers=BOT_H))
        check("E5 heartbeat terminal job -> 409 invalid_transition", r == 409 and b.get("error_code") == "invalid_transition", str(b))
        set_job_cols(s2_job, lease_expires_at=datetime.utcnow() - timedelta(seconds=5))
        r1, b1 = cap(bot().post(f"/api/jobs/{s2_job}/heartbeat", json={"claimed_by": "w-main", "claim_generation": s2_gen}, headers=BOT_H))
        r2, b2 = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-main", "claim_generation": s2_gen, "current_tab": 2}, headers=BOT_H))
        r3, b3 = cap(bot().post(f"/api/jobs/{s2_job}/complete", json={"claimed_by": "w-main", "claim_generation": s2_gen, "outcome": "success", "bot_result_code": "success", "finish_clicked": True, "indicator_detected": True, "outcome_known": True}, headers=BOT_H))
        check(
            "E6 expired lease blocks heartbeat/progress/complete",
            r1 == 409 and b1.get("error_code") == "lease_expired"
            and r2 == 409 and b2.get("error_code") == "lease_expired"
            and r3 == 409 and b3.get("error_code") == "lease_expired",
            f"{r1},{r2},{r3}",
        )
        set_job_cols(s2_job, lease_expires_at=datetime.utcnow() + timedelta(seconds=60))
        set_job_cols(s2_job, claim_generation=s2_gen + 7)
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/heartbeat", json={"claimed_by": "w-main", "claim_generation": s2_gen}, headers=BOT_H))
        check("E7 superseded generation -> 409", r == 409 and b.get("error_code") == "fencing_conflict", str(b))
        set_job_cols(s2_job, claim_generation=s2_gen)
        r, b = cap(bot().post("/api/jobs/999999/heartbeat", json={"claimed_by": "w", "claim_generation": 1}, headers=BOT_H))
        check("E8 heartbeat unknown job -> 404", r == 404, str(b))

        # =================================================================
        # F. progress
        # =================================================================
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-main", "claim_generation": s2_gen, "current_tab": 3, "last_completed_tab": 2}, headers=BOT_H))
        j = b.get("job", {})
        check(
            "F1 first progress: claimed -> running + started_at + tabs",
            r == 200 and j.get("status") == "running" and j.get("started_at")
            and j.get("current_tab") == 3 and j.get("last_completed_tab") == 2,
            json.dumps(j)[:250],
        )
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-main", "claim_generation": s2_gen, "current_tab": 4, "last_completed_tab": 3}, headers=BOT_H))
        check("F2 progress stays running, tabs update", r == 200 and b.get("job", {}).get("status") == "running" and b.get("job", {}).get("current_tab") == 4, str(b.get("job", {}).get("status")))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-main", "claim_generation": s2_gen, "current_tab": 5, "current_field": "father_name", "detail": "typing value"}, headers=BOT_H))
        err = b.get("job", {}).get("error_message") or ""
        check("F3 progress detail persisted as progress line", r == 200 and "progress:" in err and "field=father_name" in err, err[:150])
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-other", "claim_generation": s2_gen, "current_tab": 5}, headers=BOT_H))
        check("F4 stale claimant progress -> 409 fencing_conflict", r == 409 and b.get("error_code") == "fencing_conflict", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-main", "claim_generation": s2_gen + 5, "current_tab": 5}, headers=BOT_H))
        check("F5 stale generation progress -> 409 fencing_conflict", r == 409 and b.get("error_code") == "fencing_conflict", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-main", "claim_generation": s2_gen, "current_tab": 9}, headers=BOT_H))
        check("F6a current_tab out of range -> 422", r == 422, str(b))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-main", "claim_generation": s2_gen, "last_completed_tab": "x"}, headers=BOT_H))
        check("F6b non-integer last_completed_tab -> 422", r == 422, str(b))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-main", "claim_generation": s2_gen, "current_tab": 6, "status": "success"}, headers=BOT_H))
        check("F7 progress cannot jump lifecycle (status ignored)", r == 200 and b.get("job", {}).get("status") == "running", str(b.get("job", {}).get("status")))

        # =================================================================
        # G. complete success (evidence) + terminal immutability
        # =================================================================
        base = {"claimed_by": "w-main", "claim_generation": s2_gen}
        p = dict(base, outcome="success", bot_result_code="success")
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/complete", json=p, headers=BOT_H))
        check("G1 success without evidence -> 422 + stays running", r == 422 and b.get("error_code") == "missing_success_evidence" and job_row(s2_job)["status"] == "running", str(b))
        p = dict(base, outcome="success", bot_result_code="success", finish_clicked=True)
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/complete", json=p, headers=BOT_H))
        check("G2 success missing indicator/outcome -> 422", r == 422 and b.get("error_code") == "missing_success_evidence", str(b))
        p = dict(base, outcome="success", bot_result_code="fill_success", finish_clicked=True, indicator_detected=True, outcome_known=True)
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/complete", json=p, headers=BOT_H))
        check("G3 fill_success never completes as success -> 422", r == 422 and b.get("error_code") == "fill_only_is_not_success", str(b))
        p = dict(base, outcome="success", bot_result_code="error", finish_clicked=True, indicator_detected=True, outcome_known=True)
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/complete", json=p, headers=BOT_H))
        check("G4 success requires bot_result_code=success -> 422", r == 422 and b.get("error_code") == "validation_error", str(b))
        p = {"claimed_by": "w-main", "outcome": "success", "bot_result_code": "success", "finish_clicked": True, "indicator_detected": True, "outcome_known": True}
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/complete", json=p, headers=BOT_H))
        check("G5 complete missing claim_generation -> 422", r == 422, str(b))
        p = dict(base, outcome="success", bot_result_code="success", finish_clicked=True, indicator_detected=True, outcome_known=True, last_completed_tab=7)
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/complete", json=p, headers=BOT_H))
        j = b.get("job", {})
        check(
            "G6 full evidence -> success with audit fields",
            r == 200 and j.get("status") == "success" and j.get("completed_at")
            and j.get("finish_clicked") is True and j.get("indicator_detected") is True
            and j.get("outcome_known") is True and j.get("failure_category") is None
            and j.get("last_completed_tab") == 7,
            json.dumps(j)[:300],
        )
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/complete", json=p, headers=BOT_H))
        check("G7 duplicate completion is idempotent", r == 200 and b.get("idempotent") is True, str(b))
        set_job_cols(s2_job, claim_generation=99)
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/complete", json=p, headers=BOT_H))
        check("G8 superseded worker cannot complete -> 409 + stays success", r == 409 and b.get("error_code") == "fencing_conflict" and job_row(s2_job)["status"] == "success", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/heartbeat", json={"claimed_by": "w-main", "claim_generation": 99}, headers=BOT_H))
        check("G9 heartbeat on terminal -> 409 invalid_transition", r == 409 and b.get("error_code") == "invalid_transition", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/progress", json={"claimed_by": "w-main", "claim_generation": 99, "current_tab": 7}, headers=BOT_H))
        check("G10 progress on terminal -> 409 invalid_transition", r == 409 and b.get("error_code") == "invalid_transition", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s2_job}/complete", json=dict(base, claim_generation=99, outcome="failed", failure_category="network", outcome_known=True), headers=BOT_H))
        check("G11 different outcome on terminal -> 409 invalid_transition", r == 409 and b.get("error_code") == "invalid_transition", str(b))

        # =================================================================
        # H. complete failure (structured taxonomy)
        # =================================================================
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-fail", "job_id": s4_job}, headers=BOT_H))
        s4_gen = b.get("job", {}).get("claim_generation")
        check("H1 claim S4 job ok", r == 200 and b.get("ok"), str(b))
        r, b = cap(bot().post(f"/api/jobs/{s4_job}/progress", json={"claimed_by": "w-fail", "claim_generation": s4_gen, "current_tab": 1}, headers=BOT_H))
        check("H2 progress starts running", r == 200 and b.get("job", {}).get("status") == "running", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s4_job}/complete", json={"claimed_by": "w-fail", "claim_generation": s4_gen, "outcome": "failed", "failure_category": "bogus", "outcome_known": True}, headers=BOT_H))
        check("H3 invalid failure_category -> 422 + stays running", r == 422 and b.get("error_code") == "invalid_failure_category" and job_row(s4_job)["status"] == "running", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s4_job}/complete", json={"claimed_by": "w-fail", "claim_generation": s4_gen, "outcome": "failed", "failure_category": "network"}, headers=BOT_H))
        check("H4 failure without outcome_known -> 422", r == 422 and b.get("error_code") == "validation_error", str(b))
        r, b = cap(bot().post(f"/api/jobs/{s4_job}/complete", json={"claimed_by": "w-fail", "claim_generation": s4_gen, "outcome": "failed", "failure_category": "network", "outcome_known": True, "failed_tab": 9}, headers=BOT_H))
        check("H5 failed_tab out of range -> 422", r == 422, str(b))
        p = {"claimed_by": "w-fail", "claim_generation": s4_gen, "outcome": "failed", "failure_category": "network", "outcome_known": True, "failed_tab": 4, "failed_field": "email", "last_completed_tab": 3, "error_message": "Network timeout talking to FEMIS", "bot_result_code": "timeout"}
        r, b = cap(bot().post(f"/api/jobs/{s4_job}/complete", json=p, headers=BOT_H))
        j = b.get("job", {})
        check(
            "H6 structured failure stored",
            r == 200 and j.get("status") == "failed" and j.get("failure_category") == "network"
            and j.get("failed_tab") == 4 and j.get("failed_field") == "email"
            and j.get("last_completed_tab") == 3
            and j.get("error_message") == "Network timeout talking to FEMIS"
            and j.get("bot_result_code") == "timeout" and j.get("outcome_known") is True
            and j.get("completed_at"),
            json.dumps(j)[:300],
        )
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S11), headers=OP_H))
        s11_job = b.get("job", {}).get("job_id")
        check("H7a create S11 job", r == 200 and s11_job is not None, str(b))
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-unc", "job_id": s11_job}, headers=BOT_H))
        s11_gen = b.get("job", {}).get("claim_generation")
        r, b = cap(bot().post(f"/api/jobs/{s11_job}/complete", json={"claimed_by": "w-unc", "claim_generation": s11_gen, "outcome": "failed", "failure_category": "unknown", "outcome_known": False, "error_message": "Uncertain whether submission landed"}, headers=BOT_H))
        check(
            "H7 uncertain outcome preserved (outcome_known=false)",
            r == 200 and b.get("job", {}).get("status") == "failed"
            and b.get("job", {}).get("outcome_known") is False
            and job_row(s11_job)["outcome_known"] == 0,
            str(b),
        )
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S10), headers=OP_H))
        s10_job = b.get("job", {}).get("job_id")
        check("H8a create S10 job", r == 200 and s10_job is not None, str(b))
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-stale2", "job_id": s10_job}, headers=BOT_H))
        s10_gen = b.get("job", {}).get("claim_generation")
        bot().post(f"/api/jobs/{s10_job}/progress", json={"claimed_by": "w-stale2", "claim_generation": s10_gen, "current_tab": 2}, headers=BOT_H)
        set_job_cols(s10_job, claim_generation=7)
        r, b = cap(bot().post(f"/api/jobs/{s10_job}/complete", json={"claimed_by": "w-stale2", "claim_generation": s10_gen, "outcome": "failed", "failure_category": "browser", "outcome_known": False}, headers=BOT_H))
        check(
            "H8 superseded worker cannot fail job -> 409 + stays running",
            r == 409 and b.get("error_code") == "fencing_conflict"
            and job_row(s10_job)["status"] == "running",
            str(b),
        )
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S12), headers=OP_H))
        s12_job = b.get("job", {}).get("job_id")
        check("H9a create S12 job", r == 200 and s12_job is not None, str(b))
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-fill", "job_id": s12_job}, headers=BOT_H))
        s12_gen = b.get("job", {}).get("claim_generation")
        r, b = cap(bot().post(f"/api/jobs/{s12_job}/complete", json={"claimed_by": "w-fill", "claim_generation": s12_gen, "outcome": "failed", "failure_category": "femis", "outcome_known": True, "bot_result_code": "fill_success"}, headers=BOT_H))
        check(
            "H9 fill_success allowed as FAILED outcome",
            r == 200 and b.get("job", {}).get("status") == "failed"
            and b.get("job", {}).get("bot_result_code") == "fill_success"
            and b.get("job", {}).get("failure_category") == "femis",
            str(b),
        )

        # =================================================================
        # I. retry = new attempt (explicit, never overwrites history)
        # =================================================================
        r, b = cap(op_c.get(f"/api/jobs/{s4_job}", headers=OP_H))
        prior_before = b.get("job")
        r, b = cap(op_c.post(f"/api/jobs/{s4_job}/retry", json={}, headers=OP_H))
        a2 = b.get("job", {})
        s4a2 = a2.get("job_id")
        check(
            "I1 retry from failed: new attempt row + prior immutable",
            r == 200 and b.get("ok") and a2.get("attempt_number") == 2
            and a2.get("status") == "pending" and a2.get("prior_attempt_id") == s4_job
            and a2.get("retry_requested_at")
            and a2.get("student_data_version") == prior_before.get("student_data_version"),
            json.dumps(a2)[:300],
        )
        r, b = cap(op_c.get(f"/api/jobs/{s4_job}", headers=OP_H))
        check("I1b prior attempt unchanged by retry", b.get("job") == prior_before, "")
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S4), headers=OP_H))
        check("I2 create blocked while new attempt open", r == 409 and b.get("error_code") == "open_job_exists", str(b))
        edit_student(S4, "P3B4 S4 FAILURE EDITED")
        r, b = cap(op_c.post(f"/api/jobs/{s4a2}/cancel", json={}, headers=OP_H))
        check("I3 close attempt 2 (cancel) for retry semantics", r == 200 and b.get("job", {}).get("status") == "cancelled", str(b))
        r, b = cap(op_c.post(f"/api/jobs/{s4a2}/retry", json={"refresh_snapshot": False}, headers=OP_H))
        a3 = b.get("job", {})
        check(
            "I4 retry refresh=false retains old version (stale until refresh)",
            r == 200 and a3.get("attempt_number") == 3
            and a3.get("student_data_version") == prior_before.get("student_data_version")
            and a3.get("student_data_version") != raw_updated(S4),
            f"{a3.get('student_data_version')} vs current {raw_updated(S4)}",
        )
        s4a3 = a3.get("job_id")
        r, b = cap(op_c.post(f"/api/jobs/{s4a3}/cancel", json={}, headers=OP_H))
        check("I5 close attempt 3", r == 200, str(b))
        r, b = cap(op_c.post(f"/api/jobs/{s4a3}/retry", json={"refresh_snapshot": True}, headers=OP_H))
        a4 = b.get("job", {})
        s4a4 = a4.get("job_id")
        check(
            "I6 retry refresh=true takes current version",
            r == 200 and a4.get("attempt_number") == 4
            and a4.get("student_data_version") == raw_updated(S4),
            f"{a4.get('student_data_version')} vs {raw_updated(S4)}",
        )
        r, b = cap(op_c.post(f"/api/jobs/{s2_job}/retry", json={}, headers=OP_H))
        check("I7 retry success -> 409 invalid_transition", r == 409 and b.get("error_code") == "invalid_transition", str(b))
        r, b = cap(op_c.post(f"/api/jobs/{s4a4}/retry", json={}, headers=OP_H))
        check("I8 retry open attempt -> 409 invalid_transition", r == 409 and b.get("error_code") == "invalid_transition", str(b))
        r, b = cap(op_c.post(f"/api/jobs/{sq_job}/retry", json={}, headers=OP_H))
        check("I9 retry claimed attempt -> 409 invalid_transition", r == 409 and b.get("error_code") == "invalid_transition", str(b))
        r, b = cap(op_c.post("/api/jobs/999999/retry", json={}, headers=OP_H))
        check("I10 retry unknown job -> 404", r == 404, str(b))
        r, b = cap(op_c.post(f"/api/jobs/{s4a4}/cancel", json={}, headers=OP_H))
        check("I11 close attempt 4 (keeps queue single-pending for K4)", r == 200 and b.get("job", {}).get("status") == "cancelled", str(b))

        # =================================================================
        # J. cancel (pending only)
        # =================================================================
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S6), headers=OP_H))
        s6_job = b.get("job", {}).get("job_id")
        check("J0 create S6 job", r == 200 and s6_job is not None, str(b))
        r, b = cap(op_c.post(f"/api/jobs/{s6_job}/cancel", json={}, headers=OP_H))
        j = b.get("job", {})
        check(
            "J1 cancel pending -> cancelled + audit fields",
            r == 200 and j.get("status") == "cancelled"
            and j.get("failure_category") == "cancelled_by_operator"
            and j.get("completed_at") and j.get("outcome_known") is True
            and j.get("retryable") is True and j.get("error_message"),
            json.dumps(j)[:300],
        )
        r, b = cap(op_c.post(f"/api/jobs/{s6_job}/cancel", json={}, headers=OP_H))
        check("J2 cancel terminal -> 409 invalid_transition", r == 409 and b.get("error_code") == "invalid_transition", str(b))
        r, b = cap(op_c.post(f"/api/jobs/{sq_job}/cancel", json={}, headers=OP_H))
        check("J3 cancel claimed -> 409 cancel_conflict", r == 409 and b.get("error_code") == "cancel_conflict", str(b))
        r, b = cap(op_c.post("/api/jobs/999999/cancel", json={}, headers=OP_H))
        check("J4 cancel unknown -> 404", r == 404, str(b))
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S9), headers=OP_H))
        s9_job = b.get("job", {}).get("job_id")
        check("J5a create S9 job", r == 200 and s9_job is not None, str(b))

        def do_cancel():
            return cap(op("teacher").post(f"/api/jobs/{s9_job}/cancel", json={}, headers=OP_H))

        def do_claim_s9():
            return cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-race", "job_id": s9_job}, headers=BOT_H))

        out = race([do_cancel, do_claim_s9])
        twoxx = [i for i, r in enumerate(out) if r[0] < 300]
        final = job_row(s9_job)["status"]
        winner = twoxx[0] if len(twoxx) == 1 else -1
        check(
            "J5b cancel-vs-claim race: exactly one winner, consistent final state",
            len(twoxx) == 1
            and ((winner == 0 and final == "cancelled") or (winner == 1 and final == "claimed")),
            f"codes={[r[0] for r in out]} final={final}",
        )

        # =================================================================
        # K. races
        # =================================================================
        def do_create_k1():
            return cap(op("teacher").post("/api/jobs", json=create_payload(S7), headers=OP_H))

        out = race([do_create_k1, do_create_k1])
        codes = sorted(r[0] for r in out)
        loser = next((b for c, b in out if c == 409), None)
        rows7 = all_rows("SELECT * FROM bot_jobs WHERE student_id=?", (S7,))
        check(
            "K1 concurrent create: one 200 + one 409, single open row",
            codes[0] == 200 and codes[1] == 409
            and loser is not None
            and loser.get("error_code") in ("open_job_exists", "create_conflict")
            and len(rows7) == 1 and rows7[0]["status"] == "pending"
            and rows7[0]["attempt_number"] == 1,
            f"codes={codes} rows={len(rows7)} loser={loser}",
        )
        r, b = cap(op_c.post("/api/jobs", json=create_payload(S8), headers=OP_H))
        s8_job = b.get("job", {}).get("job_id")
        check("K2a create S8 job", r == 200 and s8_job is not None, str(b))

        def do_claim_k2_a():
            return cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-a", "job_id": s8_job}, headers=BOT_H))

        def do_claim_k2_b():
            return cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-b", "job_id": s8_job}, headers=BOT_H))

        out = race([do_claim_k2_a, do_claim_k2_b])
        codes = sorted(r[0] for r in out)
        k2_text = json.dumps([r[1] for r in out if r[1]])
        j8 = job_row(s8_job)
        check(
            "K2 double claim: one 200 + one 409 claim_conflict, single CAS win",
            codes[0] == 200 and codes[1] == 409
            and j8["status"] == "claimed" and j8["claim_generation"] == 1
            and j8["claimed_by"] in ("w-a", "w-b"),
            f"codes={codes} gen={j8['claim_generation']}",
        )

        r, b = cap(op_c.post("/api/jobs", json=create_payload(S13), headers=OP_H))
        s13_job = b.get("job", {}).get("job_id")
        r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-dbl", "job_id": s13_job}, headers=BOT_H))
        s13_gen = b.get("job", {}).get("claim_generation")
        bot().post(f"/api/jobs/{s13_job}/progress", json={"claimed_by": "w-dbl", "claim_generation": s13_gen, "current_tab": 7, "last_completed_tab": 6}, headers=BOT_H)

        def complete_success():
            return cap(bot().post(f"/api/jobs/{s13_job}/complete", json={"claimed_by": "w-dbl", "claim_generation": s13_gen, "outcome": "success", "bot_result_code": "success", "finish_clicked": True, "indicator_detected": True, "outcome_known": True}, headers=BOT_H))

        out = race([complete_success, complete_success])
        codes = [r[0] for r in out]
        j13 = job_row(s13_job)
        check(
            "K3 double complete: no 5xx, terminal success reached",
            all(c in (200, 409) for c in codes) and any(c == 200 for c in codes)
            and j13["status"] == "success" and j13["completed_at"] is not None,
            f"codes={codes} status={j13['status']}",
        )

        before_k4 = one("SELECT id FROM bot_jobs WHERE status='pending' ORDER BY created_at ASC, id ASC")

        def do_claim_next():
            return cap(bot().post("/api/jobs/claim", json={"claimed_by": "w-next"}, headers=BOT_H))

        out = race([do_claim_next, do_claim_next])
        codes = sorted(r[0] for r in out)
        win_ids = [r[1].get("job", {}).get("job_id") for r in out if r[0] == 200]
        check(
            "K4 claim-next race: one winner on the single pending job",
            before_k4 is not None and codes[0] == 200 and codes[1] in (404, 409)
            and len(win_ids) == 1 and win_ids[0] == before_k4["id"],
            f"codes={codes} before={before_k4}",
        )

        # =================================================================
        # L. regression guards
        # =================================================================
        n_before = one("SELECT COUNT(*) AS n FROM bot_jobs")["n"]
        r, b = cap(_admin_client().post("/api/final-submit", json={"student_id": SFS, "data": {"digital_device_at_home": "1"}}))
        n_after = one("SELECT COUNT(*) AS n FROM bot_jobs")["n"]
        check(
            "L1 final-submit creates NO job",
            r == 200 and b.get("ok") and n_after == n_before
            and one("SELECT COUNT(*) AS n FROM bot_jobs WHERE student_id=?", (SFS,))["n"] == 0,
            f"{n_before} -> {n_after}",
        )
        r = anon_c.get("/")
        check("L2 / still redirects to login", r.status_code == 302 and "/login" in (r.headers.get("Location") or ""), str(r.status_code))
        r = anon_c.get("/login")
        check("L3 /login still 200", r.status_code == 200, str(r.status_code))
        r = anon_c.get("/form/3")
        check("L4 /form/<id> still requires session", r.status_code == 302 and "/login" in (r.headers.get("Location") or ""), str(r.status_code))
        r, b = cap(anon_c.get("/api/bot/jobs", headers=BOT_H))
        check("L5 legacy /api/bot/jobs remains 404", r == 404, str(r))
        r = anon_c.get(f"/api/jobs/{sq_job}/complete")
        check("L6 complete via GET -> 405", r.status_code == 405, str(r.status_code))
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        check("L7 canonical DB URI", "femis-web" in uri and uri.endswith("femis.db"), str(uri))
        check("L8 stale root instance/ DB untouched (absent)", not (ROOT / "instance" / "femis.db").exists(), str(ROOT / "instance"))
        set_job_cols(s10_job, lease_expires_at=datetime.utcnow() + timedelta(seconds=60))
        r, b = cap(bot().post(f"/api/jobs/{s10_job}/heartbeat", json={"claimed_by": "w-stale2", "claim_generation": 7}, headers=BOT_H))
        texts = [c1_text, d1_text, k2_text, json.dumps(b) if b else ""]
        leak = [t for t in texts if BOT_TOKEN in t or OP_TOKEN in t]
        check("L9 secrets never echoed in responses", r == 200 and not leak, f"hb={r} leaks={len(leak)}")

        # =================================================================
        # M. cleanup (only rows created by this run — scoped by student)
        # =================================================================
        if created_students:
            q = ",".join("?" * len(created_students))
            err = sql(f"DELETE FROM bot_jobs WHERE student_id IN ({q})", tuple(created_students))
        else:
            err = None
        check("M1 test jobs deleted (scoped to this run's students)", err is None, str(err))
        n = one("SELECT COUNT(*) AS n FROM bot_jobs")["n"]
        check(
            "M2 bot_jobs back to baseline (no test rows remain)",
            n == len(baseline_jobs),
            f"rows={n} baseline={len(baseline_jobs)}",
        )
        after_rows = all_rows(BASELINE_Q)
        check(
            "M2b pre-existing bot_jobs rows untouched (byte-identical)",
            after_rows == baseline_jobs,
            f"before={len(baseline_jobs)} after={len(after_rows)}",
        )
        for sid in created_students:
            st = db.session.get(Student, sid)
            if st:
                db.session.delete(st)
        db.session.commit()
        gone = [
            sid
            for sid in created_students
            if db.session.get(Student, sid) is not None
        ]
        check("M3 test students deleted", not gone, str(gone))

finally:
    try:
        c = sqlite3.connect(str(DB_PATH))
        if created_students:
            q = ",".join("?" * len(created_students))
            c.execute(f"DELETE FROM bot_jobs WHERE student_id IN ({q})", created_students)
            c.execute(f"DELETE FROM students WHERE id IN ({q})", created_students)
        c.commit()
        c.close()
    except Exception as e:  # pragma: no cover
        print(f"cleanup error: {e}")

failed = [r for r in results if not r[1]]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
