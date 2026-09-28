"""3B.7 Item 2, refitted by 3B.10: NULL created_at is no longer a renderable state.

Post-migration (students.created_at NOT NULL) this file proves the new invariant while
keeping its original purpose — the pages it was written to exercise still work:
  * the schema rejects every raw/ORM attempt to store NULL (no NULL row can exist),
  * there are 0 NULL created_at rows in the live database,
  * GET /students, GET /success/<id> and the student JSON endpoint still render/serve.
Any probe rows created here are deleted by THIS file; pre-existing students untouched.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import Student, app, db  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


DB_PATH = ROOT / "femis-web" / "instance" / "femis.db"
PROBE_NAME = "P3B7 NOT NULL PROBE"


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


def one(query, params=()):
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    try:
        r = c.execute(query, params).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


probe_sid = None
students_before = []

try:
    with app.app_context():
        # idempotency: remove any leftover probe row from a previously crashed run
        sql("DELETE FROM students WHERE name=?", (PROBE_NAME,))
        students_before = sorted(
            r[0] for r in
            sqlite3.connect(str(DB_PATH)).execute("SELECT id FROM students").fetchall()
        )

        # --- schema-level invariant: 0 NULL rows anywhere ------------------
        null_count = one("SELECT COUNT(*) AS n FROM students WHERE created_at IS NULL")
        check("live database has 0 NULL created_at rows",
              null_count and null_count["n"] == 0, str(null_count))

        # --- raw SQL cannot create a NULL row (omit or explicit NULL) ------
        err = sql("INSERT INTO students (name) VALUES (?)", (PROBE_NAME,))
        row = one("SELECT id, created_at FROM students WHERE name=?", (PROBE_NAME,))
        check("raw INSERT omitting created_at rejected by schema",
              err is not None and row is None, f"err={err} row={row}")
        err = sql("INSERT INTO students (name, created_at) VALUES (?, NULL)", (PROBE_NAME,))
        row = one("SELECT id, created_at FROM students WHERE name=?", (PROBE_NAME,))
        check("raw INSERT with explicit NULL created_at rejected by schema",
              err is not None and row is None, f"err={err} row={row}")

        # --- an ORM-created row always carries a real timestamp ------------
        s = Student(name=PROBE_NAME)
        db.session.add(s)
        db.session.commit()
        probe_sid = s.id
        check("ORM-created row stores non-NULL created_at",
              s.created_at is not None, str(s.created_at))

        client = app.test_client()
        with client.session_transaction() as s:
            s["role"] = "admin"

        # --- GET /students still renders a valid created_at record ---------
        r = client.get("/students")
        body = r.get_data(as_text=True) if r.status_code == 200 else ""
        check("GET /students returns 200", r.status_code == 200,
              f"status={r.status_code}")
        check("GET /students lists the ORM-created probe row", PROBE_NAME in body, "")
        valid = one(
            "SELECT name FROM students WHERE created_at IS NOT NULL AND id != ? LIMIT 1",
            (probe_sid,),
        )
        check("GET /students still renders a pre-existing valid created_at record",
              bool(valid) and valid["name"] in body, str(valid))

        # --- GET /success/<id> --------------------------------------------
        r = client.get(f"/success/{probe_sid}")
        check("GET /success/<probe row> returns 200", r.status_code == 200,
              f"status={r.status_code}")

        # --- JSON endpoint serves a non-null created_at --------------------
        r = client.get(f"/students/{probe_sid}/json")
        j = r.get_json() or {}
        check("student JSON serves created_at non-null",
              r.status_code == 200 and j.get("created_at") is not None,
              str(j.get("created_at")))
finally:
    if probe_sid:
        sql("DELETE FROM students WHERE id=?", (probe_sid,))
    sql("DELETE FROM students WHERE name=?", (PROBE_NAME,))
    c = sqlite3.connect(str(DB_PATH))
    final = [r[0] for r in c.execute("SELECT id FROM students ORDER BY id").fetchall()]
    nulls = c.execute("SELECT COUNT(*) FROM students WHERE created_at IS NULL").fetchone()[0]
    c.close()
    if students_before:
        check("probe row cleaned up; students restored",
              final == sorted(students_before), f"before={students_before} final={final}")
    check("final state still has 0 NULL created_at rows", nulls == 0, f"nulls={nulls}")

failed = [n for n, ok in results if not ok]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
