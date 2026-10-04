"""Phase 3B.9 audit test: every production student-creation path stores non-NULL created_at.

Covers the three ORM creation paths proven by the creation-path audit:
  A. POST /api/save-tab create branch (incl. crafted `created_at: null` payload)
  B. POST /submit legacy form create branch (incl. crafted `created_at=""` payload)
  C. POST /login student auto-create branch
Phase 3B.10 refit: the raw-SQL control now proves raw inserts are REJECTED by the
NOT NULL schema (D1), and Ahmed Khan's row carries the documented backfill value (D2).

Only rows created by this file are deleted; pre-existing students are never touched.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import app, db  # noqa: E402
from form_payloads import form_all, tab1  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


DB_PATH = ROOT / "femis-web" / "instance" / "femis.db"
P3B9 = "PHASE B NINE CREATION PROBE"
created_ids = []
students_before = []


def rows(q, p=()):
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(q, p).fetchall()]
    finally:
        c.close()


def sql(q, p=()):
    c = sqlite3.connect(str(DB_PATH))
    try:
        c.execute(q, p)
        c.commit()
        return None
    except sqlite3.Error as e:
        return str(e)
    finally:
        c.close()


try:
    students_before = [r["id"] for r in rows("SELECT id FROM students ORDER BY id")]

    with app.app_context():
        client = app.test_client()

        # --- A. /api/save-tab create, incl. crafted created_at: null --------
        r = client.post("/api/save-tab", json={
            "tab": 1, "student_id": None,
            "data": tab1(name=P3B9, created_at=None),
        })
        b = r.get_json() or {}
        sid_a = b.get("student_id") if b.get("ok") else None
        if sid_a:
            created_ids.append(sid_a)
        check("A1 save-tab create ok (with injected created_at: null)",
              r.status_code == 200 and sid_a is not None, str(b))
        if sid_a:
            row = rows("SELECT created_at FROM students WHERE id=?", (sid_a,))[0]
            check("A2 save-tab row created_at non-NULL",
                  row["created_at"] is not None, str(row["created_at"]))

        # --- B. legacy POST /submit create ---------------------------------
        # complete form payload (server mandatory twin rejects partials)
        r = client.post("/submit", data=form_all(
            name=P3B9 + " LEGACY", class_id="9", section_id="B"))
        loc = r.headers.get("Location", "")
        b_id = loc.rsplit("/", 1)[-1] if r.status_code == 302 and loc.rsplit("/", 1)[-1].isdigit() else None
        if b_id:
            created_ids.append(int(b_id))
        check("B1 legacy /submit create redirects to success",
              r.status_code == 302 and b_id is not None, f"{r.status_code} {loc}")
        if b_id:
            row = rows("SELECT created_at FROM students WHERE id=?", (b_id,))[0]
            check("B2 legacy /submit row created_at non-NULL",
                  row["created_at"] is not None, str(row["created_at"]))

        # crafted legacy payload: created_at="" must fail loudly, never store NULL
        r = client.post("/submit", data=form_all(
            name=P3B9 + " CRAFT", created_at=""))
        leftover = rows("SELECT id, created_at FROM students WHERE name=?", (P3B9 + " CRAFT",))
        check("B3 crafted created_at='' rejected, no NULL row stored",
              r.status_code >= 400 and not leftover,
              f"status={r.status_code} rows={leftover}")
        # the intentional 500 above leaves this test's shared session dirty
        # (production requests get a fresh session per request); reset it
        db.session.rollback()

        # --- C. /login student auto-create ---------------------------------
        # roll must be a whole number since login validation went strict
        # (2026-10-03 directive: class/roll digits-only, section A/B/C)
        r = client.post("/login", data={
            "role": "student", "name": P3B9 + " LOGIN",
            "class_id": "9", "section": "B", "roll_no": "9701",
        })
        sid_c = None
        if r.status_code == 302:
            found = rows("SELECT id FROM students WHERE name=?", (P3B9 + " LOGIN",))
            sid_c = found[0]["id"] if found else None
        if sid_c:
            created_ids.append(sid_c)
        check("C1 /login auto-create student ok",
              r.status_code == 302 and sid_c is not None, f"status={r.status_code}")
        if sid_c:
            row = rows("SELECT created_at FROM students WHERE id=?", (sid_c,))[0]
            check("C2 /login-created row created_at non-NULL",
                  row["created_at"] is not None, str(row["created_at"]))

        # --- raw-SQL control: schema now rejects NULL created_at -----------
        err = sql("INSERT INTO students (name) VALUES (?)", (P3B9 + " RAW",))
        raw_row = rows("SELECT id, created_at FROM students WHERE name=?", (P3B9 + " RAW",))
        if raw_row:
            created_ids.append(raw_row[0]["id"])
        check("D1 raw SQL insert without created_at rejected by NOT NULL schema",
              err is not None and not raw_row,
              f"err={err} row={raw_row}")
        err2 = sql("INSERT INTO students (name, created_at) VALUES (?, NULL)",
                   (P3B9 + " RAW2",))
        raw_row2 = rows("SELECT id, created_at FROM students WHERE name=?", (P3B9 + " RAW2",))
        if raw_row2:
            created_ids.append(raw_row2[0]["id"])
        check("D1b raw SQL insert with explicit NULL rejected; no row stored",
              err2 is not None and not raw_row2, f"err={err2} row={raw_row2}")

        # --- backfill lock: Ahmed's row carries the documented value -------
        ahmed = rows("SELECT id, name, created_at FROM students WHERE id=8")
        check("D2 Ahmed id 8 created_at = documented migration backfill value",
              ahmed and ahmed[0]["name"] == "Ahmed Khan"
              and ahmed[0]["created_at"] == "2026-09-26 16:59:22",
              str(ahmed))
finally:
    # cleanup: only this file's rows (own ids + P3B9 names), scoped
    if created_ids:
        ph = ",".join("?" * len(created_ids))
        sql(f"DELETE FROM students WHERE id IN ({ph})", tuple(created_ids))
    sql("DELETE FROM students WHERE name LIKE ?", (P3B9 + "%",))
    final = [r["id"] for r in rows("SELECT id FROM students ORDER BY id")]
    check("E1 students restored to baseline (own rows only removed)",
          final == sorted(students_before), f"before={students_before} final={final}")

failed = [n for n, ok in results if not ok]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
