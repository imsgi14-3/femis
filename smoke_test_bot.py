"""Bot-side smoke test: FormFiller date normalizer (split from smoke_test.py so the portal test does not import src.*)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.form_filler import FormFiller  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


ff = FormFiller()
check("date 15/03/2010 -> 2010-03-15", ff._normalize_date("15/03/2010") == "2010-03-15")
check("date 2010-03-15 unchanged", ff._normalize_date("2010-03-15") == "2010-03-15")
check("date 15/03/10 -> 2010-03-15", ff._normalize_date("15/03/10") == "2010-03-15")

failed = [r for r in results if not r[1]]
print(f"\n{'='*40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
