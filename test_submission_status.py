"""Phase 2 regression: FILL_SUCCESS vs SUBMISSION_SUCCESS report semantics."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.main import (  # noqa: E402
    STATUS_SUCCESS,
    STATUS_FILL_SUCCESS,
    STATUS_SUBMIT_FAILED,
    STATUS_ERROR,
    classify_student_result,
)
from src.form_filler import is_submission_success  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


# --- fill succeeds, Finish never requested -> FILL_SUCCESS, never final success ---
s = classify_student_result(submit_requested=False, submitted=None)
check("fill-only -> fill_success", s == STATUS_FILL_SUCCESS, s)
check("fill-only is NOT final success", s != STATUS_SUCCESS and s != "success", s)

# --- fill succeeds but Finish not completed -> NOT final success ---
s = classify_student_result(submit_requested=True, submitted=False)
check("Finish not completed -> submit_failed", s == STATUS_SUBMIT_FAILED, s)
check("Finish not completed is NOT final success", s != STATUS_SUCCESS, s)

# --- Finish completed/detected -> final success ---
s = classify_student_result(submit_requested=True, submitted=True)
check("Finish completed -> success", s == STATUS_SUCCESS, s)

# --- validation/network failure -> NOT final success ---
s = classify_student_result(submit_requested=True, submitted=None, error="validation blocked")
check("failure -> error", s == STATUS_ERROR, s)
check("failure is NOT final success", s != STATUS_SUCCESS, s)
s = classify_student_result(submit_requested=False, submitted=None, error="network down")
check("fill-only failure -> error (not fill_success)", s == STATUS_ERROR, s)

# --- submission decision: Finish click AND completion indicator both required ---
check(
    "indicator WITHOUT Finish click is NOT success",
    is_submission_success(False, True) is False,
)
check(
    "Finish clicked but NO indicator is NOT success",
    is_submission_success(True, False) is False,
)
check(
    "no Finish + no indicator is NOT success",
    is_submission_success(False, False) is False,
)
check(
    "Finish clicked + indicator detected IS final success",
    is_submission_success(True, True) is True,
)

failed = [r for r in results if not r[1]]
print(f"\n{'='*40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
