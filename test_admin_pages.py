"""Admin section pages: overview cards, pagination, filters, search.

Covers the split of the old all-in-one admin dashboard into
/teacher-dashboard (summary cards) + /admin/students + /admin/teachers
+ /admin/bot:
  * guards      — anon 302, teacher/student 403, admin 200
  * overview    — card counts match the DB, section links, no full dump
  * students    — 10/20/50 pagination, page clamping, filters, search
  * teachers    — pagination + filters, admin row never listed

Fixtures are created (25 students, 12 teachers) and removed again; every
count assertion is scoped to their unique prefixes/classes so leftover rows
from other suites cannot change a result.

Run: python test_admin_pages.py   (exit 0 = all pass)
"""
import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import app, db, Student, Teacher, BotJob  # noqa: E402
from form_payloads import tab1  # noqa: E402

results = []

STU_PREFIX = "AP Student"
STU_CLASS = "APX"
STU_SECTION = "Q"
TCH_PREFIX = "AP Teacher"
TCH_CLASS = "TCA"
TCH_SECTION = "Z"

N_STUDENTS = 25
N_FEMALE = 8
N_SUBMITTED = 6
N_LOCKED = 4
N_TEACHERS = 12


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


def client(role=None, name="adminpages"):
    c = app.test_client()
    if role:
        with c.session_transaction() as s:
            s["role"] = role
            s["user_name"] = name
            if role == "teacher":
                s["teacher_class"] = "9"
                s["teacher_section"] = "A"
    return c


def row_ids(body, attr="data-sid"):
    return re.findall(rf'{attr}="(\d+)"', body)


created_students = []
created_teachers = []
created_botjobs = []

try:
    adm = client(role="admin")

    # ------------------------------------------------------------------
    # A. Guards on all three section pages
    # ------------------------------------------------------------------
    anon = app.test_client()
    tch = client(role="teacher")
    stu = client(role="student")
    paths = ("/admin/students", "/admin/teachers", "/admin/bot")
    check("A1 anon -> 302 login on every section page",
          all(anon.get(p).status_code == 302
              and "/login" in (anon.get(p).headers.get("Location") or "")
              for p in paths))
    check("A2 teacher -> 403 on every section page",
          all(tch.get(p).status_code == 403 for p in paths),
          str([tch.get(p).status_code for p in paths]))
    check("A3 student -> 403 on every section page",
          all(stu.get(p).status_code == 403 for p in paths),
          str([stu.get(p).status_code for p in paths]))
    check("A4 admin -> 200 on every section page",
          all(adm.get(p).status_code == 200 for p in paths),
          str([adm.get(p).status_code for p in paths]))

    # ------------------------------------------------------------------
    # B. Fixtures — 25 students (8 female, 6 submitted, 4 locked)
    # ------------------------------------------------------------------
    with app.app_context():
        for i in range(N_STUDENTS):
            over = dict(name=f"{STU_PREFIX} {chr(65 + i)}", class_id=STU_CLASS,
                        section_id=STU_SECTION, roll_no=f"9{900 + i}")
            if i < N_FEMALE:
                over.update(gender="Female", girls_stipend="0")
            r = app.test_client().post(
                "/api/save-tab", json={"tab": 1, "student_id": None,
                                       "data": tab1(**over)})
            b = r.get_json() or {}
            sid = b.get("student_id") if b.get("ok") else None
            if not sid:
                raise RuntimeError(f"fixture student {i} failed: {r.status_code} {b}")
            created_students.append(sid)
            st = Student.query.get(sid)
            if i < N_SUBMITTED:
                st.submitted = True
            if i < N_LOCKED:
                st.locked = True
        db.session.commit()

        for i in range(N_TEACHERS):
            t = Teacher(name=f"{TCH_PREFIX} {i:02d}", class_id=TCH_CLASS,
                        section_id=TCH_SECTION)
            t.set_password("ap-test-pw")
            db.session.add(t)
            db.session.commit()
            created_teachers.append(t.id)

        # ------------------------------------------------------------------
        # B2. Overview cards vs DB truth
        # ------------------------------------------------------------------
        s_total = Student.query.count()
        t_total = Teacher.query.filter(Teacher.role != "admin").count()
        bot_total = db.session.query(db.func.count(BotJob.id)).scalar() or 0

        body = adm.get("/teacher-dashboard").get_data(as_text=True)
        check("B1 overview links to all three sections",
              'href="/admin/students"' in body and 'href="/admin/teachers"' in body
              and 'href="/admin/bot"' in body, "")
        check("B2 student card count == DB total",
              f'id="statStudentsTotal">{s_total}<' in body, str(s_total))
        check("B3 teacher card count == non-admin DB total",
              f'id="statTeachersTotal">{t_total}<' in body, str(t_total))
        check("B4 bot card count == bot_jobs total",
              f'id="statBotJobs">{bot_total}<' in body, str(bot_total))
        check("B5 overview does not dump student rows",
              STU_PREFIX not in body and f"{STU_PREFIX} A" not in body, "")

        # ------------------------------------------------------------------
        # C. Students pagination (scoped to our prefix)
        # ------------------------------------------------------------------
        def spage(**kw):
            kw.setdefault("q", STU_PREFIX)
            qs = "&".join(f"{k}={quote(str(v))}" for k, v in kw.items())
            r = adm.get(f"/admin/students?{qs}")
            return r.get_data(as_text=True), r.status_code

        body, st = spage()
        check("C1 default page shows 10 of 25",
              st == 200 and len(row_ids(body)) == 10
              and f"of {N_STUDENTS} student(s)" in body
              and "page=2" in body,
              f"rows={len(row_ids(body))}")
        p1 = set(row_ids(body))

        body2, _ = spage(page=2)
        p2 = set(row_ids(body2))
        check("C2 page 2 shows 10 rows, disjoint from page 1",
              len(p2) == 10 and not (p1 & p2), f"rows={len(p2)}")
        body3, _ = spage(page=3)
        check("C3 last page shows the remaining 5",
              len(row_ids(body3)) == N_STUDENTS - 20, f"rows={len(row_ids(body3))}")

        body, _ = spage(per=20)
        check("C4 per=20 shows 20 rows", len(row_ids(body)) == 20,
              f"rows={len(row_ids(body))}")
        body, _ = spage(per=50)
        check("C5 per=50 shows all 25, pagination hidden",
              len(row_ids(body)) == N_STUDENTS and "page=2" not in body,
              f"rows={len(row_ids(body))}")

        body, _ = spage(per=15)
        check("C6 invalid per=15 falls back to 10",
              len(row_ids(body)) == 10, f"rows={len(row_ids(body))}")
        body, _ = spage(page=99)
        check("C7 out-of-range page clamps to last page",
              len(row_ids(body)) == N_STUDENTS - 20, f"rows={len(row_ids(body))}")
        body, _ = spage(page="abc")
        check("C8 non-numeric page falls back to 1",
              len(row_ids(body)) == 10, f"rows={len(row_ids(body))}")

        # ------------------------------------------------------------------
        # D. Students filters + search
        # ------------------------------------------------------------------
        body, _ = spage(gender="Female", per=50)
        check("D1 gender=Female returns exactly the 8 female fixtures",
              len(row_ids(body)) == N_FEMALE, f"rows={len(row_ids(body))}")

        body, _ = spage(status="submitted", per=50)
        check("D2 status=submitted returns the 6 submitted fixtures",
              len(row_ids(body)) == N_SUBMITTED, f"rows={len(row_ids(body))}")
        body, _ = spage(status="draft", per=50)
        check("D3 status=draft returns the other 19",
              len(row_ids(body)) == N_STUDENTS - N_SUBMITTED,
              f"rows={len(row_ids(body))}")

        body, _ = spage(lock="locked", per=50)
        check("D4 lock=locked returns the 4 locked fixtures",
              len(row_ids(body)) == N_LOCKED, f"rows={len(row_ids(body))}")

        r = adm.get(f"/admin/students?q={quote(f'{STU_PREFIX} H')}&per=50")
        b = r.get_data(as_text=True)
        check("D5 search by exact name returns 1 row",
              len(row_ids(b)) == 1, f"rows={len(row_ids(b))}")

        r = adm.get(f"/admin/students?class={STU_CLASS}&per=50")
        b = r.get_data(as_text=True)
        check("D6 class filter scopes to the 25 fixtures",
              len(row_ids(b)) == N_STUDENTS and f"of {N_STUDENTS} student(s)" in b,
              f"rows={len(row_ids(b))}")

        r = adm.get(f"/admin/students?q={quote(STU_PREFIX)}&section={STU_SECTION}&per=50")
        check("D7 combined q+section filter still returns 25",
              len(row_ids(r.get_data(as_text=True))) == N_STUDENTS,
              f"rows={len(row_ids(r.get_data(as_text=True)))}")

        r = adm.get("/admin/students?q=no-such-student-xyz")
        check("D8 no-match shows empty state, no rows",
              r.status_code == 200 and not row_ids(r.get_data(as_text=True))
              and "No students match" in r.get_data(as_text=True), "")

        # ------------------------------------------------------------------
        # E. Teachers pagination + filters
        # ------------------------------------------------------------------
        def tpage(**kw):
            kw.setdefault("q", TCH_PREFIX)
            qs = "&".join(f"{k}={quote(str(v))}" for k, v in kw.items())
            r = adm.get(f"/admin/teachers?{qs}")
            return r.get_data(as_text=True), r.status_code

        body, st = tpage()
        check("E1 default page shows 10 of 12 teachers",
              st == 200 and len(row_ids(body, "data-tid")) == 10
              and f"of {N_TEACHERS} teacher(s)" in body
              and "page=2" in body, f"rows={len(row_ids(body, 'data-tid'))}")
        body2, _ = tpage(page=2)
        check("E2 teacher page 2 shows the remaining 2",
              len(row_ids(body2, "data-tid")) == 2,
              f"rows={len(row_ids(body2, 'data-tid'))}")
        body, _ = tpage(per=20)
        check("E3 teachers per=20 shows all 12",
              len(row_ids(body, "data-tid")) == N_TEACHERS,
              f"rows={len(row_ids(body, 'data-tid'))}")

        r = adm.get(f"/admin/teachers?class={TCH_CLASS}&per=50")
        b = r.get_data(as_text=True)
        check("E4 class filter scopes to the 12 fixtures",
              len(row_ids(b, "data-tid")) == N_TEACHERS,
              f"rows={len(row_ids(b, 'data-tid'))}")

        body, _ = tpage(q=f"{TCH_PREFIX} 03", per=50)
        check("E5 teacher search by exact name returns 1 row",
              len(row_ids(body, "data-tid")) == 1,
              f"rows={len(row_ids(body, 'data-tid'))}")

        admin_row = Teacher.query.filter(Teacher.role == "admin").first()
        b = adm.get("/admin/teachers?per=50").get_data(as_text=True)
        check("E6 admin row is never listed on the teachers page",
              admin_row is None or admin_row.name not in b, "")

        # ------------------------------------------------------------------
        # F. Filter dropdowns are fed from real data
        # ------------------------------------------------------------------
        b = adm.get("/admin/students?per=50").get_data(as_text=True)
        check("F1 student filter offers the fixture class/section/gender",
              f'<option value="{STU_CLASS}"' in b
              and f'<option value="{STU_SECTION}"' in b
              and '<option value="Female"' in b, "")
        b = adm.get("/admin/teachers?per=50").get_data(as_text=True)
        check("F2 teacher filter offers the fixture class",
              f'<option value="{TCH_CLASS}"' in b, "")

        # ------------------------------------------------------------------
        # G. Bot status column on the students table (latest job per student)
        # ------------------------------------------------------------------
        sid_ok = created_students[-1]
        sid_fail = created_students[-2]
        sid_pend = created_students[-3]
        sid_none = created_students[-4]
        fixtures = (
            (sid_ok, "success", dict(
                attempt_number=1, bot_result_code="success",
                outcome_known=True, finish_clicked=True, indicator_detected=True)),
            (sid_fail, "failed", dict(
                attempt_number=3, bot_result_code="DATA_STALE",
                error_message="DATA_STALE: expected student version "
                              "2026-09-28 17:45:20.906722, current 2026-09-30 04:50:54.")),
            (sid_pend, "pending", dict(attempt_number=1)),
        )
        for sid, st, extra in fixtures:
            job = BotJob(student_id=sid, status=st, **extra)
            db.session.add(job)
            db.session.flush()
            created_botjobs.append(job.id)
        db.session.commit()

        b = adm.get(
            f"/admin/students?q={quote(STU_PREFIX)}&per=50"
        ).get_data(as_text=True)

        def row_of(body, sid):
            m = re.search(rf'<tr data-sid="{sid}">.*?</tr>', body, re.S)
            return m.group(0) if m else ""

        def badge(row, cls, text):
            return re.search(
                rf'<span class="badge {re.escape(cls)}"[^>]*>\s*{text}\s*</span>',
                row) is not None

        check("G1 students table has a Bot column",
              '<th width="90">Bot</th>' in b, "")
        row = row_of(b, sid_ok)
        check("G2 success job renders a success badge",
              badge(row, "bg-success", "success") and "Attempt 1" in row,
              row[:160])
        row = row_of(b, sid_fail)
        check("G3 failed job renders a failed badge + error tooltip",
              badge(row, "bg-danger", "failed") and "DATA_STALE" in row
              and "Attempt 3" in row, row[:160])
        row = row_of(b, sid_pend)
        check("G4 pending job renders a pending badge",
              badge(row, "bg-secondary", "pending"), row[:160])
        row = row_of(b, sid_none)
        check("G5 student with no job renders a dash",
              "Never queued" in row and "—" in row, row[:160])

finally:
    with app.app_context():
        for jid in created_botjobs:
            job = BotJob.query.get(jid)
            if job:
                db.session.delete(job)
        for sid in created_students:
            st = Student.query.get(sid)
            if st:
                db.session.delete(st)
        for tid in created_teachers:
            t = Teacher.query.get(tid)
            if t:
                db.session.delete(t)
        db.session.commit()
        left_s = [Student.query.get(s) for s in created_students]
        left_t = [Teacher.query.get(t) for t in created_teachers]
        check("Z1 cleanup removed every fixture row",
              not any(left_s) and not any(left_t),
              f"students_left={sum(1 for x in left_s if x)} "
              f"teachers_left={sum(1 for x in left_t if x)}")

n_ok = sum(1 for _, ok, _ in results if ok)
print(f"{n_ok}/{len(results)} passed")
sys.exit(0 if n_ok == len(results) else 1)
