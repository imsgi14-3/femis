"""Admin Bot Management tests: dashboard job proxies, pause gate, stale reset.

Covers: RBAC on every /api/admin/bot/* route, list/create/retry/cancel parity
with the operator API (shared svc_* service layer), queue pause blocking all
claims while heartbeat keeps working for running jobs, stale-claim requeue
with fencing intact, and the run_job_loop queue_paused -> idle branch.

No baseline file is modified. Everything created here is deleted here: jobs
and students are scoped to this run, the app_settings pause row is restored
byte-identical, and pre-existing bot_jobs rows must survive byte-identical.
"""
import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

# Must be set BEFORE importing app (fail-closed checks read env at request time).
BOT_TOKEN = "botmgmt-bot-secret-3d91c7aa"
OP_TOKEN = "botmgmt-operator-secret-8b42fe15"
os.environ["FEMIS_BOT_TOKEN"] = BOT_TOKEN
os.environ["FEMIS_OPERATOR_TOKEN"] = OP_TOKEN

from app import app, db, Student, BotJob, AppSetting  # noqa: E402
from src.job_runner import run_job_loop  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


DB_PATH = ROOT / "femis-web" / "instance" / "femis.db"
BOT_H = {"X-Bot-Token": BOT_TOKEN}
OP_H = {"X-Operator-Token": OP_TOKEN}

created_students = []
baseline_jobs = []
baseline_settings = []
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


def client(role=None, name="BotMgmt Admin"):
    c = app.test_client()
    if role:
        with c.session_transaction() as s:
            s["role"] = role
            s["user_name"] = name
    return c


def admin():
    return client("admin")


def teacher():
    return client("teacher", "BotMgmt Teacher")


def student_user():
    return client("student", "BotMgmt Student")


def bot():
    return app.test_client()


def cap(resp):
    try:
        return resp.status_code, resp.get_json()
    except Exception:
        return resp.status_code, None


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


def hit(c, method, path, body):
    if method == "GET":
        return cap(c.get(path))
    return cap(c.post(path, json=body or {}))


ADMIN_ROUTES = [
    ("GET", "/api/admin/bot/jobs", None),
    ("POST", "/api/admin/bot/jobs", {"student_id": 1}),
    ("POST", "/api/admin/bot/jobs/1/retry", {}),
    ("POST", "/api/admin/bot/jobs/1/cancel", {}),
    ("POST", "/api/admin/bot/pause", {}),
    ("POST", "/api/admin/bot/resume", {}),
    ("POST", "/api/admin/bot/reset-stale", {}),
]


try:
    baseline_jobs = all_rows(BASELINE_Q)
    baseline_settings = all_rows("SELECT * FROM app_settings ORDER BY key")

    # Never start (or be left) paused for other suites — restored at cleanup.
    cap(admin().post("/api/admin/bot/resume"))

    # =================================================================
    # A. RBAC on every admin route
    # =================================================================
    anon_codes = [hit(app.test_client(), m, p, b)[0] for m, p, b in ADMIN_ROUTES]
    check(
        "A1 anon gets 401 on every /api/admin/bot route",
        all(c == 401 for c in anon_codes),
        str(anon_codes),
    )
    teacher_codes = [hit(teacher(), m, p, b)[0] for m, p, b in ADMIN_ROUTES]
    check(
        "A2 teacher gets 403 on every /api/admin/bot route",
        all(c == 403 for c in teacher_codes),
        str(teacher_codes),
    )
    student_codes = [hit(student_user(), m, p, b)[0] for m, p, b in ADMIN_ROUTES]
    check(
        "A3 student gets 403 on every /api/admin/bot route",
        all(c == 403 for c in student_codes),
        str(student_codes),
    )

    r, b = cap(admin().get("/api/admin/bot/jobs"))
    check(
        "A4 admin list -> 200 with jobs/total/paused",
        r == 200 and b.get("ok") and isinstance(b.get("jobs"), list)
        and isinstance(b.get("total"), int) and isinstance(b.get("paused"), bool),
        f"r={r} keys={sorted(b) if b else None}",
    )
    r1, b1 = cap(admin().post("/api/admin/bot/jobs/9999999/retry", json={}))
    r2, b2 = cap(admin().post("/api/admin/bot/jobs/9999999/cancel", json={}))
    check(
        "A5 admin retry/cancel unknown job -> 404 job_not_found",
        r1 == 404 and b1.get("error_code") == "job_not_found"
        and r2 == 404 and b2.get("error_code") == "job_not_found",
        f"retry={r1}/{b1 and b1.get('error_code')} cancel={r2}/{b2 and b2.get('error_code')}",
    )

    # =================================================================
    # B. admin list parity with operator GET /api/jobs (shared svc_list)
    # =================================================================
    r_adm, b_adm = cap(admin().get("/api/admin/bot/jobs"))
    r_op, b_op = cap(teacher().get("/api/jobs", headers=OP_H))
    check(
        "B1 operator GET /api/jobs still 200 after service refactor",
        r_op == 200 and b_op.get("ok"),
        f"r={r_op}",
    )
    check(
        "B2 admin list total == operator list total",
        r_adm == 200 and b_adm.get("total") == b_op.get("total"),
        f"admin={b_adm and b_adm.get('total')} op={b_op and b_op.get('total')}",
    )
    adm0 = dict(b_adm["jobs"][0]) if b_adm.get("jobs") else {}
    adm0.pop("student_name", None)
    op0 = b_op["jobs"][0] if b_op.get("jobs") else {}
    check(
        "B3 job payload byte-identical across both APIs",
        bool(b_adm.get("jobs")) and bool(b_op.get("jobs")) and adm0 == op0,
        f"admin_keys={len(adm0)} op_keys={len(op0)}",
    )
    check(
        "B4 admin list enriches student_name",
        bool(b_adm.get("jobs")) and all("student_name" in j for j in b_adm["jobs"]),
        "",
    )

    # =================================================================
    # C. admin create (server-stamped version) parity with svc_create
    # =================================================================
    sid1 = create_student("Bot Mgmt One")
    r, b = cap(admin().post("/api/admin/bot/jobs", json={"student_id": sid1}))
    job1 = b.get("job", {}).get("job_id") if b else None
    raw = job_row(job1) if job1 else None
    stu_ver = one("SELECT updated_at FROM students WHERE id=?", (sid1,))
    check(
        "C1 admin create -> pending attempt 1, version stamped server-side",
        r == 200 and b.get("ok") and b["job"]["status"] == "pending"
        and b["job"]["attempt_number"] == 1 and raw is not None
        and raw["student_data_version"] == (stu_ver or {}).get("updated_at"),
        f"r={r} job={job1} ver={raw and raw['student_data_version']}",
    )
    check(
        "C2 job stamped with the admin session identity",
        raw is not None and raw["created_by"] == "BotMgmt Admin",
        str(raw and raw["created_by"]),
    )

    r2, b2 = cap(admin().post("/api/admin/bot/jobs", json={"student_id": sid1}))
    check(
        "C3 duplicate create -> 409 open_job_exists with existing_job",
        r2 == 409 and b2.get("error_code") == "open_job_exists"
        and (b2.get("existing_job") or {}).get("job_id") == job1,
        f"r={r2} code={b2 and b2.get('error_code')}",
    )

    r3, b3 = cap(admin().post(
        "/api/admin/bot/jobs",
        json={"student_id": sid1, "student_data_version": "2000-01-01 00:00:00.000000"},
    ))
    check(
        "C4 explicit stale version -> 422 version_mismatch",
        r3 == 422 and b3.get("error_code") == "version_mismatch",
        f"r={r3} code={b3 and b3.get('error_code')}",
    )

    r4, b4 = cap(admin().post("/api/admin/bot/jobs", json={"student_id": 9999999}))
    check(
        "C5 unknown student -> 404 student_not_found",
        r4 == 404 and b4.get("error_code") == "student_not_found",
        f"r={r4}",
    )
    r5, b5 = cap(admin().post("/api/admin/bot/jobs", json={}))
    check(
        "C6 missing student_id -> 422 validation_error",
        r5 == 422 and b5.get("error_code") == "validation_error",
        f"r={r5}",
    )

    # =================================================================
    # D. admin cancel parity (svc_cancel CAS)
    # =================================================================
    r, b = cap(admin().post(f"/api/admin/bot/jobs/{job1}/cancel", json={}))
    raw = job_row(job1)
    check(
        "D1 admin cancel pending -> cancelled (CAS)",
        r == 200 and b.get("job", {}).get("status") == "cancelled"
        and raw["status"] == "cancelled"
        and raw["failure_category"] == "cancelled_by_operator",
        f"r={r} status={raw and raw['status']}",
    )
    r2, b2 = cap(admin().post(f"/api/admin/bot/jobs/{job1}/cancel", json={}))
    check(
        "D2 second cancel -> 409 invalid_transition",
        r2 == 409 and b2.get("error_code") == "invalid_transition",
        f"r={r2} code={b2 and b2.get('error_code')}",
    )

    # =================================================================
    # E. admin retry parity (svc_retry new attempt)
    # =================================================================
    r, b = cap(admin().post(
        f"/api/admin/bot/jobs/{job1}/retry", json={"refresh_snapshot": True}
    ))
    job2 = b.get("job", {}).get("job_id") if b else None
    check(
        "E1 retry cancelled -> attempt 2, prior_attempt_id, refresh flag",
        r == 200 and b.get("job", {}).get("attempt_number") == 2
        and b.get("job", {}).get("prior_attempt_id") == job1
        and b.get("refresh_snapshot") is True and job2 is not None,
        f"r={r} job2={job2} attempt={b and b.get('job', {}).get('attempt_number')}",
    )
    stu_ver = one("SELECT updated_at FROM students WHERE id=?", (sid1,))
    raw2 = job_row(job2)
    check(
        "E2 retry refresh_snapshot re-stamps current student version",
        raw2 is not None
        and raw2["student_data_version"] == (stu_ver or {}).get("updated_at"),
        f"job={raw2 and raw2['student_data_version']} student={stu_ver}",
    )
    r3, b3 = cap(admin().post(f"/api/admin/bot/jobs/{job2}/retry", json={}))
    check(
        "E3 retry of a pending attempt -> 409 invalid_transition",
        r3 == 409 and b3.get("error_code") == "invalid_transition",
        f"r={r3} code={b3 and b3.get('error_code')}",
    )

    # =================================================================
    # F. queue pause gate (claim 409 queue_paused; heartbeat unaffected)
    # =================================================================
    r, b = cap(admin().post("/api/admin/bot/pause"))
    check(
        "F1 pause -> ok/paused true + app_settings row persisted",
        r == 200 and b.get("paused") is True
        and (one("SELECT value FROM app_settings WHERE key='bot_queue'")
             or {}).get("value") == "paused",
        f"r={r}",
    )
    r, b = cap(admin().get("/api/admin/bot/jobs"))
    check("F2 list reflects paused=true", r == 200 and b.get("paused") is True,
          str(b and b.get("paused")))

    sid2 = create_student("Bot Mgmt Two")
    r, b = cap(admin().post("/api/admin/bot/jobs", json={"student_id": sid2}))
    job3 = b.get("job", {}).get("job_id") if b else None
    check(
        "F3 create still works while paused (pause gates claims only)",
        r == 200 and b.get("job", {}).get("status") == "pending" and job3 is not None,
        f"r={r} job3={job3}",
    )

    r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "bm-worker"},
                          headers=BOT_H))
    check(
        "F4 claim-next while paused -> 409 queue_paused, job2 still pending",
        r == 409 and b.get("error_code") == "queue_paused"
        and job_row(job2)["status"] == "pending",
        f"r={r} code={b and b.get('error_code')} job2={job_row(job2)['status']}",
    )
    r, b = cap(bot().post("/api/jobs/claim",
                          json={"claimed_by": "bm-worker", "job_id": job3},
                          headers=BOT_H))
    check(
        "F5 explicit claim while paused -> 409 queue_paused, job3 still pending",
        r == 409 and b.get("error_code") == "queue_paused"
        and job_row(job3)["status"] == "pending",
        f"r={r} code={b and b.get('error_code')}",
    )

    r, b = cap(admin().post("/api/admin/bot/resume"))
    check(
        "F6 resume -> ok/paused false, row back to running",
        r == 200 and b.get("paused") is False
        and (one("SELECT value FROM app_settings WHERE key='bot_queue'")
             or {}).get("value") == "running",
        f"r={r}",
    )
    r, b = cap(bot().post("/api/jobs/claim", json={"claimed_by": "bm-worker"},
                          headers=BOT_H))
    check(
        "F7 claim after resume wins the oldest pending job (job2)",
        r == 200 and b.get("job", {}).get("job_id") == job2
        and job_row(job2)["status"] == "claimed",
        f"r={r} claimed={b and b.get('job', {}).get('job_id')} expected={job2}",
    )

    cap(admin().post("/api/admin/bot/pause"))
    gen = job_row(job2)["claim_generation"]
    r, b = cap(bot().post(f"/api/jobs/{job2}/heartbeat",
                          json={"claimed_by": "bm-worker", "claim_generation": gen},
                          headers=BOT_H))
    check(
        "F8 heartbeat still works while paused (running jobs finish)",
        r == 200 and b.get("ok") is True,
        f"r={r}",
    )
    cap(admin().post("/api/admin/bot/resume"))
    check(
        "F9 queue left unpaused after pause block",
        (one("SELECT value FROM app_settings WHERE key='bot_queue'")
         or {}).get("value") == "running",
        "",
    )

    # =================================================================
    # G. stale reset (expired lease -> pending, fencing intact)
    # =================================================================
    set_job_cols(job2, lease_expires_at=datetime.utcnow() - timedelta(seconds=5))
    r, b = cap(bot().post("/api/jobs/claim",
                          json={"claimed_by": "bm-worker", "job_id": job3},
                          headers=BOT_H))
    check(
        "G1 job3 claimed with an ACTIVE lease",
        r == 200 and job_row(job3)["status"] == "claimed"
        and job_row(job3)["lease_expires_at"] is not None
        and job_row(job3)["lease_expires_at"] > iso(datetime.utcnow()),
        f"r={r} lease={job_row(job3)['lease_expires_at']}",
    )

    r, b = cap(admin().post("/api/admin/bot/reset-stale", json={}))
    raw2, raw3 = job_row(job2), job_row(job3)
    check(
        "G2 reset-stale requeues exactly the expired-lease job2",
        r == 200 and b.get("job_ids") == [job2]
        and raw2["status"] == "pending" and raw2["claimed_by"] is None
        and raw2["lease_expires_at"] is None,
        f"r={r} ids={b and b.get('job_ids')} status={raw2['status']}",
    )
    check(
        "G3 active-lease job3 untouched by reset-stale",
        raw3["status"] == "claimed" and raw3["claimed_by"] == "bm-worker",
        f"status={raw3['status']} by={raw3['claimed_by']}",
    )
    check(
        "G4 requeue note recorded on error_message",
        "Requeued by admin" in (raw2["error_message"] or ""),
        str(raw2["error_message"]),
    )
    r, b = cap(bot().post(f"/api/jobs/{job2}/heartbeat",
                          json={"claimed_by": "bm-worker", "claim_generation": 0},
                          headers=BOT_H))
    check(
        "G5 zombie worker fenced after reset (409)",
        r == 409 and b.get("error_code") in ("fencing_conflict", "invalid_transition"),
        f"r={r} code={b and b.get('error_code')}",
    )

    r, b = cap(bot().post(
        f"/api/jobs/{job3}/progress",
        json={"claimed_by": "bm-worker",
              "claim_generation": job_row(job3)["claim_generation"],
              "current_tab": 1},
        headers=BOT_H,
    ))
    set_job_cols(job3, lease_expires_at=datetime.utcnow() - timedelta(seconds=5))
    r, b = cap(admin().post("/api/admin/bot/reset-stale", json={}))
    check(
        "G6 RUNNING job with expired lease also requeued",
        r == 200 and job3 in (b.get("job_ids") or [])
        and job_row(job3)["status"] == "pending",
        f"r={r} ids={b and b.get('job_ids')} status={job_row(job3)['status']}",
    )

    # =================================================================
    # H. run_job_loop treats queue_paused as a clean idle exit
    # =================================================================
    class _PausedClient:
        def claim(self, claimed_by, job_id=None):
            return 409, {
                "ok": False,
                "error": "Job queue is paused by an administrator.",
                "error_code": "queue_paused",
            }

    reason, detail = asyncio.run(
        run_job_loop(_PausedClient(), "bm-loop-worker", None)
    )
    check(
        "H1 run_job_loop exits 'idle' on queue_paused (worker never called)",
        reason == "idle" and detail.get("error_code") == "queue_paused",
        f"reason={reason} detail={detail}",
    )

    # =================================================================
    # I. cleanup (only rows created by this run — scoped by student)
    # =================================================================
    if created_students:
        q = ",".join("?" * len(created_students))
        err = sql(f"DELETE FROM bot_jobs WHERE student_id IN ({q})",
                  tuple(created_students))
    else:
        err = None
    check("I1 test jobs deleted (scoped to this run's students)", err is None, str(err))
    n = one("SELECT COUNT(*) AS n FROM bot_jobs")["n"]
    check(
        "I2 bot_jobs back to baseline (no test rows remain)",
        n == len(baseline_jobs),
        f"rows={n} baseline={len(baseline_jobs)}",
    )
    after_rows = all_rows(BASELINE_Q)
    check(
        "I3 pre-existing bot_jobs rows untouched (byte-identical)",
        after_rows == baseline_jobs,
        f"before={len(baseline_jobs)} after={len(after_rows)}",
    )

    # Restore app_settings exactly as found (pause row included).
    sql("DELETE FROM app_settings")
    for row in baseline_settings:
        sql(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (row["key"], row["value"], row["updated_at"]),
        )
    after_settings = all_rows("SELECT * FROM app_settings ORDER BY key")
    check(
        "I4 app_settings restored byte-identical (queue unpaused for others)",
        after_settings == baseline_settings
        and not any(s["key"] == "bot_queue" and s["value"] == "paused"
                    for s in after_settings),
        f"before={baseline_settings} after={after_settings}",
    )

    with app.app_context():
        for sid in created_students:
            st = db.session.get(Student, sid)
            if st:
                db.session.delete(st)
        db.session.commit()
        gone = [sid for sid in created_students
                if db.session.get(Student, sid) is not None]
    check("I5 test students deleted", not gone, str(gone))

finally:
    try:
        c = sqlite3.connect(str(DB_PATH))
        if created_students:
            q = ",".join("?" * len(created_students))
            c.execute(f"DELETE FROM bot_jobs WHERE student_id IN ({q})", created_students)
            c.execute(f"DELETE FROM students WHERE id IN ({q})", created_students)
        c.execute("DELETE FROM app_settings WHERE key = 'bot_queue'")
        for row in baseline_settings:
            if row["key"] == "bot_queue":
                c.execute(
                    "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
                    (row["key"], row["value"], row["updated_at"]),
                )
        c.commit()
        c.close()
    except Exception as e:  # pragma: no cover
        print(f"cleanup error: {e}")

passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
