"""RBAC regression: admin/teacher/student authorization gates (C1-C4).

Covers: env-seeded admin login, admin-only teacher creation, class+section
ownership on modify/read/lock routes, student own-record isolation, and the
job-api operator role gate. Auth fixtures use session_transaction directly;
behavioral coverage of passwords lives in the login checks below.

Run: python test_rbac.py   (exit 0 = all pass)
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import app, db, Student, Teacher  # noqa: E402
from form_payloads import create_full, tab1  # noqa: E402
from sqlalchemy import text  # noqa: E402

DB = ROOT / "femis-web" / "instance" / "femis.db"
BASELINE_IDS = [3, 4, 6, 8, 9, 10]
OP_TOKEN = "rbac-test-operator-token"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


def client(role=None, student_id=None, teacher_class=None, teacher_section=None, name="rbac"):
    c = app.test_client()
    if role:
        with c.session_transaction() as s:
            s["role"] = role
            s["user_name"] = name
            if student_id is not None:
                s["student_id"] = student_id
            if teacher_class is not None:
                s["teacher_class"] = teacher_class
                s["teacher_section"] = teacher_section
    return c


def create_student(name, class_id, section_id, roll):
    # create branch stays open (anon) but must carry a complete tab-1
    # payload — server mandatory twin rejects partial creates
    r = app.test_client().post(
        "/api/save-tab",
        json={"tab": 1, "student_id": None,
              "data": tab1(name=name, class_id=class_id,
                           section_id=section_id, roll_no=roll)},
    )
    b = r.get_json() or {}
    return b.get("student_id") if b.get("ok") else None


admin_name = (os.environ.get("FEMIS_ADMIN_NAME") or "").strip()
admin_pass = (os.environ.get("FEMIS_ADMIN_PASSWORD") or "").strip()
os.environ["FEMIS_OPERATOR_TOKEN"] = OP_TOKEN
OP_H = {"X-Operator-Token": OP_TOKEN}

created_students = []
created_teachers = []

try:
    with app.app_context():
        # ==============================================================
        # A. Admin bootstrap / login
        # ==============================================================
        admin_rows = Teacher.query.filter(Teacher.role == "admin").all()
        check("A1 env seeded exactly one admin", len(admin_rows) == 1,
              [a.name for a in admin_rows])
        check("A2 admin credentials configured in env",
              bool(admin_name and admin_pass),
              f"name={'set' if admin_name else 'MISSING'}")

        c = app.test_client()
        r = c.get("/login")
        body = r.get_data(as_text=True)
        check("A3 login page hides Setup Admin box when admin exists",
              r.status_code == 200 and "First time? Set up the Admin account" not in body,
              str(r.status_code))

        r = c.post("/login", data={"role": "admin", "name": admin_name,
                                   "password": admin_pass}, follow_redirects=False)
        with c.session_transaction() as s:
            s_role = s.get("role")
        check("A4 admin login -> dashboard, session role=admin",
              r.status_code == 302 and "teacher-dashboard" in (r.headers.get("Location") or "")
              and s_role == "admin",
              f"r={r.status_code} loc={r.headers.get('Location')} role={s_role}")

        c = app.test_client()
        r = c.post("/login", data={"role": "admin", "name": admin_name,
                                   "password": "wrong-password"}, follow_redirects=False)
        with c.session_transaction() as s:
            bad_role = s.get("role")
        check("A5 wrong admin password -> bounced to /login, no role granted",
              r.status_code == 302 and "/login" in (r.headers.get("Location") or "")
              and bad_role != "admin",
              f"loc={r.headers.get('Location')} role={bad_role}")
        r = c.get("/api/admin/bot/jobs")
        b = r.get_json() or {}
        check("A5b failed login cannot reach admin endpoints (401)",
              r.status_code == 401
              and b.get("error_code") == "authentication_required",
              f"{r.status_code} {b}")

        r = app.test_client().post("/api/setup-admin", json={"name": "X", "password": "y"})
        check("A6 setup-admin refuses when admin exists", r.status_code == 400, r.status_code)

        r = app.test_client().post("/api/setup-teacher",
                                   json={"name": "X", "password": "y",
                                         "class_id": "9", "section": "Z"})
        check("A7 old /api/setup-teacher route is gone", r.status_code == 404, r.status_code)

        # ==============================================================
        # B. Teacher creation is admin-only
        # ==============================================================
        r = app.test_client().post("/api/register-teacher",
                                   json={"name": "RBAC Temp Teacher", "password": "pw",
                                         "class_id": "9", "section": "R"})
        check("B1 anon cannot register teacher", r.status_code == 403, r.status_code)

        r = client(role="teacher", teacher_class="9", teacher_section="A") \
            .post("/api/register-teacher",
                  json={"name": "RBAC Temp Teacher", "password": "pw",
                        "class_id": "9", "section": "R"})
        check("B2 teacher cannot register teacher", r.status_code == 403, r.status_code)

        r = client(role="admin").post(
            "/api/register-teacher",
            json={"name": "RBAC Temp Teacher", "password": "pw",
                  "class_id": "9", "section": "R"})
        b = r.get_json() or {}
        check("B3 admin can register teacher", r.status_code == 200 and b.get("ok"), json.dumps(b))
        if b.get("teacher_id"):
            created_teachers.append(b["teacher_id"])

        r = app.test_client().post("/login",
                                   data={"role": "teacher", "name": "RBAC Temp Teacher",
                                         "password": "pw", "class_id": "9", "section": "R"},
                                   follow_redirects=False)
        check("B4 registered teacher can log in",
              r.status_code == 302 and "teacher-dashboard" in (r.headers.get("Location") or ""),
              r.headers.get("Location"))

        # ==============================================================
        # C. Fixtures (student create path stays open = public registration)
        # ==============================================================
        sid_own = create_student("RBAC Own Student", "9", "A", "901")
        sid_other = create_student("RBAC Other Student", "8", "B", "801")
        created_students += [sid_own, sid_other]
        check("C1 fixtures created (open student registration path)",
              bool(sid_own and sid_other), (sid_own, sid_other))

        t_9a = client(role="teacher", teacher_class="9", teacher_section="A")
        t_other = client(role="teacher", teacher_class="8", teacher_section="B")
        s_own = client(role="student", student_id=sid_own)
        s_other = client(role="student", student_id=sid_other)
        adm = client(role="admin")

        # ==============================================================
        # D. save-tab / final-submit ownership
        # ==============================================================
        r = t_9a.post("/api/save-tab", json={"tab": 1, "student_id": sid_own,
                                             "data": {"name": "RBAC Own Student"}})
        check("D1 teacher saves own-class student", r.status_code == 200
              and (r.get_json() or {}).get("ok"), r.status_code)

        r = t_9a.post("/api/save-tab", json={"tab": 1, "student_id": sid_other,
                                             "data": {"name": "h4x"}})
        check("D2 teacher blocked from other-class student", r.status_code == 403, r.status_code)

        r = s_own.post("/api/save-tab", json={"tab": 1, "student_id": sid_own,
                                              "data": {"name": "RBAC Own Student"}})
        check("D3 student saves own record", r.status_code == 200
              and (r.get_json() or {}).get("ok"), r.status_code)

        r = s_other.post("/api/save-tab", json={"tab": 1, "student_id": sid_own,
                                                "data": {"name": "h4x"}})
        check("D4 student blocked from another student's record", r.status_code == 403,
              r.status_code)

        r = adm.post("/api/save-tab", json={"tab": 1, "student_id": sid_other,
                                            "data": {"name": "RBAC Other Student"}})
        check("D5 admin saves any record", r.status_code == 200
              and (r.get_json() or {}).get("ok"), r.status_code)

        r = t_9a.post("/api/final-submit", json={"student_id": sid_other, "data": {}})
        check("D6 teacher final-submit blocked for other class", r.status_code == 403,
              r.status_code)

        # ==============================================================
        # E. /students/<id>/json read gate
        # ==============================================================
        r = app.test_client().get(f"/students/{sid_own}/json")
        check("E1 anon json -> 401", r.status_code == 401, r.status_code)
        r = t_9a.get(f"/students/{sid_other}/json")
        check("E2 teacher json other-class -> 403", r.status_code == 403, r.status_code)
        r = t_9a.get(f"/students/{sid_own}/json")
        check("E3 teacher json own-class -> 200", r.status_code == 200, r.status_code)
        r = s_own.get(f"/students/{sid_other}/json")
        check("E4 student json other -> 403", r.status_code == 403, r.status_code)
        r = s_own.get(f"/students/{sid_own}/json")
        check("E5 student json own -> 200", r.status_code == 200, r.status_code)
        r = adm.get(f"/students/{sid_other}/json")
        check("E6 admin json any -> 200", r.status_code == 200, r.status_code)

        # ==============================================================
        # F. /form/<id> page gate
        # ==============================================================
        r = app.test_client().get(f"/form/{sid_own}", follow_redirects=False)
        check("F1 anon form -> redirect to login",
              r.status_code == 302 and "/login" in (r.headers.get("Location") or ""),
              r.headers.get("Location"))
        r = t_9a.get(f"/form/{sid_other}")
        check("F2 teacher form other-class -> 403", r.status_code == 403, r.status_code)
        r = t_9a.get(f"/form/{sid_own}")
        check("F3 teacher form own-class -> 200", r.status_code == 200, r.status_code)
        r = s_other.get(f"/form/{sid_own}", follow_redirects=False)
        check("F4 student form other -> own dashboard",
              r.status_code == 302 and "student-dashboard" in (r.headers.get("Location") or ""),
              r.headers.get("Location"))
        r = adm.get(f"/form/{sid_own}")
        check("F5 admin form any -> 200", r.status_code == 200, r.status_code)

        # ==============================================================
        # G. lock / unlock gates + locked-record write rule
        # ==============================================================
        r = app.test_client().post(f"/api/lock/{sid_own}")
        check("G1 anon lock -> 403", r.status_code == 403, r.status_code)
        r = t_9a.post(f"/api/lock/{sid_other}")
        check("G2 teacher lock other-class -> 403", r.status_code == 403, r.status_code)
        r = t_9a.post(f"/api/lock/{sid_own}")
        check("G3 teacher lock own-class -> ok", r.status_code == 200
              and (r.get_json() or {}).get("locked") is True, r.status_code)

        r = s_own.post("/api/save-tab", json={"tab": 1, "student_id": sid_own,
                                              "data": {"name": "RBAC Own Student"}})
        check("G4 student cannot edit own LOCKED record", r.status_code == 403, r.status_code)
        r = t_9a.post("/api/save-tab", json={"tab": 1, "student_id": sid_own,
                                             "data": {"name": "RBAC Own Student"}})
        check("G5 owning teacher can edit locked record", r.status_code == 200, r.status_code)

        r = adm.post(f"/api/unlock/{sid_own}")
        check("G6 admin unlocks", r.status_code == 200
              and (r.get_json() or {}).get("locked") is False, r.status_code)
        r = s_own.post("/api/save-tab", json={"tab": 1, "student_id": sid_own,
                                              "data": {"name": "RBAC Own Student"}})
        check("G7 student can edit after unlock", r.status_code == 200, r.status_code)

        # ==============================================================
        # H. /students list filtering
        # ==============================================================
        r = t_9a.get("/students")
        body = r.get_data(as_text=True)
        check("H1 teacher list shows own class only",
              r.status_code == 200 and "RBAC Own Student" in body
              and "RBAC Other Student" not in body, str(r.status_code))
        r = s_own.get("/students")
        body = r.get_data(as_text=True)
        check("H2 student list shows own record only",
              r.status_code == 200 and "RBAC Own Student" in body
              and "RBAC Other Student" not in body, str(r.status_code))
        r = adm.get("/students")
        body = r.get_data(as_text=True)
        check("H3 admin list shows all",
              r.status_code == 200 and "RBAC Own Student" in body
              and "RBAC Other Student" in body, str(r.status_code))
        r = app.test_client().get("/students", follow_redirects=False)
        check("H4 anon list -> login redirect",
              r.status_code == 302 and "/login" in (r.headers.get("Location") or ""),
              r.headers.get("Location"))

        # ==============================================================
        # I. job-api operator role gate
        # ==============================================================
        r = app.test_client().get("/api/jobs", headers=OP_H)
        check("I1 anon job list -> 401", r.status_code == 401, r.status_code)
        r = client(role="student", student_id=sid_own).get("/api/jobs", headers=OP_H)
        check("I2 student job list -> 403 forbidden_role", r.status_code == 403, r.status_code)
        r = t_9a.get("/api/jobs", headers=OP_H)
        check("I3 teacher job list -> 200", r.status_code == 200, r.status_code)
        r = adm.get("/api/jobs", headers=OP_H)
        b = r.get_json() or {}
        check("I4 admin job list -> 200", r.status_code == 200 and b.get("ok") is not False,
              str(r.status_code))

        # ==============================================================
        # J. Delete endpoint + admin teacher management + admin dashboard
        # ==============================================================
        r = app.test_client().post(f"/api/delete/{sid_own}")
        check("J1 anon delete -> 403", r.status_code == 403, r.status_code)
        r = s_own.post(f"/api/delete/{sid_own}")
        check("J2 student delete -> 403", r.status_code == 403, r.status_code)
        r = t_9a.post(f"/api/delete/{sid_other}")
        check("J3 teacher delete other-class -> 403", r.status_code == 403, r.status_code)

        sid_del = create_student("RBAC Del Student", "9", "A", "902")
        created_students.append(sid_del)
        db.session.execute(text(
            "INSERT INTO bot_jobs (student_id, attempt_number, status, created_at, "
            "claim_generation) VALUES (:s, 1, 'pending', CURRENT_TIMESTAMP, 0)"),
            {"s": sid_del})
        db.session.commit()
        r = t_9a.post(f"/api/delete/{sid_del}")
        b = r.get_json() or {}
        n_jobs = db.session.execute(text(
            "SELECT COUNT(*) FROM bot_jobs WHERE student_id = :s"),
            {"s": sid_del}).scalar()
        check("J4 teacher deletes own student + bot_jobs cascade",
              r.status_code == 200 and b.get("ok") and b.get("deleted_jobs") == 1
              and n_jobs == 0, (r.status_code, b, n_jobs))

        admin_row = Teacher.query.filter(Teacher.role == "admin").first()
        admin_id = admin_row.id
        admin_display_name = admin_row.name
        r = adm.post(f"/api/admin/teachers/{admin_id}/delete")
        check("J5 admin row cannot be deleted", r.status_code == 403, r.status_code)

        temp_tid = created_teachers[0] if created_teachers else None
        if temp_tid:
            r = t_9a.post(f"/api/admin/teachers/{temp_tid}/delete")
            check("J6 teacher cannot delete teachers", r.status_code == 403, r.status_code)
            r = adm.post(f"/api/admin/teachers/{temp_tid}/reset-password",
                         json={"password": "rbac-new-pw"})
            check("J7 admin resets teacher password", r.status_code == 200, r.status_code)
            r = app.test_client().post(
                "/login",
                data={"role": "teacher", "name": "RBAC Temp Teacher",
                      "password": "rbac-new-pw", "class_id": "9", "section": "R"},
                follow_redirects=False)
            check("J8 teacher logs in with reset password",
                  r.status_code == 302 and "teacher-dashboard" in (r.headers.get("Location") or ""),
                  r.headers.get("Location"))
            r = app.test_client().post(
                "/login",
                data={"role": "teacher", "name": "RBAC Temp Teacher",
                      "password": "pw", "class_id": "9", "section": "R"},
                follow_redirects=False)
            check("J9 old password no longer works",
                  not (r.status_code == 302 and "teacher-dashboard" in (r.headers.get("Location") or "")),
                  r.headers.get("Location"))

        r = adm.get("/teacher-dashboard")
        body = r.get_data(as_text=True)
        check("J10 admin dashboard: summary cards + section links, no full dump",
              r.status_code == 200 and 'href="/admin/students"' in body
              and 'href="/admin/teachers"' in body and 'href="/admin/bot"' in body
              and "RBAC Own Student" not in body
              and "RBAC Temp Teacher" not in body
              and admin_display_name not in body,
              str(r.status_code))
        check("J10b admin section pages: teacher/student 403, anon 302",
              all(t_9a.get(p).status_code == 403
                  for p in ("/admin/students", "/admin/teachers", "/admin/bot"))
              and client(role="student").get("/admin/students").status_code == 403
              and client().get("/admin/students").status_code == 302,
              t_9a.get("/admin/students").status_code)
        r_s = adm.get("/admin/students")
        b_s = r_s.get_data(as_text=True)
        check("J10c /admin/students: paged table + filters + search",
              r_s.status_code == 200 and 'data-sid=' in b_s
              and 'name="q"' in b_s and 'name="per"' in b_s and 'name="class"' in b_s
              and 'name="status"' in b_s,
              str(r_s.status_code))
        r_t = adm.get("/admin/teachers")
        b_t = r_t.get_data(as_text=True)
        check("J11 /admin/teachers has Add Teacher button + table",
              r_t.status_code == 200 and "Add Teacher" in b_t
              and 'data-tid=' in b_t, str(r_t.status_code))
        r_b = adm.get("/admin/bot")
        check("J11b /admin/bot renders the bot console",
              r_b.status_code == 200
              and 'id="botQueueCard"' in r_b.get_data(as_text=True),
              str(r_b.status_code))

        r = t_9a.get("/teacher-dashboard")
        body = r.get_data(as_text=True)
        check("J12 teacher dashboard: no Add Teacher, no other-class student",
              r.status_code == 200 and "Add Teacher" not in body
              and "RBAC Other Student" not in body, str(r.status_code))

        # Success-page dashboard link follows the role: admin/teacher use the
        # shared admin-view dashboard, students their own — never a plain table.
        html_adm = adm.get(f"/success/{sid_own}").get_data(as_text=True)
        html_tch = t_9a.get(f"/success/{sid_own}").get_data(as_text=True)
        html_stu = s_own.get(f"/success/{sid_own}").get_data(as_text=True)
        check("J12b success page dashboard link is role-aware",
              'href="/teacher-dashboard"' in html_adm
              and 'href="/teacher-dashboard"' in html_tch
              and 'href="/student-dashboard"' in html_stu
              and 'href="/students"' not in html_stu,
              f"adm={'teacher' if '/teacher-dashboard' in html_adm else '?'} "
              f"stu={'student' if '/student-dashboard' in html_stu else '?'}")

        r = adm.post(f"/api/delete/{sid_other}")
        check("J13 admin deletes any student", r.status_code == 200
              and (r.get_json() or {}).get("ok"), r.status_code)

        # ==============================================================
        # K. Admin DB export (source for tools/sync_from_portal.py)
        # ==============================================================
        r = app.test_client().get("/api/admin/export")
        check("K1 anon export -> 401", r.status_code == 401, r.status_code)
        r = t_9a.get("/api/admin/export")
        check("K2 teacher export -> 403", r.status_code == 403, r.status_code)
        r = adm.get("/api/admin/export")
        check("K3 admin export -> valid sqlite attachment",
              r.status_code == 200
              and r.data[:16] == b"SQLite format 3\x00"
              and "attachment" in (r.headers.get("Content-Disposition") or ""),
              (r.status_code, r.data[:16], r.headers.get("Content-Disposition")))
        import tempfile as _tf
        with _tf.NamedTemporaryFile(suffix=".db", delete=False) as _f:
            _f.write(r.data)
            _tmp_db = _f.name
        try:
            _con = sqlite3.connect(_tmp_db)
            _integrity = _con.execute("PRAGMA integrity_check").fetchone()[0]
            _n_students = _con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
            _n_admins = _con.execute(
                "SELECT COUNT(*) FROM teachers WHERE role='admin'").fetchone()[0]
            _con.close()
        finally:
            Path(_tmp_db).unlink(missing_ok=True)
        check("K4 export passes integrity_check + contains data",
              str(_integrity).lower() == "ok" and _n_students >= 6 and _n_admins == 1,
              (_integrity, _n_students, _n_admins))

        # ==============================================================
        # L. Blank /form route + post-submit redirect (Add Student fix)
        # ==============================================================
        r = app.test_client().get("/form")
        check("L1 anon /form -> login", r.status_code == 302
              and "/login" in (r.headers.get("Location") or ""),
              r.headers.get("Location"))

        r = t_9a.get("/form")
        body = r.get_data(as_text=True)
        check("L2 teacher /form -> blank new-student form",
              r.status_code == 200 and "New Student Admission" in body
              and 'id="student_id" value=""' in body, str(r.status_code))

        r = adm.get("/form")
        check("L3 admin /form -> blank new-student form",
              r.status_code == 200
              and "New Student Admission" in r.get_data(as_text=True),
              str(r.status_code))

        # L5/L6 final-submit expects 200 -> this carrier must be complete
        st_m, body_m = create_full(client(role="admin"),
                                   name="RBAC Redirect Student",
                                   class_id="9", section_id="A", roll_no="991")
        sid_mine = body_m.get("student_id") if st_m == 200 else None
        created_students.append(sid_mine)
        r = client(role="student", student_id=sid_mine).get("/form")
        check("L4 student /form -> redirect to own record",
              r.status_code == 302
              and f"/form/{sid_mine}" in (r.headers.get("Location") or ""),
              r.headers.get("Location"))

        r = client(role="student", student_id=sid_mine).post(
            "/api/final-submit", json={"student_id": sid_mine, "data": {}})
        b = r.get_json() or {}
        check("L5 student final-submit -> student dashboard",
              r.status_code == 200 and b.get("redirect") == "/student-dashboard",
              json.dumps(b))

        r = adm.post("/api/final-submit",
                     json={"student_id": sid_mine, "data": {}})
        b = r.get_json() or {}
        check("L6 admin final-submit -> success page",
              r.status_code == 200
              and (b.get("redirect") or "").startswith("/success/"),
              json.dumps(b))

        r = t_9a.get("/teacher-dashboard")
        body = r.get_data(as_text=True)
        check("L7 dashboard button is Add Student -> /form, New Admission gone",
              "Add Student" in body and 'href="/form"' in body
              and "New Admission" not in body, str(r.status_code))

        r = client(role="student").get("/student-dashboard")
        body = r.get_data(as_text=True)
        check("L8 student Start Form button links to /form",
              r.status_code == 200 and 'href="/form"' in body,
              str(r.status_code))

finally:
    # ------------------------------------------------------------------
    # Cleanup: temp students + temp teacher; baseline must be restored.
    # The env-seeded admin row is never touched.
    # ------------------------------------------------------------------
    with app.app_context():
        for sid in [s for s in created_students if s]:
            st = Student.query.get(sid)
            if st:
                db.session.delete(st)
        for tid in created_teachers:
            t = Teacher.query.get(tid)
            if t:
                db.session.delete(t)
        db.session.commit()

    con = sqlite3.connect(str(DB))
    ids = [r[0] for r in con.execute("SELECT id FROM students ORDER BY id")]
    n_admin = con.execute("SELECT COUNT(*) FROM teachers WHERE role='admin'").fetchone()[0]
    n_temp = con.execute(
        "SELECT COUNT(*) FROM teachers WHERE name='RBAC Temp Teacher'").fetchone()[0]
    con.close()
    check("Z1 students baseline restored", ids == BASELINE_IDS, ids)
    check("Z2 admin still present, temp teacher removed",
          n_admin == 1 and n_temp == 0, (n_admin, n_temp))

passed = sum(1 for _, ok, _ in results if ok)
print("=" * 50)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
