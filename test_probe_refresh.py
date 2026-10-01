"""Edit-probe refresh: stale portal values are rewritten before the probe save.

Job 144 (Jannat noor): the admin fixed date_of_birth=2013-06-19 in PA at
19:08, the job claimed the fresh snapshot at 21:20 (student_data_version
matched updated_at exactly) - but the edit probe only checked VALIDITY,
not equality: "Probe tab 1: OK (already filled)" skipped tab 1 and FEMIS
kept the old DOB, so every save hit "date of admission cannot be earlier
than three years before the date of birth".

The probe now fills each tab with only_if_changed=True before its probe
save: _fill_field reads the control (READ_CURRENT_VALUE) and skips only
when _state_matches says the values are definitely equal (ambiguity ->
refill, the safe direction). Locks:
  A. _state_matches unit behavior (date/radio/checkbox/select/text/cnic);
  B. _fill_field(only_if_changed=True) skips a matching control, refills
     a stale one, and the default (False) path never reads the control;
  C. probe wiring: student_data + refresh BEFORE _save_next(probe=True),
     fill-loop calls stay full-fill, refresh failure aborts the probe on
     the current pane so the fill loop rewrites the tab.

Run: python test_probe_refresh.py   (exit 0 = all pass)
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.form_filler import FormFiller  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" - {detail}" if detail else ""))


M = FormFiller._state_matches

# ------------------------------------------------------------------
# A. _state_matches units
# ------------------------------------------------------------------
# dates - the Jannat noor job-144 case
check("A1 date mm/dd matches the desired ISO (skip)",
      M("date", {"kind": "input", "value": "06/19/2013"}, "2013-06-19") is True)
check("A2 stale portal DOB -> refill (the job-144 bug)",
      M("date", {"kind": "input", "value": "06/19/2013"}, "2012-05-10") is False)
check("A3 ISO portal value matches ISO desired",
      M("date", {"kind": "input", "value": "2013-06-19"}, "2013-06-19") is True)
check("A4 day-first-looking value (month part > 12) -> refill",
      M("date", {"kind": "input", "value": "19/06/2013"}, "2013-06-19") is False)
check("A5 empty portal date -> refill",
      M("date", {"kind": "input", "value": ""}, "2013-06-19") is False)
check("A6 non-padded mm/d still matches",
      M("date", {"kind": "input", "value": "6/19/2013"}, "2013-06-19") is True)

# text
check("B1 text: whitespace+case-insensitive match skips",
      M("text", {"kind": "input", "value": "FATIMA  KHAN"}, "Fatima Khan") is True)
check("B2 text: different value refills",
      M("text", {"kind": "input", "value": "OLD NAME"}, "NEW NAME") is False)
check("B3 cnic: formatted vs raw digits match",
      M("text", {"kind": "input", "value": "37405-6743320-6"},
        "3740567433206", {"validation": "cnic"}) is True)
check("B4 mobile: formatted vs raw digits match",
      M("text", {"kind": "input", "value": "0302-5194313"},
        "03025194313", {"validation": "mobile_pakistani"}) is True)
check("B5 unreadable state (None) -> refill",
      M("text", None, "anything") is False)
check("B6 cnic: different holder -> refill",
      M("text", {"kind": "input", "value": "11111-1111111-1"},
        "3740567433206", {"validation": "cnic"}) is False)

# dropdown
check("C1 dropdown: selected option text matches",
      M("dropdown", {"kind": "select", "value": "7", "text": "Class 7"},
        "Class 7") is True)
check("C2 dropdown: placeholder -> refill",
      M("dropdown", {"kind": "select", "value": "", "text": "Select"},
        "Class 7") is False)
check("C3 dropdown: value matches when option text differs",
      M("dropdown", {"kind": "select", "value": "Class 7", "text": "..."},
        "Class 7") is True)

# radio
check("D1 radio: checked value 1 == Yes",
      M("radio", {"kind": "radio", "value": "1", "label": "Yes"}, "Yes") is True)
check("D2 radio: wrong option -> refill",
      M("radio", {"kind": "radio", "value": "0", "label": "No"}, "Yes") is False)
check("D3 radio: nothing checked -> refill",
      M("radio", {"kind": "radio", "value": "", "label": ""}, "Yes") is False)
check("D4 radio: label match with opaque value",
      M("radio", {"kind": "radio", "value": "x9", "label": "Male"},
        "Male") is True)
check("D5 radio: No matches 0",
      M("radio", {"kind": "radio", "value": "0", "label": "No"}, "No") is True)

# checkbox
check("E1 checkbox: checked == Yes skips",
      M("checkbox", {"kind": "checkbox", "checked": True}, "Yes") is True)
check("E2 checkbox: checked but desired No -> refill",
      M("checkbox", {"kind": "checkbox", "checked": True}, "No") is False)
check("E3 checkbox: unchecked == No skips",
      M("checkbox", {"kind": "checkbox", "checked": False}, "No") is True)


# ------------------------------------------------------------------
# B. _fill_field drive against a fake page
# ------------------------------------------------------------------
class FakePage:
    def __init__(self, state):
        self.state = state
        self.evals = []

    async def evaluate(self, script, *args):
        s = str(script)
        self.evals.append(s)
        if "READ_CURRENT_VALUE" in s:
            return self.state
        if "getComputedStyle" in s:
            return True  # control visible on this tab
        return True


def fill_one(state, data, config, field_name, only_if_changed, spy_name):
    ff = FormFiller()
    calls = []

    async def spy(page, label, value, *a, **k):
        calls.append(value)

    async def fake_verify(page, label, portal_name, expected):
        return None

    setattr(ff, spy_name, spy)
    ff._verify_filled = fake_verify
    page = FakePage(state)
    res = asyncio.run(ff._fill_field(page, field_name, config, data,
                                     only_if_changed=only_if_changed))
    return res, calls, page


DOB_CFG = {"type": "date", "source_field": "date_of_birth",
           "label": "Date of Birth", "required": True}

res, calls, page = fill_one(
    {"kind": "input", "value": "06/19/2013"},
    {"date_of_birth": "2013-06-19"}, DOB_CFG, "date_of_birth", True, "_fill_date")
check("F1 matching date + only_if_changed -> skipped, no write",
      res == "skipped" and calls == [], f"res={res} calls={calls}")
check("F1b the reader (READ_CURRENT_VALUE) was used",
      any("READ_CURRENT_VALUE" in e for e in page.evals))

res, calls, page = fill_one(
    {"kind": "input", "value": "06/19/2013"},
    {"date_of_birth": "2012-05-10"}, DOB_CFG, "date_of_birth", True, "_fill_date")
check("F2 stale date + only_if_changed -> refilled",
      res == "filled" and calls == ["2012-05-10"], f"res={res} calls={calls}")

res, calls, page = fill_one(
    {"kind": "input", "value": "06/19/2013"},
    {"date_of_birth": "2013-06-19"}, DOB_CFG, "date_of_birth", False, "_fill_date")
check("F3 default path never reads the control (full-fill behavior)",
      res == "filled" and calls == ["2013-06-19"]
      and not any("READ_CURRENT_VALUE" in e for e in page.evals),
      f"res={res} evals={len(page.evals)}")

NAME_CFG = {"type": "text", "source_field": "mother_name",
            "label": "Mother Name"}
res, calls, page = fill_one(
    {"kind": "input", "value": "FATIMA KHAN"},
    {"mother_name": "Fatima Khan"}, NAME_CFG, "mother_name", True, "_fill_text")
check("F4 name compared AFTER the capitalization transform",
      res == "skipped" and calls == [], f"res={res} calls={calls}")

res, calls, page = fill_one(
    None, {"mother_name": "Fatima Khan"}, NAME_CFG, "mother_name", True, "_fill_text")
check("F5 unreadable control -> conservative refill (post-transform value)",
      res == "filled" and calls == ["FATIMA KHAN"], f"res={res} calls={calls}")


# ------------------------------------------------------------------
# C. Static wiring: probe refreshes before its save; fill loop full-fills
# ------------------------------------------------------------------
ff_src = (ROOT / "src" / "form_filler.py").read_text(encoding="utf-8")


def method_body(name, next_name):
    s = ff_src.index(name)
    e = ff_src.index(next_name, s + 10)
    return ff_src[s:e]


probe_src = method_body("async def _probe_incomplete_tab", "async def _save_next")
fill_src = method_body("async def fill_student_form", "@staticmethod")
field_src = method_body("async def _fill_field", "async def _verify_filled")
tabf_src = method_body("async def _fill_tab_fields", "def _portal_name")

save_at = probe_src.index("_save_next(page, i, probe=True)")
refresh_at = probe_src.index("only_if_changed=True")
check("G1 probe takes student_data and refreshes BEFORE its probe save",
      "student_data: dict | None = None" in probe_src and refresh_at < save_at)
check("G2 fill loop passes the snapshot into the probe",
      "_probe_incomplete_tab(page, student_data)" in fill_src)
check("G3 fill loop still full-fills every tab it reaches",
      "only_if_changed" not in fill_src
      and "_fill_tab_fields(page, i, student_data)" in fill_src)
check("G4 _fill_field exposes only_if_changed + the reader marker",
      "only_if_changed: bool = False" in field_src
      and "async def _read_control_state" in ff_src
      and "READ_CURRENT_VALUE" in ff_src)
check("G5 skip only on a definite match (conservative compare)",
      "if state is not None and self._state_matches" in field_src)
check("G6 refresh write failure aborts the probe BEFORE its save",
      "refresh write(s) failed" in probe_src
      and probe_src.index("refresh write(s) failed") < save_at)
check("G7 probe learns nothing on the refresh path (learn only on FAIL)",
      probe_src.count("_learn_unmapped_fields") == 1)
check("G8 _fill_tab_fields returns (filled, failed) counts",
      "return filled, failed" in tabf_src and "return 0, 0" in tabf_src)

n_ok = sum(1 for _, ok in results if ok)
print(f"{n_ok}/{len(results)} passed")
sys.exit(0 if n_ok == len(results) else 1)
