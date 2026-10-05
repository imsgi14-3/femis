"""Export Data tab: teacher/admin field-picker export to Excel/PDF.

Covers the /export page + POST /api/export/students route:
  * catalog      — form.html-pane grouping, core/record groups, no duplicate
                   columns, labels present, Yes/No flags, defaults in catalog
  * page guards  — anon 302, student 403, teacher/admin 200 with picker
  * api guards   — anon 401, student 403, format/fields validation -> 422
  * scoping      — teacher xlsx = own class+section rows only; admin = all
  * content      — xlsx headers = requested labels, Yes/No rendering,
                   pdf = %PDF magic, download filenames carry the scope tag
  * invariants   — export is read-only (student ids untouched), cell_value
                   unit rules (bool/1/0/datetime/None)

Fixtures are created (2 students) and removed again in finally; the
baseline id list is captured BEFORE fixture creation so the check works
against any restored DB state.

Run: python test_export.py   (exit 0 = all pass)
"""
import io
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    app, db, Student,
    _EXPORT_GROUPS, _EXPORT_LABELS, _EXPORT_YESNO, _EXPORT_DEFAULTS,
)
import student_export  # noqa: E402
from form_payloads import tab1  # noqa: E402
from sqlalchemy import text  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

DB = ROOT / "femis-web" / "instance" / "femis.db"
TEACHER_CLASS, TEACHER_SECTION = "9", "A"
OTHER_CLASS, OTHER_SECTION = "8", "B"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


def client(role=None, name="exporttest"):
    c = app.test_client()
    if role:
        with c.session_transaction() as s:
            s["role"] = role
            s["user_name"] = name
            if role == "teacher":
                s["teacher_class"] = TEACHER_CLASS
                s["teacher_section"] = TEACHER_SECTION
    return c


def create_student(name, class_id, section_id, roll):
    r = app.test_client().post(
        "/api/save-tab",
        json={"tab": 1, "student_id": None,
              "data": tab1(name=name, class_id=class_id,
                           section_id=section_id, roll_no=roll)},
    )
    b = r.get_json() or {}
    return b.get("student_id") if b.get("ok") else None


def sheet_rows(resp):
    wb = load_workbook(io.BytesIO(resp.data))
    return [list(r) for r in wb.active.iter_rows(values_only=True)]


created_students = []
baseline_ids = []

try:
    with app.app_context():
        baseline_ids = [i for (i,) in db.session.execute(
            text("SELECT id FROM students ORDER BY id"))]

    # ------------------------------------------------------------------
    # A. Catalog structure
    # ------------------------------------------------------------------
    titles = [t for t, _ in _EXPORT_GROUPS]
    all_cols = [c for _, items in _EXPORT_GROUPS for c, _ in items]
    stu_cols = {c.name for c in Student.__table__.columns}
    check("A1 groups: Student first, Record last, >= 8 groups",
          len(titles) >= 8 and titles[0] == "Student" and titles[-1] == "Record",
          titles)
    check("A2 no duplicate columns; role excluded; covers all real columns",
          len(all_cols) == len(set(all_cols))
          and "role" not in all_cols
          and set(all_cols) == stu_cols - {"role"},
          f"{len(all_cols)} cols vs {len(stu_cols)} columns")
    check("A3 every column has a non-empty label",
          all(isinstance(l, str) and l.strip() for l in _EXPORT_LABELS.values())
          and len(_EXPORT_LABELS) == len(all_cols),
          len(_EXPORT_LABELS))
    check("A4 defaults = 11 core fields, all present in catalog",
          _EXPORT_DEFAULTS == [c for c, _ in student_export._CORE_FIELDS]
          and all(c in _EXPORT_LABELS for c in _EXPORT_DEFAULTS),
          _EXPORT_DEFAULTS)
    gmap = {t: [c for c, _ in items] for t, items in _EXPORT_GROUPS}
    check("A5 pane grouping: emergency_* under Emergency, digital_* under Digital",
          "emergency_contact" in gmap.get("Emergency Contact", [])
          and "emergency_name" in gmap.get("Emergency Contact", [])
          and "digital_device_type" in gmap.get("Digital Access", [])
          and "father_cnic" in gmap.get("Parents / Guardian", []),
          {t: len(v) for t, v in gmap.items()})
    check("A6 Yes/No flags: submitted/locked + form yesno cols, all in catalog",
          {"submitted", "locked"} <= _EXPORT_YESNO
          and "digital_device_at_home" in _EXPORT_YESNO
          and _EXPORT_YESNO <= set(_EXPORT_LABELS),
          sorted(_EXPORT_YESNO)[:6])
    check("A7 catalog covers form panes (7 pane groups + core + record)",
          len(titles) == 9, titles)

    # ------------------------------------------------------------------
    # B. GET /export page guards
    # ------------------------------------------------------------------
    anon = app.test_client()
    r = anon.get("/export", follow_redirects=False)
    check("B1 anon /export -> login redirect",
          r.status_code == 302 and "/login" in (r.headers.get("Location") or ""),
          r.headers.get("Location"))

    stu = client(role="student")
    r = stu.get("/export")
    check("B2 student /export -> 403", r.status_code == 403, r.status_code)

    tch = client(role="teacher")
    r = tch.get("/export")
    body = r.get_data(as_text=True)
    scope_txt = f"Class {TEACHER_CLASS} - Section {TEACHER_SECTION}"
    check("B3 teacher /export -> 200 with scope badge + field picker",
          r.status_code == 200 and scope_txt in body
          and 'id="exportFields"' in body and "Export Excel" in body
          and "Export PDF" in body,
          str(r.status_code))

    adm = client(role="admin")
    r = adm.get("/export")
    body = r.get_data(as_text=True)
    check("B4 admin /export -> 200, All classes scope",
          r.status_code == 200 and "All classes" in body
          and 'id="exportFields"' in body,
          str(r.status_code))

    # ------------------------------------------------------------------
    # C. POST /api/export/students guards + validation
    # ------------------------------------------------------------------
    r = anon.post("/api/export/students",
                  json={"format": "xlsx", "fields": ["name"]})
    b = r.get_json() or {}
    check("C1 anon api -> 401 authentication_required",
          r.status_code == 401 and not b.get("ok"), r.status_code)

    r = stu.post("/api/export/students",
                 json={"format": "xlsx", "fields": ["name"]})
    check("C2 student api -> 403", r.status_code == 403, r.status_code)

    for label, payload in [
        ("bad format", {"format": "csv", "fields": ["name"]}),
        ("missing fields", {"format": "xlsx"}),
        ("empty fields list", {"format": "xlsx", "fields": []}),
        ("non-list fields", {"format": "xlsx", "fields": "name"}),
        ("only non-string entries", {"format": "xlsx", "fields": [1, None]}),
    ]:
        r = adm.post("/api/export/students", json=payload)
        b = r.get_json() or {}
        check(f"C3 validation: {label} -> 422",
              r.status_code == 422 and not b.get("ok") and b.get("error"),
              f"{r.status_code} {b.get('error')}")

    r = adm.post("/api/export/students",
                 json={"format": "xlsx", "fields": ["name", "not_a_column"]})
    b = r.get_json() or {}
    check("C4 unknown field named in 422 error",
          r.status_code == 422 and "not_a_column" in (b.get("error") or ""),
          b.get("error"))

    too_many = list(_EXPORT_LABELS)[:31]
    r = adm.post("/api/export/students",
                 json={"format": "pdf", "fields": too_many})
    b = r.get_json() or {}
    check("C5 pdf >30 columns -> 422 suggesting Excel",
          r.status_code == 422 and "Excel" in (b.get("error") or ""),
          b.get("error"))

    # ------------------------------------------------------------------
    # D. Fixtures (own class + foreign class) for scoping checks
    # ------------------------------------------------------------------
    sid_own = create_student("Export Own Student", TEACHER_CLASS,
                             TEACHER_SECTION, "9091")
    sid_other = create_student("Export Other Student", OTHER_CLASS,
                               OTHER_SECTION, "9092")
    created_students += [sid_own, sid_other]
    check("D1 fixtures created", bool(sid_own and sid_other),
          (sid_own, sid_other))

    fields = ["name", "class_id", "section_id", "roll_no", "submitted", "locked"]
    labels = [_EXPORT_LABELS[c] for c in fields]

    # ------------------------------------------------------------------
    # E. Teacher export: scoped rows only, correct headers/filename
    # ------------------------------------------------------------------
    with app.app_context():
        own_names = [n for (n,) in db.session.execute(text(
            "SELECT name FROM students WHERE class_id = :c AND section_id = :s"),
            {"c": TEACHER_CLASS, "s": TEACHER_SECTION})]
        total = db.session.execute(text(
            "SELECT COUNT(*) FROM students")).scalar()

    r = tch.post("/api/export/students",
                 json={"format": "xlsx", "fields": fields})
    cd = r.headers.get("Content-Disposition") or ""
    rows = sheet_rows(r) if r.status_code == 200 else []
    check("E1 teacher xlsx 200 + filename students_9A_<date>.xlsx",
          r.status_code == 200 and "students_9A_" in cd and ".xlsx" in cd,
          f"{r.status_code} {cd}")
    check("E2 xlsx headers == requested labels",
          rows and list(rows[0]) == labels,
          rows[0] if rows else None)
    body_names = {row[0] for row in rows[1:]}
    check("E3 teacher xlsx = own class rows only (foreign student absent)",
          len(rows) - 1 == len(own_names)
          and "Export Other Student" not in body_names
          and "Export Own Student" in body_names,
          f"rows={len(rows) - 1} expected={len(own_names)}")

    # ------------------------------------------------------------------
    # F. Admin export: all rows
    # ------------------------------------------------------------------
    r = adm.post("/api/export/students",
                 json={"format": "xlsx", "fields": fields})
    cd = r.headers.get("Content-Disposition") or ""
    rows = sheet_rows(r) if r.status_code == 200 else []
    body_names = {row[0] for row in rows[1:]}
    check("F1 admin xlsx 200 + filename students_all_<date>.xlsx",
          r.status_code == 200 and "students_all_" in cd and ".xlsx" in cd,
          f"{r.status_code} {cd}")
    check("F2 admin xlsx covers every student (both fixtures present)",
          len(rows) - 1 == total
          and {"Export Own Student", "Export Other Student"} <= body_names,
          f"rows={len(rows) - 1} total={total}")

    # ------------------------------------------------------------------
    # G. Yes/No rendering + PDF
    # ------------------------------------------------------------------
    sub_row = [row for row in rows[1:] if row[0] == "Export Own Student"]
    yesno_vals_ok = (sub_row and sub_row[0][4] in ("Yes", "No")
                     and sub_row[0][5] in ("Yes", "No"))
    check("G1 submitted/locked render as Yes/No", bool(yesno_vals_ok),
          sub_row[0][4:6] if sub_row else None)

    r = adm.post("/api/export/students",
                 json={"format": "pdf", "fields": ["name", "class_id",
                                                   "section_id", "roll_no"]})
    cd = r.headers.get("Content-Disposition") or ""
    check("G2 admin pdf 200, %PDF magic, .pdf filename",
          r.status_code == 200 and r.data[:4] == b"%PDF"
          and ".pdf" in cd and "students_all_" in cd,
          f"{r.status_code} {r.data[:4]!r} {cd}")

    r = tch.post("/api/export/students",
                 json={"format": "pdf", "fields": ["name", "roll_no"]})
    check("G3 teacher pdf 200 (scoped)",
          r.status_code == 200 and r.data[:4] == b"%PDF"
          and "students_9A_" in (r.headers.get("Content-Disposition") or ""),
          r.status_code)

    # ------------------------------------------------------------------
    # H. cell_value unit rules
    # ------------------------------------------------------------------
    fake = SimpleNamespace(submitted=1, locked=0, name="X",
                           created_at=datetime(2026, 10, 5, 16, 30),
                           date_of_birth=date(2026, 1, 2),
                           father_name=None)
    check("H1 bool/1/0 -> Yes/No (yesno col), raw otherwise",
          student_export.cell_value(fake, "submitted", True) == "Yes"
          and student_export.cell_value(fake, "locked", True) == "No"
          and student_export.cell_value(fake, "submitted", False) == "1",
          (student_export.cell_value(fake, "submitted", True),
           student_export.cell_value(fake, "locked", True),
           student_export.cell_value(fake, "submitted", False)))
    check("H2 datetime/date formatted, None -> empty string",
          student_export.cell_value(fake, "created_at") == "2026-10-05 16:30"
          and student_export.cell_value(fake, "date_of_birth") == "2026-01-02"
          and student_export.cell_value(fake, "father_name") == "",
          (student_export.cell_value(fake, "created_at"),
           student_export.cell_value(fake, "date_of_birth")))

    # ------------------------------------------------------------------
    # I. Dashboard buttons (entry points)
    # ------------------------------------------------------------------
    dash = tch.get("/teacher-dashboard").get_data(as_text=True)
    check("I1 teacher dashboard links /export",
          'href="/export"' in dash, dash.count('href="/export"'))
    adash = adm.get("/teacher-dashboard").get_data(as_text=True)
    check("I2 admin dashboard links /export",
          'href="/export"' in adash, adash.count('href="/export"'))

finally:
    # ------------------------------------------------------------------
    # Cleanup: temp students removed; baseline ids restored; DB read-only
    # (export never wrote a row — verified by the id compare).
    # ------------------------------------------------------------------
    with app.app_context():
        for sid in [s for s in created_students if s]:
            st = Student.query.get(sid)
            if st:
                db.session.delete(st)
        db.session.commit()

    con = sqlite3.connect(str(DB))
    ids = [r[0] for r in con.execute("SELECT id FROM students ORDER BY id")]
    con.close()
    check("Z1 students baseline ids restored after export suite",
          ids == baseline_ids, ids)
    check("Z2 both fixtures removed",
          all(s not in ids for s in created_students if s),
          (len(ids), len(baseline_ids)))

passed = sum(1 for _, ok, _ in results if ok)
print("=" * 50)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
