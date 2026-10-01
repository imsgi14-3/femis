"""Phase 3B.10: students.created_at NOT NULL migration integrity suite.

Proves the migration invariant from three independent angles:
  1. Schema  - SQLite table_info/DDL declare created_at NOT NULL.
  2. Data    - every row has non-NULL created_at; schema rejects NULL at insert time
               (raw sqlite3 and ORM both).
  3. Create  - every production creation path still succeeds after the change.
Also locks: column count, index set, foreign keys, row counts and Ahmed's backfill value.

Only rows created by this file are deleted; pre-existing students are never touched.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import Student, app, db  # noqa: E402
from form_payloads import tab1  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


DB_PATH = ROOT / "femis-web" / "instance" / "femis.db"
PROBE_NAME = "PHASE B TEN INTEGRITY PROBE"
EXPECTED_STUDENT_IDS = [3, 4, 6, 8, 9, 10]
EXPECTED_INDEXES = ["ix_bot_jobs_lease", "ix_bot_jobs_status_created",
                    "ix_bot_jobs_student_created", "ix_bot_jobs_student_id",
                    "sqlite_autoindex_app_settings_1",
                    "sqlite_autoindex_bot_jobs_1", "sqlite_autoindex_bot_jobs_2",
                    "uq_bot_jobs_open_per_student", "uq_students_b_form",
                    "uq_students_class_section_roll"]
created_ids = []
students_before = []
botjobs_before = 0


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


def one(q, p=()):
    r = rows(q, p)
    return r[0] if r else None


try:
    students_before = [r["id"] for r in rows("SELECT id FROM students ORDER BY id")]
    botjobs_before = one("SELECT COUNT(*) AS n FROM bot_jobs")["n"]

    # ---- 1. schema-level invariant ---------------------------------------
    info = rows("PRAGMA table_info(students)")
    ca = [x for x in info if x["name"] == "created_at"]
    check("1a table_info: created_at exists", len(ca) == 1, str(ca))
    check("1b table_info: notnull flag = 1", bool(ca) and ca[0]["notnull"] == 1,
          str(ca[0] if ca else None))
    ddl = one("SELECT sql FROM sqlite_master WHERE type='table' AND name='students'")
    check("1c DDL declares created_at DATETIME NOT NULL",
          bool(ddl) and "created_at DATETIME NOT NULL" in ddl["sql"], "")
    check("1d column count unchanged (141)", len(info) == 141, str(len(info)))

    # ---- 2. data-level invariant -----------------------------------------
    nulls = rows("SELECT id FROM students WHERE created_at IS NULL")
    check("2a 0 NULL created_at rows", nulls == [], str(nulls))
    check("2b expected students present", [r["id"] for r in
          rows("SELECT id FROM students ORDER BY id")] == EXPECTED_STUDENT_IDS,
          str([r["id"] for r in rows("SELECT id FROM students ORDER BY id")]))
    ahmed = one("SELECT created_at FROM students WHERE id=8")
    check("2c Ahmed backfill value locked to documented timestamp",
          bool(ahmed) and ahmed["created_at"] == "2026-09-26 16:59:22",
          str(ahmed))
    check("2d every updated_at non-NULL (3B.3 contract)",
          rows("SELECT id FROM students WHERE updated_at IS NULL") == [])

    # ---- 3. schema rejects NULL (raw sqlite3) -----------------------------
    err = sql("INSERT INTO students (name) VALUES (?)", (PROBE_NAME,))
    check("3a raw INSERT omitting created_at rejected", err is not None and
          not rows("SELECT id FROM students WHERE name=?", (PROBE_NAME,)),
          f"err={err}")
    err = sql("INSERT INTO students (name, created_at) VALUES (?, NULL)", (PROBE_NAME,))
    check("3b raw INSERT with explicit NULL rejected",
          err is not None and not rows("SELECT id FROM students WHERE name=?",
                                       (PROBE_NAME,)), f"err={err}")
    check("3c rejected inserts left no partial rows",
          not rows("SELECT id FROM students WHERE name LIKE ?", (PROBE_NAME + "%",)))

    # ---- 4. ORM behavior after model alignment ---------------------------
    with app.app_context():
        s = Student(name=PROBE_NAME)
        db.session.add(s)
        db.session.commit()
        created_ids.append(s.id)
        check("4a ORM insert (no created_at arg) succeeds with default",
              s.created_at is not None, str(s.created_at))
        orm_null_stored = True
        orm_err = ""
        try:
            db.session.execute(
                db.text("INSERT INTO students (name, created_at) VALUES (:n, NULL)"),
                {"n": PROBE_NAME + " ORMA"})
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            orm_null_stored = False
            orm_err = str(e).splitlines()[0]
        check("4b ORM insert with explicit created_at=None rejected by schema",
              not orm_null_stored, "" if not orm_null_stored else f"stored: {orm_err}")
        try:
            s2 = Student(name=PROBE_NAME + " ORMNULL", created_at=None)
            db.session.add(s2)
            db.session.commit()
            check("4c ORM Student(created_at=None) uses column default (non-NULL)",
                  s2.created_at is not None, str(s2.created_at))
            created_ids.append(s2.id)
        except Exception as e:
            db.session.rollback()
            # explicit None may either fall back to the default OR be rejected;
            # either outcome is safe — the row must not exist with NULL.
            left = rows("SELECT id, created_at FROM students WHERE name=?",
                        (PROBE_NAME + " ORMNULL",))
            check("4c ORM Student(created_at=None) never stores NULL",
                  not left or left[0]["created_at"] is not None,
                  f"err={str(e).splitlines()[0]} leftover={left}")

        # ---- 5. production create path still works -----------------------
        client = app.test_client()
        r = client.post("/api/save-tab", json={
            "tab": 1, "student_id": None,
            "data": tab1(name=PROBE_NAME + " SAVE", created_at=None),
        })
        b = r.get_json() or {}
        sid = b.get("student_id") if b.get("ok") else None
        if sid:
            created_ids.append(sid)
        check("5a save-tab create path works post-migration (created_at: null in payload)",
              r.status_code == 200 and sid is not None, str(b))
        if sid:
            row = one("SELECT created_at FROM students WHERE id=?", (sid,))
            check("5b save-tab row has non-NULL created_at",
                  bool(row) and row["created_at"] is not None, str(row))

    # ---- 6. structural locks: indexes / FKs / bot_jobs --------------------
    idx = sorted(r["name"] for r in rows(
        "SELECT name FROM sqlite_master WHERE type='index'"))
    check("6a index set unchanged", idx == EXPECTED_INDEXES, str(idx))
    uq = one("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_students_b_form'")
    check("6b uq_students_b_form SQL identical to pre-migration",
          bool(uq) and uq["sql"] == "CREATE UNIQUE INDEX uq_students_b_form ON students "
          "(replace(replace(replace(b_form, '-', ''), ' ', ''), '.', '')) "
          "WHERE b_form IS NOT NULL AND b_form <> ''", str(uq))
    fks = sorted(rows("PRAGMA foreign_key_list(bot_jobs)"),
                 key=lambda r: (r["table"], r["from"]))
    check("6c bot_jobs foreign keys unchanged",
          [(f["table"], f["from"], f["to"], f["on_delete"]) for f in fks]
          == [("bot_jobs", "prior_attempt_id", "id", "SET NULL"),
              ("students", "student_id", "id", "CASCADE")], str(fks))
    tables = sorted(r["name"] for r in rows(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    check("6d exactly 4 tables (no students_new leftover)",
          tables == ["app_settings", "bot_jobs", "students", "teachers"], str(tables))
    nb = one("SELECT COUNT(*) AS n FROM bot_jobs")["n"]
    nulls = one("SELECT COUNT(*) AS n FROM bot_jobs WHERE created_at IS NULL")["n"]
    check("6e bot_jobs baseline unchanged + created_at never NULL",
          nb == botjobs_before and nulls == 0,
          f"total={nb} baseline={botjobs_before} null_created_at={nulls}")
    n_students = len(rows("SELECT id FROM students"))
    check("6f student count = baseline + this file's live probe rows",
          n_students == len(students_before) + len(created_ids),
          f"total={n_students} baseline={len(students_before)} probes={len(created_ids)}")

    # ---- 7. integrity checks ---------------------------------------------
    integ = rows("PRAGMA integrity_check")
    check("7a PRAGMA integrity_check ok",
          len(integ) == 1 and "ok" in list(integ[0].values())[0], str(integ))
    fk_bad = rows("PRAGMA foreign_key_check")
    check("7b PRAGMA foreign_key_check clean", fk_bad == [], str(fk_bad))
finally:
    # cleanup: only this file's rows (own ids + probe names), scoped
    if created_ids:
        ph = ",".join("?" * len(created_ids))
        sql(f"DELETE FROM students WHERE id IN ({ph})", tuple(created_ids))
    sql("DELETE FROM students WHERE name LIKE ?", (PROBE_NAME + "%",))
    final = [r["id"] for r in rows("SELECT id FROM students ORDER BY id")]
    nulls = rows("SELECT id FROM students WHERE created_at IS NULL")
    check("E1 students restored to baseline (own rows only removed)",
          final == sorted(students_before), f"before={students_before} final={final}")
    check("E2 post-cleanup still 0 NULL created_at rows", nulls == [], str(nulls))

failed = [n for n, ok in results if not ok]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
