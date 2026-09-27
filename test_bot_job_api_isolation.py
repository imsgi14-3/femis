"""3B.7 Item 1: isolation proof for test_bot_job_api.py cleanup scoping.

Creates a pre-existing, unrelated (sentinel) bot_jobs row, runs the full API suite as a
subprocess with that row present, then proves:

  1. the API suite still passes with a pre-existing row present,
  2. the sentinel row survived byte-identical (not deleted, not mutated),
  3. the suite removed only rows/students it created itself,
  4. no suite-named student leftovers remain,
  5. after this file cleans up its own sentinel, bot_jobs is exactly pristine again.

The sentinel is created and deleted by THIS file only (never used as a suite fixture),
and no 3B.6 evidence/job rows are used anywhere.
"""
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

# Same test-only tokens the suite under test configures for itself (env is read at
# request time; the subprocess suite overwrites these with identical values).
os.environ["FEMIS_BOT_TOKEN"] = "p3b4-bot-secret-7f3a9c21"
os.environ["FEMIS_OPERATOR_TOKEN"] = "p3b4-operator-secret-5e2b1d44"

from app import app, db  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


DB_PATH = ROOT / "femis-web" / "instance" / "femis.db"
OP_H = {"X-Operator-Token": os.environ["FEMIS_OPERATOR_TOKEN"]}


def rows(query, params=()):
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(query, params).fetchall()]
    finally:
        c.close()


def sql(query, params=()):
    c = sqlite3.connect(str(DB_PATH))
    try:
        c.execute(query, params)
        c.commit()
        return None
    except sqlite3.Error as e:
        return str(e)
    finally:
        c.close()


sentinel_sid = None
sentinel_job = None
pristine = []
with_sentinel = []
students_before = []

try:
    with app.app_context():
        pristine = rows("SELECT * FROM bot_jobs ORDER BY id")
        students_before = [r["id"] for r in rows("SELECT id FROM students ORDER BY id")]

        # --- 1. sentinel student (owned by this file) ---------------------
        r = app.test_client().post(
            "/api/save-tab",
            json={"tab": 1, "student_id": None, "data": {"name": "P3B7 ISOLATION SENTINEL"}},
        )
        j = r.get_json() or {}
        sentinel_sid = j.get("student_id") if j.get("ok") else None
        check("sentinel student created", sentinel_sid is not None, str(j))

        # --- 2. sentinel job via the real operator API, driven to a -------
        # terminal state (cancelled) so claim-next can never touch it.
        c = app.test_client()
        with c.session_transaction() as s:
            s["role"] = "teacher"
            s["user_name"] = "P3B7 Isolation"
        ver = rows("SELECT updated_at FROM students WHERE id=?", (sentinel_sid,))[0]["updated_at"]
        r = c.post(
            "/api/jobs",
            json={"student_id": sentinel_sid, "student_data_version": ver},
            headers=OP_H,
        )
        j = r.get_json() or {}
        sentinel_job = (j.get("job") or {}).get("job_id")
        check("sentinel job created (pending)", r.status_code == 200 and sentinel_job, str(j)[:200])
        r = c.post(f"/api/jobs/{sentinel_job}/cancel", json={}, headers=OP_H)
        j = r.get_json() or {}
        check(
            "sentinel job terminal (cancelled)",
            r.status_code == 200 and (j.get("job") or {}).get("status") == "cancelled",
            str(j)[:200],
        )

        with_sentinel = rows("SELECT * FROM bot_jobs ORDER BY id")
        check(
            "sentinel is a pre-existing row alongside pristine rows",
            len(with_sentinel) == len(pristine) + 1,
            f"pristine={len(pristine)} with_sentinel={len(with_sentinel)}",
        )

        # --- 3. run the suite under test with the sentinel present --------
        db.session.remove()
        db.engine.dispose()  # parent must hold no DB connection during the run
        proc = subprocess.run(
            [sys.executable, "test_bot_job_api.py"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        m = re.search(r"(\d+)/(\d+) passed", out)
        check(
            "API suite passes with pre-existing row present",
            proc.returncode == 0 and m is not None,
            f"rc={proc.returncode} summary={m.group(0) if m else 'no summary'}",
        )
        check(
            "API suite reported no FAIL lines",
            "FAIL:" not in out,
            out.strip().splitlines()[-1][:120] if out.strip() else "no output",
        )
        check(
            "API suite check count intact (>=123, all equal)",
            bool(m) and int(m.group(1)) == int(m.group(2)) and int(m.group(1)) >= 123,
            m.group(0) if m else "no summary",
        )

        # --- 4. prove the suite touched nothing pre-existing --------------
        after = rows("SELECT * FROM bot_jobs ORDER BY id")
        sentinel_before = [r for r in with_sentinel if r["id"] == sentinel_job]
        sentinel_after = [r for r in after if r["id"] == sentinel_job]
        check(
            "sentinel bot_jobs row survived byte-identical",
            sentinel_after and sentinel_after == sentinel_before,
            f"before={sentinel_before} after={sentinel_after}",
        )
        check(
            "suite removed only its own rows (bot_jobs == with_sentinel)",
            after == with_sentinel,
            f"expected={len(with_sentinel)} actual={len(after)}",
        )
        students_after = [r["id"] for r in rows("SELECT id FROM students ORDER BY id")]
        check(
            "suite removed only its own students (sentinel student kept)",
            students_after == sorted(students_before + [sentinel_sid]),
            f"before={students_before} after={students_after}",
        )
        leftovers = rows(
            "SELECT id, name FROM students WHERE name LIKE 'P3B4 %' OR name LIKE 'P3B5 %'"
        )
        check("no suite-named student leftovers", not leftovers, str(leftovers))
finally:
    # --- cleanup: only this file's sentinel, scoped by its own ids ---------
    if sentinel_sid:
        sql("DELETE FROM bot_jobs WHERE student_id=?", (sentinel_sid,))
        sql("DELETE FROM students WHERE id=?", (sentinel_sid,))
    final_jobs = rows("SELECT * FROM bot_jobs ORDER BY id")
    final_students = [r["id"] for r in rows("SELECT id FROM students ORDER BY id")]
    check(
        "sentinel cleaned up; bot_jobs restored to pristine",
        final_jobs == pristine,
        f"pristine={len(pristine)} final={len(final_jobs)}",
    )
    check(
        "students restored to pre-test set",
        final_students == sorted(students_before),
        f"before={students_before} final={final_students}",
    )

failed = [n for n, ok in results if not ok]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
