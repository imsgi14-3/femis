"""Admission-number conflicts route to human action required (user directive).

FEMIS whole-school records are invisible to our one-class PA database, so a
PA admission number can collide with a DIFFERENT FEMIS student (job 146:
IMTISAL KAMRAM held admission 2288 while the PA job submitted Khadija
haroon). FEMIS reports it as "Admission Number already exists for another
student. Please review the details : Name: IMTISAL KAMRAM, ...", which the
old matcher - only "already been taken" - missed: the fill loop never set
duplicate_conflict and classify fell through to the 3-item "Finish not
available" cap, masking the real error as an emergency-tab trio.

Locks (user directive: "this type error will go to human action require
category"):
  1. fill-loop still_dup matches BOTH duplicate phrasings -> the exact
     test_create_first guard strings + break stay (checks 27/28/29);
  2. the CNIC-scan gate still fires only for "already been taken" (the
     admission holder is another student - the scan cannot help);
  3. classify_submit_failure's fallback matches the admission phrasing even
     when buried after 3 other errors -> "Duplicate record conflict" (the
     server's auto-queue keys on that prefix to keep the job out of
     automatic runs until a human queues it);
  4. both modules carry the same DUP_ERROR_RE (keep-in-sync copies).

Run: python test_admission_conflict.py   (exit 0 = all pass)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.form_filler import DUP_ERROR_RE as FILL_DUP_RE  # noqa: E402
from src.job_runner import DUP_ERROR_RE as RUN_DUP_RE  # noqa: E402
from src.job_runner import classify_submit_failure  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" - {detail}" if detail else ""))


ADMISSION_MSG = (
    "x Error! Admission Number already exists for another student. Please "
    "review the details : Name: IMTISAL KAMRAM, Class: Class 7, "
    "B Form: 3740567433206"
)

ff_src = (ROOT / "src" / "form_filler.py").read_text(encoding="utf-8")
jr_src = (ROOT / "src" / "job_runner.py").read_text(encoding="utf-8")


def method_body(src, name, next_name):
    s = src.index(name)
    e = src.index(next_name, s + 10)
    return src[s:e]


fill_body = method_body(ff_src, "async def fill_student_form", "@staticmethod")

# ------------------------------------------------------------------
# 1. The shared regex matches both phrasings in BOTH modules
# ------------------------------------------------------------------
check("1 form_filler DUP_ERROR_RE matches both dup phrasings",
      bool(FILL_DUP_RE.search("already been taken"))
      and bool(FILL_DUP_RE.search(
          "Admission Number already exists for another student")))
check("2 job_runner DUP_ERROR_RE matches both dup phrasings",
      bool(RUN_DUP_RE.search("already been taken"))
      and bool(RUN_DUP_RE.search(
          "Admission Number already exists for another student")))
check("3 the two copies are literally in sync",
      FILL_DUP_RE.pattern == RUN_DUP_RE.pattern
      and FILL_DUP_RE.flags == RUN_DUP_RE.flags,
      FILL_DUP_RE.pattern)

# ------------------------------------------------------------------
# 2. Fill loop: still_dup uses the regex; locked guard strings intact
# ------------------------------------------------------------------
check("4 fill loop still_dup filters through DUP_ERROR_RE",
      "if DUP_ERROR_RE.search(str(e))" in fill_body)
check("5 fill loop keeps the test_create_first guard + break",
      "if still_dup and self.duplicate_conflict is None:" in fill_body
      and "if self.duplicate_conflict:" in fill_body
      and "break" in fill_body)
check("6 CNIC-scan gate still fires only for 'already been taken'",
      'any("already been taken" in e for e in dup_errs)' in fill_body)

# ------------------------------------------------------------------
# 3. Classify fallback
# ------------------------------------------------------------------
check("7 classify dup fallback scans through DUP_ERROR_RE",
      "DUP_ERROR_RE.search(e)" in jr_src
      and 'r"already been taken|already exists for another student"' in jr_src)

cat, msg = classify_submit_failure({
    "finish_clicked": False,
    "errors": ["Date of Admission: This field is required.",
               "Emergency Contact Person: This field is required.",
               "Contact Number: This field is required.",
               ADMISSION_MSG],
})
check("8 buried admission error -> Duplicate record conflict (not the 3-item cap)",
      cat == "validation" and msg.startswith("Duplicate record conflict")
      and "already exists for another student" in msg,
      f"{cat}: {msg[:140]}")

cat, msg = classify_submit_failure({
    "finish_clicked": False,
    "duplicate_conflict": {"tab": 3, "errors": [ADMISSION_MSG]},
    "errors": ["x Error! something else"],
})
check("9 fill-loop conflict dict (tab 3) -> full admission message",
      cat == "validation"
      and msg.startswith("Duplicate record conflict (tab 3):")
      and "IMTISAL KAMRAM" in msg and "3740567433206" in msg,
      msg[:160])
check("10 conflict detail stays within the approved 380-char cap",
      len(msg) <= len("Duplicate record conflict (tab 3): ") + 380,
      f"len={len(msg)}")

cat, msg = classify_submit_failure({
    "finish_clicked": False,
    "errors": ["B-Form has already been taken"],
})
check("11 classic 'already been taken' still routes to dup",
      cat == "validation" and msg.startswith("Duplicate record conflict"),
      msg[:100])

cat, msg = classify_submit_failure({
    "finish_clicked": False,
    "errors": ["Other Profession: Please fill out this field.",
               "Class is required"],
})
check("12 ordinary validation errors stay 'Finish not available'",
      msg.startswith("Finish not available:"), msg[:120])

n_ok = sum(1 for _, ok in results if ok)
print(f"{n_ok}/{len(results)} passed")
sys.exit(0 if n_ok == len(results) else 1)
