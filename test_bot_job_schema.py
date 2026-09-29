"""Phase 3B.3 schema tests: students.updated_at + bot_jobs constraints (schema only).

Isolation contract (3B.8): bot_jobs rows are snapshotted before any insert; only rows
created by this run are mutated or cleaned up; pre-existing rows must survive
byte-identical. See test_bot_job_api.py for the same principle.
"""
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import app, db, Student, BotJob, BOT_JOB_STATUSES, BOT_JOB_FAILURE_CATEGORIES  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


DB_PATH = ROOT / "femis-web" / "instance" / "femis.db"

# Isolation state (3B.8): pre-existing rows snapshotted before any insert; created_job_ids
# records exactly the rows THIS run inserts, so mutations and cleanup touch only our rows.
baseline_jobs = []
created_job_ids = []


def all_jobs():
    c = raw_conn()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM bot_jobs ORDER BY id").fetchall()]
    finally:
        c.close()


def ours_where(prefix=""):
    """SQL predicate + params restricting a statement to rows created by this run."""
    if created_job_ids:
        ph = ",".join("?" * len(created_job_ids))
        return f" AND {prefix}id IN ({ph})", tuple(created_job_ids)
    return " AND 0=1", ()


def raw_conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def insert_raw(sql, params=()):
    c = raw_conn()
    try:
        cur = c.execute(sql, params)
        c.commit()
        created_job_ids.append(cur.lastrowid)
        return None
    except sqlite3.IntegrityError as e:
        return str(e)
    finally:
        c.close()


def delete_raw(table, where, params=()):
    c = raw_conn()
    c.execute(f"DELETE FROM {table} WHERE {where}", params)
    c.commit()
    c.close()


with app.app_context():
    created_ids = []
    job_ids = []

    # Isolation (3B.8): snapshot pre-existing bot_jobs before touching the table.
    baseline_jobs = all_jobs()
    try:

        # =====================================================================
        # A. students.updated_at — structure + backfill
        # =====================================================================
        cols = {c.name for c in Student.__table__.columns}
        check("A1 student model has updated_at", "updated_at" in cols)

        c = raw_conn()
        info = {r[1] for r in c.execute("PRAGMA table_info(students)")}
        check("A2 students table has updated_at column", "updated_at" in info)
        nulls = c.execute(
            "SELECT COUNT(*) FROM students WHERE updated_at IS NULL"
        ).fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        c.close()
        check("A3 all existing students backfilled (no NULL updated_at)", nulls == 0,
              f"nulls={nulls} total={total}")

        # =====================================================================
        # B. updated_at — set on create, bumped on modify (API path)
        # =====================================================================
        client = app.test_client()
        with client.session_transaction() as s:
            s["role"] = "admin"
        # complete record: B3 (tab-3 save) and B4 (final-submit) both need
        # stored tabs covered by the server mandatory twin
        from form_payloads import create_full
        resp_status, body = create_full(client, name="P3B3 SCHEMA TEST")
        sid = body.get("student_id") if body else None
        check("B1 create student via API", resp_status == 200 and body.get("ok") and sid is not None,
              json.dumps(body))
        if sid:
            created_ids.append(sid)

        if sid:
            j = client.get(f"/students/{sid}/json").get_json()
            check("B2 new student has updated_at set", bool(j.get("updated_at")), str(j.get("updated_at")))

            # read raw microsecond-precision values (API JSON serializes to 1s precision)
            def raw_updated(student_id):
                rc = raw_conn()
                v = rc.execute("SELECT updated_at FROM students WHERE id=?", (student_id,)).fetchone()
                rc.close()
                return v["updated_at"] if v else None

            first_updated = raw_updated(sid)
            check("B2b raw updated_at has microseconds", bool(first_updated and "." in str(first_updated)),
                  str(first_updated))

            time.sleep(0.05)
            resp = client.post(
                "/api/save-tab",
                json={"tab": 3, "student_id": sid, "data": {"name": "P3B3 SCHEMA TEST MODIFIED"}},
            )
            second_updated = raw_updated(sid)
            check("B3 modify bumps updated_at",
                  bool(resp.get_json().get("ok")) and second_updated != first_updated,
                  f"{first_updated} -> {second_updated}")

            time.sleep(0.05)
            resp = client.post(
                "/api/final-submit",
                json={"student_id": sid, "data": {"digital_device_at_home": "1"}},
            )
            third_updated = raw_updated(sid)
            check("B4 final-submit bumps updated_at",
                  bool(resp.get_json().get("ok")) and third_updated != second_updated,
                  f"{second_updated} -> {third_updated}")

            # updated_at must never predate created_at
            rc = raw_conn()
            crow = rc.execute("SELECT created_at, updated_at FROM students WHERE id=?", (sid,)).fetchone()
            rc.close()
            check("B5 updated_at >= created_at",
                  str(crow["updated_at"]) >= str(crow["created_at"]),
                  f"created={crow['created_at']} updated={crow['updated_at']}")

        # =====================================================================
        # C. bot_jobs — structure
        # =====================================================================
        model_cols = {c.name for c in BotJob.__table__.columns}
        c = raw_conn()
        tbl_cols = {r[1] for r in c.execute("PRAGMA table_info(bot_jobs)")}
        c.close()
        expected = {
            "id", "student_id", "attempt_number", "status",
            "created_at", "claimed_at", "started_at", "completed_at",
            "student_data_version", "snapshot_json", "snapshot_materialized_at",
            "claimed_by", "lease_expires_at", "last_heartbeat_at", "claim_generation",
            "current_tab", "last_completed_tab",
            "failure_category", "failed_tab", "failed_field", "error_message",
            "outcome_known", "bot_result_code",
            "finish_clicked", "indicator_detected",
            "prior_attempt_id", "created_by", "requested_at", "retry_requested_at",
            "idempotency_key",
        }
        check("C1 bot_jobs model/table columns complete",
              expected <= model_cols and expected <= tbl_cols,
              f"missing_model={sorted(expected - model_cols)} missing_table={sorted(expected - tbl_cols)}")

        # =====================================================================
        # D. attempt history — one student, many attempts
        # =====================================================================
        sid6 = 6  # may carry real job history — offset this run's attempts past it
        c = raw_conn()
        base6 = c.execute(
            "SELECT COALESCE(MAX(attempt_number), 0) FROM bot_jobs WHERE student_id=?",
            (sid6,),
        ).fetchone()[0]
        c.close()
        for k in (1, 2, 3):
            err = insert_raw(
                "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
                " failure_category, outcome_known) VALUES (?, ?, 'failed', ?, 0, 'browser', 0)",
                (sid6, base6 + k, "2026-09-26 12:00:00"),
            )
            check(f"D{k} failed attempt {base6 + k} insertable", err is None, str(err))
        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
            " outcome_known, finish_clicked, indicator_detected, prior_attempt_id)"
            " VALUES (?, ?, 'success', ?, 0, 1, 1, 1, "
            "(SELECT id FROM bot_jobs WHERE student_id=? AND attempt_number=?))",
            (sid6, base6 + 4, "2026-09-26 12:05:00", sid6, base6 + 3),
        )
        check(f"D4 success attempt {base6 + 4} with prior_attempt_id insertable", err is None, str(err))

        _ours_sql, _ours_p = ours_where()
        _ours_j_sql, _ours_p = ours_where("j.")
        c = raw_conn()
        hist = c.execute(
            "SELECT attempt_number, status FROM bot_jobs WHERE student_id=?" + _ours_sql
            + " ORDER BY attempt_number",
            (sid6,) + _ours_p,
        ).fetchall()
        linked = c.execute(
            "SELECT COUNT(*) FROM bot_jobs j JOIN bot_jobs p ON j.prior_attempt_id = p.id"
            " WHERE j.student_id=? AND p.attempt_number=?" + _ours_j_sql,
            (sid6, base6 + 3) + _ours_p,
        ).fetchone()[0]
        c.close()
        check("D5 history rows coexist (4 attempts)", len(hist) == 4,
              str([(r[0], r[1]) for r in hist]))
        check("D6 prior_attempt_id links retry to prior attempt", linked == 1, f"linked={linked}")

        # duplicate attempt_number rejected
        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
            " VALUES (?, ?, 'cancelled', ?, 0)",
            (sid6, base6 + 2, "2026-09-26 12:10:00"),
        )
        check("D7 duplicate attempt rejected", err is not None, str(err))

        # =====================================================================
        # E. one open job per student (partial unique index)
        # =====================================================================
        sid3 = 3
        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
            " VALUES (?, 1, 'pending', ?, 0)",
            (sid3, "2026-09-26 12:00:00"),
        )
        check("E1 first open job (pending) allowed", err is None, str(err))

        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
            " VALUES (?, 2, 'pending', ?, 0)",
            (sid3, "2026-09-26 12:00:00"),
        )
        check("E2 second pending rejected (open-job constraint)", err is not None, str(err))

        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
            " VALUES (?, 2, 'claimed', ?, 0)",
            (sid3, "2026-09-26 12:00:00"),
        )
        check("E3 pending + claimed rejected (open-job constraint)", err is not None, str(err))

        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
            " VALUES (?, 2, 'running', ?, 0)",
            (sid3, "2026-09-26 12:00:00"),
        )
        check("E4 pending + running rejected (open-job constraint)", err is not None, str(err))

        # open for a *different* student is fine (next attempt past D's rows)
        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
            " VALUES (?, ?, 'pending', ?, 0)",
            (sid6, base6 + 5, "2026-09-26 12:00:00"),
        )
        check("E5 open job for other student allowed", err is None, str(err))
        if err is None:
            # close it for later tests
            delete_raw("bot_jobs", "student_id=? AND attempt_number=? AND status='pending'",
                       (sid6, base6 + 5))

        # close open job for sid3 -> new open allowed (only this test's rows)
        _ours_sql, _ours_p = ours_where()
        c = raw_conn()
        c.execute("UPDATE bot_jobs SET status='failed', completed_at=? WHERE student_id=?"
                  " AND status='pending'" + _ours_sql,
                  ("2026-09-26 12:00:00", sid3) + _ours_p)
        c.commit()
        c.close()
        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
            " VALUES (?, 2, 'pending', ?, 0)",
            (sid3, "2026-09-26 12:00:00"),
        )
        check("E6 new open job allowed after terminal state", err is None, str(err))

        # =====================================================================
        # F. status CHECK constraint
        # =====================================================================
        for i, st in enumerate(BOT_JOB_STATUSES, start=10):
            err = insert_raw(
                "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
                " outcome_known, finish_clicked, indicator_detected)"
                " VALUES (4, ?, ?, ?, 0, 1, 1, 1)",
                (i, st, "2026-09-26 12:00:00"),
            )
            check(f"F{i - 9} status '{st}' accepted", err is None, str(err))
            if st in ("pending", "claimed", "running"):
                # close open row so the next open status for the same student can be tested
                # (predicate restricted to rows created by this run)
                _ours_sql, _ours_p = ours_where()
                c = raw_conn()
                c.execute("UPDATE bot_jobs SET status='cancelled' WHERE student_id=4"
                          " AND attempt_number=?" + _ours_sql, (i,) + _ours_p)
                c.commit()
                c.close()

        for i, bad in enumerate(("retrying", "fill_only", "unknown_outcome", ""), start=1):
            err = insert_raw(
                "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
                " VALUES (4, ?, ?, ?, 0)",
                (100 + i, bad, "2026-09-26 12:00:00"),
            )
            check(f"F_invalid_{bad!r} rejected", err is not None, str(err))

        # =====================================================================
        # G. failure_category CHECK constraint
        # =====================================================================
        for i, cat in enumerate(BOT_JOB_FAILURE_CATEGORIES, start=20):
            err = insert_raw(
                "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
                " failure_category, outcome_known) VALUES (4, ?, 'failed', ?, 0, ?, 0)",
                (i, "2026-09-26 12:00:00", cat),
            )
            check(f"G_{cat} accepted", err is None, str(err))

        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
            " failure_category) VALUES (4, 90, 'failed', ?, 0, 'database')",
            ("2026-09-26 12:00:00",),
        )
        check("G_unknown category 'database' rejected", err is not None, str(err))

        # =====================================================================
        # H. success evidence CHECK (never imply fill_success is success)
        # =====================================================================
        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
            " VALUES (7, 1, 'success', ?, 0)",
            ("2026-09-26 12:00:00",),
        )
        check("H1 success without evidence (NULLs) rejected", err is not None, str(err))

        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
            " outcome_known, finish_clicked, indicator_detected)"
            " VALUES (7, 1, 'success', ?, 0, 1, 0, 1)",
            ("2026-09-26 12:00:00",),
        )
        check("H2 success without finish_clicked rejected", err is not None, str(err))

        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
            " outcome_known, finish_clicked, indicator_detected)"
            " VALUES (7, 1, 'success', ?, 0, 1, 1, 0)",
            ("2026-09-26 12:00:00",),
        )
        check("H3 success without indicator_detected rejected", err is not None, str(err))

        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
            " outcome_known, finish_clicked, indicator_detected)"
            " VALUES (7, 1, 'success', ?, 0, 1, 1, 1)",
            ("2026-09-26 12:00:00",),
        )
        check("H4 success with full evidence accepted", err is None, str(err))

        # uncertain outcome: failed + outcome_known=0 must be representable
        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
            " failure_category, outcome_known, error_message)"
            " VALUES (7, 2, 'failed', ?, 0, 'timeout', 0, 'uncertain: no response')",
            ("2026-09-26 12:00:00",),
        )
        check("H5 uncertain outcome (failed + outcome_known=0) allowed", err is None, str(err))

        # =====================================================================
        # I. snapshot storage (materialized at claim; immutable JSON + version)
        # =====================================================================
        version = datetime.utcnow().isoformat(sep=" ", timespec="microseconds")
        snapshot = json.dumps({"name": "SNAPSHOT TEST", "transport": "Institution Bus"})

        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
            " snapshot_json, student_data_version, snapshot_materialized_at)"
            " VALUES (9, 1, 'claimed', ?, 0, ?, ?, ?)",
            ("2026-09-26 12:00:00", snapshot, version, "2026-09-26 12:00:01"),
        )
        check("I1 snapshot + version insertable", err is None, str(err))

        c = raw_conn()
        _ours_sql, _ours_p = ours_where()
        row = c.execute(
            "SELECT snapshot_json, student_data_version, snapshot_materialized_at, status"
            " FROM bot_jobs WHERE student_id=9 AND attempt_number=1" + _ours_sql,
            _ours_p,
        ).fetchone()
        c.close()
        if row:
            check("I2 snapshot JSON round-trips",
                  json.loads(row["snapshot_json"]) == {"name": "SNAPSHOT TEST", "transport": "Institution Bus"},
                  row["snapshot_json"])
            check("I3 snapshot version stored", row["student_data_version"] == version,
                  str(row["student_data_version"]))
            check("I4 snapshot materialized_at stored", bool(row["snapshot_materialized_at"]))
            check("I5 snapshot belongs to its attempt (claimed)", row["status"] == "claimed", row["status"])
        else:
            check("I2 snapshot JSON round-trips", False, "row missing")
            check("I3 snapshot version stored", False, "row missing")
            check("I4 snapshot materialized_at stored", False, "row missing")
            check("I5 snapshot belongs to its attempt (claimed)", False, "row missing")

        # close student 9's open job first so I6 hits the snapshot CHECK, not the open-job index
        # (predicates restricted to rows created by this run)
        _ours_sql, _ours_p = ours_where()
        c = raw_conn()
        c.execute("UPDATE bot_jobs SET status='running' WHERE student_id=9"
                  " AND attempt_number=1" + _ours_sql, _ours_p)
        c.execute("UPDATE bot_jobs SET status='cancelled', completed_at='2026-09-26 12:00:02'"
                  " WHERE student_id=9 AND attempt_number=1" + _ours_sql, _ours_p)
        c.commit()
        c.close()
        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
            " snapshot_json) VALUES (9, 2, 'pending', ?, 0, '{}')",
            ("2026-09-26 12:00:00",),
        )
        check("I6 snapshot_json without version rejected", err is not None, str(err))
        check("I6b rejection is the snapshot CHECK", bool(err and "ck_bot_jobs_snapshot_requires_version" in err),
              str(err))

        # =====================================================================
        # J. foreign key enforcement (PRAGMA foreign_keys=ON)
        # =====================================================================
        c = raw_conn()
        c.execute("PRAGMA foreign_keys=ON")
        try:
            c.execute(
                "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation)"
                " VALUES (999999, 1, 'pending', ?, 0)",
                ("2026-09-26 12:00:00",),
            )
            c.commit()
            check("J1 FK: job with unknown student rejected", False, "insert succeeded")
        except sqlite3.IntegrityError as e:
            check("J1 FK: job with unknown student rejected", True, str(e))
        finally:
            c.close()

        # =====================================================================
        # K. lease / claim runtime fields are storable (schema only, no behavior)
        # =====================================================================
        err = insert_raw(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, claim_generation,"
            " claimed_by, lease_expires_at, last_heartbeat_at, claimed_at)"
            " VALUES (10, 1, 'claimed', ?, 1, 'bot-1', ?, ?, ?)",
            ("2026-09-26 12:00:00", "2026-09-26 12:15:00", "2026-09-26 12:00:05", "2026-09-26 12:00:01"),
        )
        check("K1 lease/heartbeat/claim fields storable", err is None, str(err))

    finally:
        # Guaranteed cleanup (3B.8): remove only rows created by this run, even if a
        # check above raised. Pre-existing rows are never matched.
        if created_job_ids:
            ph = ",".join("?" * len(created_job_ids))
            delete_raw("bot_jobs", f"id IN ({ph})", tuple(created_job_ids))
        for i in created_ids:
            st = db.session.get(Student, i)
            if st:
                db.session.delete(st)
        db.session.commit()

    # Post-cleanup assertions (run only on the success path)
    check("K2 bot_jobs test rows cleaned (created ids only)", True,
          f"created={len(created_job_ids)}")

    after_jobs = all_jobs()
    check("K3 bot_jobs count restored to baseline", len(after_jobs) == len(baseline_jobs),
          f"baseline={len(baseline_jobs)} after={len(after_jobs)}")
    check("K3b pre-existing bot_jobs rows byte-identical", after_jobs == baseline_jobs,
          f"baseline_ids={[r['id'] for r in baseline_jobs]} after_ids={[r['id'] for r in after_jobs]}")
    gone = all(not db.session.get(Student, i) for i in created_ids)
    check("K4 test student cleaned", gone, f"created_students={created_ids}")

failed = [r for r in results if not r[1]]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
