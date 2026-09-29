"""Phase 3B.5 bot integration tests: bot <-> bot-job API lifecycle.

Covers the Phase 3B.5 brief section 18 items against the REAL Phase 3B.4 API
on a local ephemeral-port Werkzeug server (no Playwright, no live FEMIS):
  - bot auth, claim + snapshot envelope, no_pending/conflict handling
  - snapshot adapter parity with WebFormHandler.read_by_id + no DB re-read
  - heartbeat/lease/fencing on a background thread, abort-on-lost claim
  - progress transitions and failure-path preservation
  - success evidence only (fill-only / Finish-only / indicator-only never success)
  - failure taxonomy mapping, DATA_STALE (never filled), retry-new-attempt,
    superseded worker cannot complete, queue drain + conflict retry
  - FormFiller integration seams (progress callback, abort check, last_submit)

No baseline file is modified. Everything created here is deleted here.
"""
import asyncio
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

BOT_TOKEN = "p3b5-bot-secret-9d4e1f77"
OP_TOKEN = "p3b5-operator-secret-2c8a5b63"
os.environ["FEMIS_BOT_TOKEN"] = BOT_TOKEN
os.environ["FEMIS_OPERATOR_TOKEN"] = OP_TOKEN
os.environ["FEMIS_JOB_HEARTBEAT_SECONDS"] = "0.05"

from werkzeug.serving import make_server  # noqa: E402

from app import app  # noqa: E402

from src.job_api_client import JobApiClient, JobApiClientError  # noqa: E402
from src.job_runner import (  # noqa: E402
    HeartbeatWorker,
    WorkResult,
    _execute_claimed,
    build_complete_payload,
    classify_exception,
    classify_submit_failure,
    outcome_known_from_evidence,
    run_job_loop,
    snapshot_to_student,
)
from src.form_filler import FormFiller  # noqa: E402
from src.data_sources.webform_handler import WebFormHandler  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


DB_PATH = ROOT / "femis-web" / "instance" / "femis.db"
created_students = []


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


def job_row(job_id):
    return one("SELECT * FROM bot_jobs WHERE id=?", (job_id,))


def iso(dt):
    return dt.isoformat(sep=" ", timespec="microseconds")


def op_client():
    c = app.test_client()
    with c.session_transaction() as s:
        s["role"] = "teacher"
        s["user_name"] = "P3B5 Test Operator"
    return c


OP_H = {"X-Operator-Token": OP_TOKEN}


def create_student(name):
    r = app.test_client().post(
        "/api/save-tab",
        json={"tab": 1, "student_id": None, "data": {"name": name}},
    )
    j = r.get_json()
    sid = j.get("student_id") if j and j.get("ok") else None
    if sid:
        created_students.append(sid)
    return sid


def edit_student(sid, name):
    time.sleep(0.05)
    c = app.test_client()
    with c.session_transaction() as s:
        s["role"] = "admin"
    r = c.post(
        "/api/save-tab",
        json={"tab": 1, "student_id": sid, "data": {"name": name}},
    )
    j = r.get_json()
    return bool(j and j.get("ok"))


def create_job(sid, **extra):
    payload = {"student_id": sid}
    row = one("SELECT updated_at FROM students WHERE id=?", (sid,))
    if row and row["updated_at"]:
        payload["student_data_version"] = row["updated_at"]
    payload.update(extra)
    r = op_client().post("/api/jobs", json=payload, headers=OP_H)
    j = r.get_json() or {}
    return r.status_code, j


def cap(resp):
    try:
        return resp.status_code, resp.get_json()
    except Exception:
        return resp.status_code, None


def api(token=BOT_TOKEN, timeout=5.0):
    return JobApiClient(base_url=BASE, token=token, timeout=timeout)


def run(coro):
    return asyncio.run(coro)


SUCCESS_EVIDENCE = {
    "finish_clicked": True,
    "indicator_detected": True,
    "outcome_known": True,
    "errors": [],
    "diagnostics": None,
}
FILL_ONLY_EVIDENCE = {
    "finish_clicked": False,
    "indicator_detected": False,
    "outcome_known": True,
    "errors": [],
    "diagnostics": None,
}


def make_worker(evidence=None, error=None, seen=None, on_progress_seq=None):
    async def worker(student, on_progress, should_abort):
        if seen is not None:
            seen.append(student.get("name"))
        if on_progress_seq:
            for kw in on_progress_seq:
                await on_progress(**kw)
        if should_abort():
            raise RuntimeError("job aborted: claim lost (fencing/lease)")
        return WorkResult(
            submitted=bool(evidence and evidence.get("finish_clicked")
                           and evidence.get("indicator_detected")),
            evidence=evidence,
            error=error,
        )

    return worker


server = None
server_thread = None

try:
    server = make_server("127.0.0.1", 0, app, threaded=True)
    BASE = f"http://127.0.0.1:{server.server_port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    c = api()

    # =======================================================================
    # A. Auth + claim contract
    # =======================================================================
    try:
        JobApiClient(base_url=BASE, token="")
        check("A1 job client fails closed without token", False, "no exception")
    except JobApiClientError:
        check("A1 job client fails closed without token", True)

    r, b = api(token="wrong-token").claim("w-auth")
    check("A2 wrong bot token rejected", r == 401 and b.get("error_code") == "invalid_bot_token",
          f"{r} {b.get('error_code')}")

    r, b = c.claim("w-empty")
    check("A3 claim with empty queue -> no_pending_job",
          r == 404 and b.get("error_code") == "no_pending_job", f"{r} {b.get('error_code')}")

    sid_a = create_student("P3B5 Student A")
    r0, j0 = create_job(sid_a)
    job_a = j0.get("job", {}).get("job_id")
    check("A4 operator created job", r0 == 200 and bool(job_a), f"{r0} {j0.get('error_code')}")

    r, b = c.claim("w-one")
    snap = b.get("student_snapshot") or {}
    check("A5 claim returns job + snapshot envelope",
          r == 200 and b.get("ok") and (b.get("job") or {}).get("claim_generation") == 1
          and snap.get("student_id") == sid_a
          and isinstance(snap.get("data"), dict) and snap.get("data")
          and bool(snap.get("version")) and bool(snap.get("materialized_at")),
          f"{r}")
    claimed_a = b

    r2, b2 = c.claim("w-two", job_id=job_a)
    check("A6 second claimant -> already_claimed",
          r2 == 409 and b2.get("error_code") == "already_claimed", f"{r2}")

    # =======================================================================
    # B. Snapshot adapter: parity, immutability, no DB re-read
    # =======================================================================
    data_snap = snapshot_to_student(snap)
    read_row = WebFormHandler().read_by_id(sid_a)
    parity = read_row is not None and (
        set(data_snap) == set(read_row) - {"updated_at", "processed"}
    )
    check("B1 snapshot parity with WebFormHandler.read_by_id", parity,
          f"snapshot-only={sorted(set(data_snap) - set(read_row or {}))} "
          f"read-only={sorted(set(read_row or {}) - set(data_snap))}" if not parity else "")
    check("B2 transport_facility alias present when transport set",
          ("transport" not in data_snap) or ("transport_facility" in data_snap))

    copy_before = dict(data_snap)
    edit_student(sid_a, "P3B5 Student A Renamed")
    again = snapshot_to_student(snap)
    check("B3 mid-run student edit does not change adapter output",
          again == copy_before and data_snap.get("name") == "P3B5 Student A")

    try:
        snapshot_to_student({"data": {}})
        check("B4 empty snapshot rejected", False, "no exception")
    except ValueError:
        check("B4 empty snapshot rejected", True)

    orig_read_by_id = WebFormHandler.read_by_id
    orig_read_all = WebFormHandler.read_all

    def _boom(self, *a, **k):
        raise AssertionError("job mode must not read the students table")

    WebFormHandler.read_by_id = _boom
    WebFormHandler.read_all = _boom
    try:
        sid_b5 = create_student("P3B5 Student B5")
        create_job(sid_b5)
        seen_b = []

        async def b_worker(student, on_progress, should_abort):
            seen_b.append(student.get("name"))
            return WorkResult(submitted=True, evidence=SUCCESS_EVIDENCE)

        reason_b, _ = run(run_job_loop(api(), "w-noread", b_worker, claim_pause=0.05))
        job_b_row = one("SELECT * FROM bot_jobs WHERE student_id=? ORDER BY id DESC", (sid_b5,))
        check("B5 full cycle without any students-table read",
              reason_b == "idle" and job_b_row["status"] == "success"
              and seen_b == ["P3B5 Student B5"],
              f"reason={reason_b} status={job_b_row['status']}")
    finally:
        WebFormHandler.read_by_id = orig_read_by_id
        WebFormHandler.read_all = orig_read_all

    # =======================================================================
    # C. Heartbeat: lease extension, fencing, lease expiry
    # =======================================================================
    sid_c = create_student("P3B5 Student C")
    _, jc = create_job(sid_c)
    job_c = jc["job"]["job_id"]
    rc, bc = c.claim("w-hb", job_id=job_c)
    check("C1 claim for heartbeat test", rc == 200, f"{rc}")

    before = job_row(job_c)
    hb = HeartbeatWorker(api(), job_c, "w-hb", bc["job"]["claim_generation"], interval=0.05)
    hb.start()
    time.sleep(0.3)
    after = job_row(job_c)
    hb.stop()
    hb.join(timeout=2)
    check("C2 heartbeat extends lease/last_heartbeat",
          after["last_heartbeat_at"] != before["last_heartbeat_at"]
          and after["lease_expires_at"] != before["lease_expires_at"]
          and hb.lost_reason is None,
          f"lost={hb.lost_reason}")

    hb_bad = HeartbeatWorker(api(), job_c, "w-hb", 999, interval=0.05)
    hb_bad.start()
    deadline = time.time() + 2
    while hb_bad.lost_reason is None and time.time() < deadline:
        time.sleep(0.02)
    hb_bad.stop()
    hb_bad.join(timeout=2)
    check("C3 stale generation heartbeat -> fencing_conflict + abort",
          hb_bad.lost_reason == "fencing_conflict" and hb_bad.should_abort(),
          f"lost={hb_bad.lost_reason}")

    sid_c2 = create_student("P3B5 Student C2")
    _, jc2 = create_job(sid_c2)
    job_c2 = jc2["job"]["job_id"]
    rc2, bc2 = c.claim("w-hb2", job_id=job_c2)
    sql("UPDATE bot_jobs SET lease_expires_at=? WHERE id=?",
        (iso(datetime.utcnow()), job_c2))
    hb_exp = HeartbeatWorker(api(), job_c2, "w-hb2", bc2["job"]["claim_generation"], interval=0.05)
    hb_exp.start()
    deadline = time.time() + 2
    while hb_exp.lost_reason is None and time.time() < deadline:
        time.sleep(0.02)
    hb_exp.stop()
    hb_exp.join(timeout=2)
    check("C4 expired lease -> heartbeat reports lease_expired",
          hb_exp.lost_reason == "lease_expired", f"lost={hb_exp.lost_reason}")

    # =======================================================================
    # D. Progress: state transition + fencing + failure preservation
    # =======================================================================
    sid_d = create_student("P3B5 Student D")
    _, jd = create_job(sid_d)
    job_d = jd["job"]["job_id"]
    rd, bd = c.claim("w-prog", job_id=job_d)
    gen_d = bd["job"]["claim_generation"]

    rp, bp = c.progress(job_d, "w-prog", gen_d, current_tab=1, detail="filling")
    row_d = job_row(job_d)
    check("D1 first progress moves claimed -> running",
          rp == 200 and row_d["status"] == "running" and row_d["started_at"] is not None,
          f"{rp} {row_d['status']}")

    rp2, bp2 = c.progress(job_d, "w-prog", gen_d, current_tab=3, last_completed_tab=2,
                           current_field="mother_name", detail="saved")
    row_d = job_row(job_d)
    check("D2 progress stores tabs/field detail",
          rp2 == 200 and row_d["current_tab"] == 3 and row_d["last_completed_tab"] == 2
          and "progress:" in (row_d["error_message"] or ""),
          f"{rp2}")

    rp3, bp3 = c.progress(job_d, "w-stale", gen_d, current_tab=4)
    check("D3 stale generation progress -> fencing_conflict",
          rp3 == 409 and bp3.get("error_code") == "fencing_conflict", f"{rp3}")

    rcomp, bcomp = c.complete(job_d, "w-prog", gen_d, {
        "outcome": "failed",
        "failure_category": "validation",
        "outcome_known": True,
        "bot_result_code": "submit_failed",
        "error_message": "Validation errors blocked submission: Name is required",
        "failed_tab": 3,
        "failed_field": "name",
        "last_completed_tab": 2,
        "finish_clicked": False,
        "indicator_detected": False,
    })
    row_d = job_row(job_d)
    check("D4 failed completion preserves progress fields",
          rcomp == 200 and row_d["status"] == "failed"
          and row_d["current_tab"] == 3 and row_d["last_completed_tab"] == 2
          and row_d["failed_tab"] == 3 and row_d["failed_field"] == "name"
          and row_d["outcome_known"] == 1
          and row_d["failure_category"] == "validation",
          f"{rcomp}")

    # =======================================================================
    # E. run_job_loop evidence matrix (success only with full evidence)
    # =======================================================================
    sid_e1 = create_student("P3B5 Student E1")
    create_job(sid_e1)
    seen_e1 = []
    recs_e1 = []
    reason_e1, _ = run(run_job_loop(api(), "w-loop",
                                     make_worker(evidence=SUCCESS_EVIDENCE, seen=seen_e1),
                                     on_result=recs_e1.append, claim_pause=0.05))
    job_e1 = one("SELECT * FROM bot_jobs WHERE student_id=? ORDER BY id DESC", (sid_e1,))
    check("E1 success cycle: full evidence -> status success",
          reason_e1 == "idle" and job_e1["status"] == "success"
          and job_e1["finish_clicked"] == 1 and job_e1["indicator_detected"] == 1
          and job_e1["outcome_known"] == 1 and job_e1["bot_result_code"] == "success"
          and job_e1["failure_category"] is None
          and recs_e1 and recs_e1[0]["status"] == "success"
          and recs_e1[0]["complete_ok"] is True,
          f"reason={reason_e1} status={job_e1['status']}")

    sid_e2 = create_student("P3B5 Student E2")
    create_job(sid_e2)
    recs_e2 = []
    run(run_job_loop(api(), "w-loop", make_worker(evidence=FILL_ONLY_EVIDENCE),
                     on_result=recs_e2.append, claim_pause=0.05))
    job_e2 = one("SELECT * FROM bot_jobs WHERE student_id=? ORDER BY id DESC", (sid_e2,))
    check("E2 fill-only is failed/not success",
          job_e2["status"] == "failed" and job_e2["outcome_known"] == 1
          and job_e2["failure_category"] == "femis"
          and job_e2["finish_clicked"] == 0 and job_e2["bot_result_code"] == "submit_failed"
          and recs_e2[0]["status"] == "submit_failed",
          f"{job_e2['status']} {job_e2['failure_category']}")

    sid_e3 = create_student("P3B5 Student E3")
    create_job(sid_e3)
    ev_e3 = {"finish_clicked": True, "indicator_detected": False, "outcome_known": False,
             "errors": ["Name is required"], "diagnostics": {"errorTexts": []}}
    recs_e3 = []
    run(run_job_loop(api(), "w-loop", make_worker(evidence=ev_e3),
                     on_result=recs_e3.append, claim_pause=0.05))
    job_e3 = one("SELECT * FROM bot_jobs WHERE student_id=? ORDER BY id DESC", (sid_e3,))
    check("E3 Finish-only: failed, outcome uncertain (outcome_known=false)",
          job_e3["status"] == "failed" and job_e3["outcome_known"] == 0
          and job_e3["finish_clicked"] == 1 and job_e3["indicator_detected"] == 0
          and job_e3["failure_category"] == "validation",
          f"known={job_e3['outcome_known']} cat={job_e3['failure_category']}")

    sid_e4 = create_student("P3B5 Student E4")
    create_job(sid_e4)
    ev_e4 = {"finish_clicked": False, "indicator_detected": True, "outcome_known": True,
             "errors": [], "diagnostics": None}
    run(run_job_loop(api(), "w-loop", make_worker(evidence=ev_e4), claim_pause=0.05))
    job_e4 = one("SELECT * FROM bot_jobs WHERE student_id=? ORDER BY id DESC", (sid_e4,))
    check("E4 indicator-only without Finish: failed",
          job_e4["status"] == "failed" and job_e4["outcome_known"] == 1
          and job_e4["failure_category"] == "femis",
          f"{job_e4['status']} {job_e4['failure_category']}")

    sid_e5 = create_student("P3B5 Student E5")
    create_job(sid_e5)
    run(run_job_loop(api(), "w-loop",
                     make_worker(evidence=SUCCESS_EVIDENCE,
                                 error=RuntimeError("screenshot failed after success")),
                     claim_pause=0.05))
    job_e5 = one("SELECT * FROM bot_jobs WHERE student_id=? ORDER BY id DESC", (sid_e5,))
    check("E5 late exception with success evidence still completes success",
          job_e5["status"] == "success" and job_e5["bot_result_code"] == "success",
          f"{job_e5['status']}")

    sid_e6 = create_student("P3B5 Student E6")
    create_job(sid_e6)
    run(run_job_loop(api(), "w-loop",
                     make_worker(evidence=None, error=ValueError("student CNIC missing")),
                     claim_pause=0.05))
    job_e6 = one("SELECT * FROM bot_jobs WHERE student_id=? ORDER BY id DESC", (sid_e6,))
    check("E6 fill-stage exception -> failed/validation, outcome known",
          job_e6["status"] == "failed" and job_e6["failure_category"] == "validation"
          and job_e6["outcome_known"] == 1 and job_e6["finish_clicked"] == 0,
          f"{job_e6['failure_category']}")

    # =======================================================================
    # F. DATA_STALE never filled; loop continues to next job
    # =======================================================================
    sid_f1 = create_student("P3B5 Student F1")
    create_job(sid_f1)
    edit_student(sid_f1, "P3B5 Student F1 Edited")
    sid_f2 = create_student("P3B5 Student F2")
    create_job(sid_f2)
    seen_f = []
    recs_f = []
    run(run_job_loop(api(), "w-loop", make_worker(evidence=SUCCESS_EVIDENCE, seen=seen_f),
                     on_result=recs_f.append, claim_pause=0.05))
    job_f1 = one("SELECT * FROM bot_jobs WHERE student_id=? ORDER BY id DESC", (sid_f1,))
    job_f2 = one("SELECT * FROM bot_jobs WHERE student_id=? ORDER BY id DESC", (sid_f2,))
    stale_recs = [r for r in recs_f if "DATA_STALE" in (r.get("reason") or "")]
    check("F1 DATA_STALE: job failed closed, never filled",
          job_f1["status"] == "failed" and job_f1["bot_result_code"] == "DATA_STALE"
          and job_f1["outcome_known"] == 1 and job_f1["failure_category"] == "validation"
          and "F1" not in "".join(seen_f) and bool(stale_recs),
          f"{job_f1['status']} seen={seen_f}")
    check("F2 loop continues past DATA_STALE to next job",
          job_f2["status"] == "success" and seen_f == ["P3B5 Student F2"],
          f"{job_f2['status']} seen={seen_f}")

    # =======================================================================
    # G. Retry = new attempt; history preserved
    # =======================================================================
    sid_g = create_student("P3B5 Student G")
    _, jg = create_job(sid_g)
    job_g1 = jg["job"]["job_id"]
    run(run_job_loop(api(), "w-loop", make_worker(evidence=FILL_ONLY_EVIDENCE),
                     claim_pause=0.05))
    g1 = job_row(job_g1)
    r_retry, b_retry = cap(op_client().post(
        f"/api/jobs/{job_g1}/retry", json={"refresh_snapshot": True}, headers=OP_H))
    g2 = b_retry.get("job") or {}
    run(run_job_loop(api(), "w-loop", make_worker(evidence=SUCCESS_EVIDENCE), claim_pause=0.05))
    g2_row = job_row(g2.get("job_id")) if g2.get("job_id") else None
    check("G1 operator retry -> new attempt succeeds",
          r_retry == 200 and g2_row is not None and g2_row["status"] == "success"
          and g2_row["attempt_number"] == 2 and g1["status"] == "failed"
          and g2_row["id"] != job_g1,
          f"retry={r_retry} attempt={g2_row and g2_row['attempt_number']}")

    # =======================================================================
    # H. Superseded worker cannot complete; failure still completes
    # =======================================================================
    sid_h = create_student("P3B5 Student H")
    _, jh = create_job(sid_h)
    job_h = jh["job"]["job_id"]
    rh, bh = c.claim("w-old", job_id=job_h)
    gen_h = bh["job"]["claim_generation"]
    r_h, b_h = c.complete(job_h, "w-old", gen_h + 7, {
        "outcome": "failed", "failure_category": "unknown", "outcome_known": True,
        "bot_result_code": "error", "error_message": "stale claimant",
    })
    check("H1 superseded generation cannot complete",
          r_h == 409 and b_h.get("error_code") == "fencing_conflict"
          and job_row(job_h)["status"] == "claimed",
          f"{r_h} {b_h.get('error_code')}")

    async def h_worker(student, on_progress, should_abort):
        sql("UPDATE bot_jobs SET claim_generation = claim_generation + 1 WHERE id=?",
            (job_h,))
        await on_progress(tab=1, stage="filling")
        for _ in range(20):
            if should_abort():
                break
            await asyncio.sleep(0.05)
        raise RuntimeError("job aborted: claim lost (fencing/lease)")

    rec_h = run(_execute_claimed(api(), bh, "w-old", h_worker, HeartbeatWorker))
    check("H2 mid-run supersede aborts run; complete rejected; no new attempt",
          rec_h["complete_ok"] is False
          and rec_h["lost_reason"] in ("fencing_conflict", "invalid_transition", "lease_expired")
          and job_row(job_h)["status"] == "claimed"
          and rec_h["status"] == "error",
          f"lost={rec_h['lost_reason']} complete_ok={rec_h['complete_ok']}")

    # =======================================================================
    # I. FormFiller seams (no browser)
    # =======================================================================
    filler = FormFiller()

    async def seams():
        out = {}

        async def noop_cb(**kw):
            out["cb"] = kw

        await filler._notify_progress(tab=2, stage="filling")
        out["noop"] = True

        filler.progress_callback = noop_cb
        await filler._notify_progress(tab=2, stage="saved", field="name", last_completed=2)
        out["kw"] = dict(out.get("cb") or {})

        filler.abort_check = lambda: True
        try:
            await filler._notify_progress(tab=3, stage="filling")
            out["abort_raised"] = False
        except RuntimeError:
            out["abort_raised"] = True
        filler.abort_check = None

        async def raising_cb(**kw):
            raise KeyError("boom")

        filler.progress_callback = raising_cb
        try:
            await filler._notify_progress(tab=1, stage="filling")
            out["cb_exc_propagated"] = False
        except KeyError:
            out["cb_exc_propagated"] = True
        filler.progress_callback = None
        return out

    seams_out = run(seams())
    check("I1 progress seam no-op by default", seams_out.get("noop") is True)
    check("I2 progress callback receives kwargs",
          seams_out.get("kw", {}).get("tab") == 2
          and seams_out.get("kw", {}).get("last_completed") == 2
          and seams_out.get("kw", {}).get("field") == "name",
          str(seams_out.get("kw")))
    check("I3 abort_check stops the run (RuntimeError)", seams_out.get("abort_raised") is True)
    check("I4 callback exceptions propagate", seams_out.get("cb_exc_propagated") is True)

    run(filler._fill_field(None, "mother_name",
                           {"source_field": "mother_name", "required": False}, {}))
    check("I5 _last_attempted_field recorded for failure evidence",
          filler._last_attempted_field == "mother_name")

    check("I6 submit evidence reset semantics (dict rule)",
          outcome_known_from_evidence(False, False) is True
          and outcome_known_from_evidence(False, True) is True
          and outcome_known_from_evidence(True, False) is False
          and outcome_known_from_evidence(True, True) is True)

    p_fillonly = build_complete_payload(WorkResult(submitted=True, evidence=FILL_ONLY_EVIDENCE))
    p_finonly = build_complete_payload(WorkResult(
        submitted=False,
        evidence={"finish_clicked": True, "indicator_detected": False,
                  "outcome_known": False, "errors": [], "diagnostics": None}))
    check("I7 fill-only payload is never a success",
          p_fillonly["outcome"] == "failed" and p_fillonly["bot_result_code"] == "submit_failed"
          and p_fillonly["outcome_known"] is True
          and p_finonly["outcome"] == "failed" and p_finonly["outcome_known"] is False,
          f"{p_fillonly['outcome']}/{p_finonly['outcome']}")

    # =======================================================================
    # J. Failure taxonomy mapping units
    # =======================================================================
    check("J1 exception classification",
          classify_exception(asyncio.TimeoutError()) == "timeout"
          and classify_exception(ConnectionError("connection reset")) == "network"
          and classify_exception(ValueError("bad field mapping for tab_2")) == "field_mapping"
          and classify_exception(ValueError("Name is required")) == "validation"
          and classify_exception(RuntimeError("captcha solver failed")) == "captcha"
          and classify_exception(RuntimeError("session expired, please log in")) == "auth_portal"
          and classify_exception(RuntimeError("locator not found")) == "unknown",
          str({k: classify_exception(v) for k, v in {
              "t": asyncio.TimeoutError(), "n": ConnectionError("connection reset"),
              "f": ValueError("bad field mapping for tab_2"),
          }.items()}))

    cat_v, msg_v = classify_submit_failure(
        {"finish_clicked": False, "errors": ["Class is required"], "diagnostics": None})
    cat_n, msg_n = classify_submit_failure(
        {"finish_clicked": True, "indicator_detected": False, "errors": [],
         "diagnostics": {"errorTexts": ["network error: failed to fetch"]}})
    cat_d, msg_d = classify_submit_failure(
        {"finish_clicked": True, "indicator_detected": False, "errors": [],
         "diagnostics": {"errorTexts": []}})
    check("J2 submit failure classification",
          cat_v == "validation" and cat_n == "network" and cat_d == "femis",
          f"{cat_v}/{cat_n}/{cat_d}")

    cat_dup, msg_dup = classify_submit_failure(
        {"finish_clicked": False, "indicator_detected": False,
         "errors": ["B-Form has already been taken"], "diagnostics": None})
    cat_mk, msg_mk = classify_submit_failure(
        {"finish_clicked": False, "indicator_detected": False,
         "duplicate_conflict": {"tab": 3,
                                "errors": ["Admission number has already been taken"]},
         "errors": [], "diagnostics": None})
    check(
        "J2b duplicate conflict -> validation + stable marker prefix",
        cat_dup == "validation" and cat_mk == "validation"
        and msg_dup.startswith("Duplicate record conflict")
        and msg_mk.startswith("Duplicate record conflict (tab 3)")
        and "already been taken" in msg_mk,
        f"{cat_dup}:{msg_dup} | {cat_mk}:{msg_mk}",
    )
    p_dup = build_complete_payload(WorkResult(evidence={
        "finish_clicked": False, "indicator_detected": False,
        "duplicate_conflict": {"tab": 2,
                               "errors": ["B-Form has already been taken"]},
        "errors": [], "diagnostics": None}))
    check(
        "J2c conflict marker survives into the complete payload",
        p_dup["outcome"] == "failed"
        and p_dup["failure_category"] == "validation"
        and "duplicate record conflict" in (p_dup.get("error_message") or "").lower(),
        str({k: p_dup.get(k) for k in ("outcome", "failure_category", "error_message")}),
    )

    p_big = build_complete_payload(WorkResult(evidence={
        "finish_clicked": False, "indicator_detected": False, "outcome_known": True,
        "errors": ["x" * 500, "y" * 500, "z" * 500], "diagnostics": None}),
        current_tab=9, failed_field="f" * 400)
    check("J3 payload bounds: message<=1000, code<=30, tab range enforced",
          len(p_big["error_message"]) <= 1000
          and len(p_big["bot_result_code"]) <= 30
          and "failed_tab" not in p_big
          and p_big["last_completed_tab"] == 0,
          f"len={len(p_big['error_message'])} keys={sorted(p_big)}")

    p_lost = build_complete_payload(WorkResult(), lost_reason="api_unreachable")
    p_lease = build_complete_payload(WorkResult(), lost_reason="lease_expired")
    check("J4 lost-claim reason maps to category",
          p_lost["failure_category"] == "network"
          and p_lease["failure_category"] == "timeout"
          and "[api_unreachable]" in p_lost["error_message"],
          f"{p_lost['failure_category']}/{p_lease['failure_category']}")

    # =======================================================================
    # K. Filler -> runner -> API progress chain (real FormFiller, no browser)
    # =======================================================================
    sid_k = create_student("P3B5 Student K")
    _, jk = create_job(sid_k)
    job_k = jk["job"]["job_id"]
    rk, bk = c.claim("w-chain", job_id=job_k)
    filler_k = FormFiller()

    async def k_worker(student, on_progress, should_abort):
        filler_k.progress_callback = on_progress
        filler_k.abort_check = should_abort
        filler_k.last_submit = None
        try:
            await filler_k._notify_progress(tab=1, stage="filling")
            filler_k._last_attempted_field = "name"
            await filler_k._notify_progress(tab=1, stage="saved", field="name", last_completed=1)
            await filler_k._notify_progress(tab=7, stage="final_save", last_completed=7)
            await filler_k._notify_progress(tab=7, stage="submitting")
            await filler_k._notify_progress(tab=7, stage="verifying")
            filler_k.last_submit = dict(SUCCESS_EVIDENCE)
            return WorkResult(submitted=True, evidence=filler_k.last_submit)
        finally:
            filler_k.progress_callback = None
            filler_k.abort_check = None

    rec_k = run(_execute_claimed(api(), bk, "w-chain", k_worker, HeartbeatWorker))
    row_k = job_row(job_k)
    check("K1 filler progress chain lands in API job row",
          row_k["status"] == "success" and row_k["started_at"] is not None
          and row_k["current_tab"] == 7 and row_k["last_completed_tab"] == 7
          and "progress:" in (row_k["error_message"] or "")
          and rec_k["complete_ok"] is True,
          f"status={row_k['status']} tab={row_k['current_tab']}")

    # =======================================================================
    # L. Loop exit behaviors (fake client units)
    # =======================================================================
    class FakeClient:
        def __init__(self, claim_script):
            self.script = list(claim_script)

        def claim(self, claimed_by, job_id=None):
            return self.script.pop(0)

        def heartbeat(self, *a, **k):
            return 200, {"ok": True, "lease_seconds": 60}

        def progress(self, *a, **k):
            return 200, {"ok": True}

        def complete(self, *a, **k):
            return 200, {"ok": True}

    async def l_loop(client, pause=0.0):
        return await run_job_loop(client, "w-fake", make_worker(), claim_pause=pause)

    reason_l1, _ = run(l_loop(FakeClient([
        (409, {"ok": False, "error_code": "claim_conflict"}),
        (404, {"ok": False, "error_code": "no_pending_job"}),
    ])))
    check("L1 claim conflict retries then drains cleanly", reason_l1 == "idle", reason_l1)

    reason_l2, detail_l2 = run(l_loop(FakeClient([
        (401, {"ok": False, "error_code": "invalid_bot_token"}),
    ])))
    check("L2 auth failure stops the loop with error",
          reason_l2 == "error" and detail_l2.get("error_code") == "invalid_bot_token",
          str(detail_l2.get("error_code")))

    # =======================================================================
    # M. Heartbeat failure/expiry semantics (unit, no server)
    # =======================================================================
    class DeadClient:
        def __init__(self, script=None):
            self.script = list(script or [])

        def heartbeat(self, *a, **k):
            if self.script:
                return self.script.pop(0)
            return 0, {"ok": False, "error_code": "api_unreachable"}

    def unit_hb(streak_limit=3, deadline_offset=60):
        return HeartbeatWorker(DeadClient(), 99, "w-unit", 1, interval=0.01,
                               error_streak_limit=streak_limit,
                               lease_deadline=time.time() + deadline_offset)

    hb_u = unit_hb()
    hb_u._note_result(0, {"ok": False, "error_code": "api_unreachable"})
    hb_u._note_result(500, {"ok": False})
    check("M1 transient failures accumulate streak without loss",
          hb_u.lost_reason is None and hb_u.error_streak == 2,
          f"streak={hb_u.error_streak} lost={hb_u.lost_reason}")
    hb_u._note_result(500, {"ok": False})
    check("M2 third consecutive failure -> api_unreachable + should_abort",
          hb_u.lost_reason == "api_unreachable" and hb_u.should_abort(),
          f"lost={hb_u.lost_reason}")

    hb_r = unit_hb()
    hb_r._note_result(0, {"ok": False})
    hb_r._note_result(500, {"ok": False})
    hb_r._note_result(200, {"ok": True, "lease_seconds": 45})
    check("M3 success resets streak and extends local lease deadline",
          hb_r.error_streak == 0 and hb_r.lost_reason is None
          and hb_r.lease_deadline > time.time() + 40,
          f"streak={hb_r.error_streak}")

    hb_a = unit_hb()
    hb_a._note_result(401, {"ok": False, "error_code": "invalid_bot_token"})
    check("M4 auth rejection lost immediately (no streak)", hb_a.lost_reason == "auth_rejected",
          f"lost={hb_a.lost_reason}")

    hb_n = unit_hb()
    hb_n._note_result(404, {"ok": False, "error_code": "job_not_found"})
    check("M5 job_not_found lost immediately", hb_n.lost_reason == "job_not_found",
          f"lost={hb_n.lost_reason}")

    hb_l = unit_hb(streak_limit=99, deadline_offset=-10)
    hb_l._note_result(500, {"ok": False})
    check("M6 local lease deadline fallback -> lease_expired",
          hb_l.lost_reason == "lease_expired", f"lost={hb_l.lost_reason}")

    hb_p = unit_hb()
    for _ in range(3):
        hb_p.note_api_error()
    check("M7 progress-path error streak loses claim",
          hb_p.lost_reason == "api_unreachable", f"lost={hb_p.lost_reason}")

    hb_t = unit_hb()
    hb_t.start()
    time.sleep(0.15)
    hb_t.stop()
    hb_t.join(timeout=2)
    check("M8 thread against dead client -> api_unreachable",
          hb_t.lost_reason == "api_unreachable", f"lost={hb_t.lost_reason}")

    hb_s = HeartbeatWorker(DeadClient(), 99, "w-unit", 1, interval=0.05,
                           lease_deadline=time.time() + 60)
    hb_s.start()
    hb_s.stop()
    hb_s.join(timeout=2)
    check("M9 clean stop does not lose claim",
          hb_s.lost_reason is None and not hb_s.is_alive(),
          f"lost={hb_s.lost_reason}")

    abort_err = RuntimeError("job aborted: claim lost (fencing/lease)")
    p_auth = build_complete_payload(WorkResult(error=abort_err), lost_reason="auth_rejected")
    p_fence = build_complete_payload(WorkResult(error=abort_err), lost_reason="fencing_conflict")
    p_lease2 = build_complete_payload(WorkResult(error=abort_err), lost_reason="lease_expired")
    check("M10 lost-reason overlays + intentional claim_lost/unknown mapping",
          p_auth["failure_category"] == "auth_portal"
          and p_fence["failure_category"] == "unknown"
          and p_fence["bot_result_code"] == "claim_lost"
          and p_fence["outcome_known"] is True
          and "[fencing_conflict]" in p_fence["error_message"]
          and p_lease2["failure_category"] == "timeout",
          f"{p_auth['failure_category']}/{p_fence['failure_category']}/"
          f"{p_fence['bot_result_code']}/{p_lease2['failure_category']}")

except Exception as exc:
    check("SUITE crashed", False, f"{type(exc).__name__}: {exc}")
    import traceback
    traceback.print_exc()
finally:
    try:
        if server is not None:
            server.shutdown()
        if server_thread is not None:
            server_thread.join(timeout=3)
    except Exception:
        pass
    for sid in list(created_students):
        sql("DELETE FROM bot_jobs WHERE student_id=?", (sid,))
        sql("DELETE FROM students WHERE id=?", (sid,))
    failed = [r for r in results if not r[1]]
    total = len(results)
    passed = total - len(failed)
    print(f"\n{'='*60}\nRESULT: {passed}/{total} checks passed")
    for name, _, detail in failed:
        print(f"  FAILED: {name} — {detail}")
    print(f"{'='*60}")
    sys.exit(1 if failed else 0)
