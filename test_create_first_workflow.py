"""Create-first workflow regression lock.

The bot must NEVER search the portal list by student name — two students can
share a name and an unverified edit would overwrite the wrong record. The
locked workflow (user decision 2026-09-30):

  1. attempt 1: open_form always opens CREATE (no list visit, no name search),
  2. only a portal 'already been taken' error triggers the CNIC page-scan:
     100 records/page, browser-find (Ctrl+F equivalent) for the B-Form
     digits on every page, page forward until the row appears,
  3. the found record's name decides: case/space match -> edit that record;
     any difference -> duplicate_conflict ('different name') and STOP,
     never editing it,
  4. CNIC on no page -> duplicate_conflict (original error) for a human,
  5. a set duplicate_conflict stops the fill, aborts the submit, and skips
     the submit call in the job worker.

Retry workflow (user directive 2026-09-30, attempt > 1): open_form searches
the portal list by CNIC FIRST instead of filling blindly — name match ->
"edit" (fill that record), name mismatch -> "conflict" (report the portal
holder's name, never fill), CNIC nowhere -> the attempt-1 create flow.
Attempt 1 stays exactly as locked above.

No network/browser: a scripted FakePage drives the flow.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.form_filler import CREATE_URL, LIST_URL, FormFiller  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" - {detail}" if detail else ""))


class FakeResp:
    status = 200


class FakeLoc:
    def __init__(self, spec):
        self.spec = spec

    @property
    def first(self):
        return self

    async def count(self):
        return int(self.spec.get("count", 0))

    async def is_visible(self):
        return bool(self.spec.get("visible", False))

    async def get_attribute(self, name):
        return self.spec.get("attrs", {}).get(name)

    async def click(self, **kwargs):
        cb = self.spec.get("on_click")
        if cb:
            cb()

    async def select_option(self, value):
        self.spec["selected"] = value

    async def input_value(self):
        return str(self.spec.get("value", ""))


class FakePage:
    """Scripted page: hit results per list page, portal name on edit."""

    def __init__(self, hits=None, portal_name="", length_present=True,
                 next_cls="", name_input=True, ui_error=""):
        self.hits = list(hits or [])
        self.idx = 0
        self.portal_name = portal_name
        self.length_present = length_present
        self.next_cls = next_cls
        self.name_input = name_input
        self.ui_error = ui_error
        self.visits = []
        self.clicked_next = 0
        self.selected_length = None

    async def goto(self, url, wait_until=None):
        self.visits.append(url)
        return FakeResp()

    def locator(self, sel):
        if "length" in sel and "select" in sel:
            self._len_loc = FakeLoc({"count": 1 if self.length_present else 0})
            return self._len_loc
        if "paginate_button.next" in sel or sel.endswith("button.next"):
            return FakeLoc({
                "count": 1, "visible": True,
                "attrs": {"class": self.next_cls},
                "on_click": self._next,
            })
        if sel in ('input[name="name"]', "#name", 'input[name="student_name"]'):
            return FakeLoc({"count": 1 if self.name_input else 0,
                            "value": self.portal_name})
        return FakeLoc({"count": 0})

    def _next(self):
        self.clicked_next += 1
        self.idx += 1

    async def evaluate(self, script, arg=None):
        if "window.find" in script:
            if self.idx < len(self.hits):
                return self.hits[self.idx]
            return None
        if "toast-body" in script:
            return self.ui_error
        return ""


def scan(page, ff=None, b_form="36302-1234567-1", name="Ammara Ehsan",
         tab=None):
    ff = ff or FormFiller()
    return ff, asyncio.run(ff._scan_list_by_cnic(
        page, {"b_form": b_form, "name": name}, tab=tab))


# 1. open_form is create-only
page = FakePage()
ff = FormFiller()
mode = asyncio.run(ff.open_form(page, {"name": "X", "b_form": "36302-1234567-1"}))
check("1 open_form returns create", mode == "create")
check("2 open_form visits ONLY the create URL",
      page.visits == [CREATE_URL], str(page.visits))
check("3 open_form never touches the list (no name search)",
      LIST_URL not in page.visits)

src = (ROOT / "src" / "form_filler.py").read_text(encoding="utf-8")


def method_body(name, next_name):
    s = src.index(name)
    e = src.index(next_name, s + 10)
    return src[s:e]


open_body = method_body("async def open_form", "async def _read_name_value")
check("4 open_form body has no list search / name search",
      "LIST_URL" not in open_body and "No portal match" not in open_body
      and "input[name='search']" not in open_body)

# 2. CNIC scan finds the row; same name -> edit
page = FakePage(hits=[{"href": "https://femis.fde.gov.pk/students/abc-123",
                       "rowText": "AMMARA EHSAN 36302-1234567-1",
                       "nameMatch": True}],
                portal_name="  ammara   ehsan ")
ff, out = scan(page)
check("5 scan: CNIC row + name match -> edit", out == "edit", out)
check("6 scan sets form_mode=edit", ff.form_mode == "edit")
check("7 scan opened the record's /edit URL",
      any(v.rstrip("/").endswith("/edit") for v in page.visits), str(page.visits))
check("8 scan set list length to 100/page",
      getattr(page, "_len_loc", None) is not None
      and page._len_loc.spec.get("selected") == "100",
      str(getattr(page, "_len_loc", None) and page._len_loc.spec))

# 3. CNIC found but DIFFERENT name -> conflict, left the record
page = FakePage(hits=[{"href": "https://femis.fde.gov.pk/students/def-456",
                       "rowText": "OTHER STUDENT 36302-1234567-1",
                       "nameMatch": False}],
                portal_name="OTHER STUDENT")
ff, out = scan(page, tab=3)
check("9 scan: name differs -> conflict", out == "conflict", out)
conf = ff.duplicate_conflict or {}
check("10 conflict reason is cnic_name_mismatch",
      conf.get("reason") == "cnic_name_mismatch", str(conf))
check("11 conflict error names the CNIC + portal holder",
      any("3630212345671" in str(e) and "OTHER STUDENT" in str(e)
          for e in conf.get("errors") or []), str(conf.get("errors")))
check("12 conflict carries the tab", conf.get("tab") == 3, str(conf.get("tab")))
check("13 scan LEFT the wrong record (create URL visited after)",
      page.visits[-1] == CREATE_URL, str(page.visits))

# 3b. name unreadable on the record -> conflict (never guess)
page = FakePage(hits=[{"href": "https://femis.fde.gov.pk/students/ghi-789",
                       "rowText": "36302-1234567-1", "nameMatch": False}],
                name_input=False)
ff, out = scan(page)
check("14 scan: unreadable name -> conflict, not edit",
      out == "conflict" and ff.form_mode == "create", out)

# 4. CNIC nowhere: next disabled on page 1 -> notfound (recover sets conflict)
page = FakePage(hits=[None], next_cls="disabled")
ff, out = scan(page)
check("15 scan: CNIC absent and no next page -> notfound", out == "notfound", out)
check("16 no page-forward when next is disabled", page.clicked_next == 0,
      str(page.clicked_next))
check("17 scan alone leaves conflict unset (recover sets it)",
      ff.duplicate_conflict is None)

page = FakePage(hits=[None,
                      {"href": "https://femis.fde.gov.pk/students/jkl-012",
                       "rowText": "AMMARA EHSAN", "nameMatch": True}],
                portal_name="AMMARA EHSAN")
ff, out = scan(page)
check("18 scan finds the CNIC on page 2", out == "edit", out)
check("19 exactly one page-forward happened", page.clicked_next == 1,
      str(page.clicked_next))

# 5. _recover_duplicate behaviors
ff = FormFiller()
ff._last_api = [{"status": 422, "body": "b_form already been taken"}]
called = []

async def fake_scan(page, student_data, tab=None):
    called.append(tab)
    return "edit"

ff._scan_list_by_cnic = fake_scan
ok = asyncio.run(ff._recover_duplicate(FakePage(), {"b_form": "36302-1234567-1",
                                                    "name": "X"}, tab=2))
check("20 recover: scan->edit returns True", ok is True)
check("21 recover passes the tab through", called == [2], str(called))
check("22 recover: no conflict on success", ff.duplicate_conflict is None)

ff = FormFiller()
ff._last_api = [{"status": 422, "body": "b_form already been taken"}]
called2 = []

async def fake_scan2(page, student_data, tab=None):
    called2.append(1)
    return "notfound"

ff._scan_list_by_cnic = fake_scan2
ok = asyncio.run(ff._recover_duplicate(FakePage(), {"b_form": "36302-1234567-1",
                                                    "name": "X"}))
conf = ff.duplicate_conflict or {}
check("23 recover: scan->notfound returns False", ok is False)
check("24 recover sets cnic_not_found conflict with errors",
      conf.get("reason") == "cnic_not_found" and conf.get("errors"),
      str(conf))

ff = FormFiller()
called3 = []

async def fake_scan3(page, student_data, tab=None):
    called3.append(1)
    return "edit"

ff._scan_list_by_cnic = fake_scan3
ok = asyncio.run(ff._recover_duplicate(FakePage(), {"b_form": "36302-1234567-1",
                                                    "name": "X"}))
check("25 recover: no duplicate signal -> no scan, no edit",
      ok is False and not called3 and ff.duplicate_conflict is None)

ff = FormFiller()
ff._last_api = [{"status": 422, "body": "b_form already been taken"}]
page = FakePage()
ok = asyncio.run(ff._recover_duplicate(page, {"b_form": "", "name": "X"}))
check("26 recover: empty B-Form -> conflict WITHOUT leaving create",
      ok is False and ff.duplicate_conflict is not None and page.visits == [],
      f"visits={page.visits} conf={ff.duplicate_conflict}")

# 6. static locks: conflict stops fill / submit / worker
fill_body = method_body("async def fill_student_form", "@staticmethod")
check("27 fill loop breaks on duplicate_conflict",
      "if self.duplicate_conflict:" in fill_body and "break" in fill_body)
check("28 still_dup never overwrites a richer conflict",
      "if still_dup and self.duplicate_conflict is None:" in fill_body)
submit_body = method_body("async def submit_form", "async def _capture_ui_error")
check("29 submit aborts on unresolved conflict",
      "elif self.duplicate_conflict:" in submit_body
      and "aborting submit" in submit_body)
recover_body = method_body("async def _recover_duplicate", "async def _notify_progress")
check("30 recover no longer calls open_form (name search gone)",
      "self.open_form" not in recover_body)
scan_body = method_body("async def _scan_list_by_cnic", "async def _recover_duplicate")
check("31 scan uses browser-find (Ctrl+F) per page", "window.find(digits)" in scan_body)
check("32 scan never opens /create rows", "href.includes('/create')" in scan_body)
check("33 scan sets 100 records/page", 'select_option("100")' in scan_body)
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
check("34 worker skips submit when conflict set",
      "if self.filler.duplicate_conflict:" in main_src
      and "skipping submit" in main_src)

# 7. attempt-aware workflow (user directive 2026-09-30): attempt > 1
#    pre-scans the list by CNIC before any fill; attempt 1 is unchanged.
page = FakePage(hits=[{"href": "https://femis.fde.gov.pk/students/abc-123",
                       "rowText": "AMMARA EHSAN 36302-1234567-1",
                       "nameMatch": True}],
                portal_name="  ammara   ehsan ")
ff = FormFiller()
mode = asyncio.run(ff.open_form(
    page, {"name": "Ammara Ehsan", "b_form": "36302-1234567-1"}, attempt=2))
check("35 attempt>1: CNIC found + name match -> edit", mode == "edit", mode)
check("36 attempt>1 edit: form_mode set for the fill probe",
      ff.form_mode == "edit")
check("37 attempt>1 edit: list visited first, create never opened",
      bool(page.visits) and page.visits[0] == LIST_URL
      and CREATE_URL not in page.visits, str(page.visits))

page = FakePage(hits=[{"href": "https://femis.fde.gov.pk/students/def-456",
                       "rowText": "OTHER STUDENT 36302-1234567-1",
                       "nameMatch": False}],
                portal_name="OTHER STUDENT")
ff = FormFiller()
mode = asyncio.run(ff.open_form(
    page, {"name": "Ammara Ehsan", "b_form": "36302-1234567-1"}, attempt=3))
conf = ff.duplicate_conflict or {}
check("38 attempt>1: name mismatch -> conflict (no fill)",
      mode == "conflict", mode)
check("39 conflict reports the student holding the CNIC",
      any("OTHER STUDENT" in str(e) for e in conf.get("errors") or []),
      str(conf.get("errors")))
check("40 conflict reason cnic_name_mismatch",
      conf.get("reason") == "cnic_name_mismatch", str(conf.get("reason")))

page = FakePage(hits=[None], next_cls="disabled")
ff = FormFiller()
mode = asyncio.run(ff.open_form(
    page, {"name": "Ammara Ehsan", "b_form": "36302-1234567-1"}, attempt=2))
check("41 attempt>1: CNIC nowhere -> create-first fallback",
      mode == "create" and bool(page.visits) and page.visits[-1] == CREATE_URL,
      str(page.visits))

page = FakePage()
ff = FormFiller()
mode = asyncio.run(ff.open_form(
    page, {"name": "Ammara Ehsan", "b_form": "36302-1234567-1"}, attempt=1))
check("42 attempt 1: unchanged create-first (no list visit)",
      mode == "create" and page.visits == [CREATE_URL], str(page.visits))

jr_src = (ROOT / "src" / "job_runner.py").read_text(encoding="utf-8")
check("43 runner stamps attempt_number onto the student payload",
      'student["_attempt_number"] = int(job.get("attempt_number") or 1)'
      in jr_src)
check("44 worker passes the attempt into open_form and stops on conflict",
      "open_form(page, student, attempt=attempt)" in main_src
      and 'if mode == "conflict":' in main_src)
worker_region = main_src[main_src.index("async def worker"):]
check("45 conflict return happens BEFORE the fill",
      worker_region.index('if mode == "conflict":')
      < worker_region.index("await self.filler.fill_student_form(page, student)"))

failed = [n for n, ok in results if not ok]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
