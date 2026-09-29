"""Income PA->FEMIS mapping regression lock.

The bot once sent PA's legacy bracket label "Lessthan 50,000" to FEMIS while
the portal options read "Less than 50,000"; the select stayed empty, the save
stayed blocked, and jobs for Jannat/Hajra/Ayat/Abeera failed on tab 2.  Three
layers now prevent a recurrence and this suite locks all three:

  1. no live config/data file contains the typo'd label (docs/ history
     snapshots are immutable records of the old state and are exempt),
  2. the bot's dropdown mappings for father/mother/guardian income carry the
     exact five FDE brackets,
  3. FormFiller._fuzzy_match still repairs a legacy stored value to the
     correct option (and invents nothing for an unknown value),
  4. the PA portal's own selects (portal_options.json) agree with the bot's
     mappings - PA and bot must speak the same option text.

No database writes; reads only.
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.form_filler import FormFiller  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


EXPECTED = [
    "Less than 50,000",
    "50,001 - 100,000",
    "100,001 - 200,000",
    "200,001 - 300,000",
    "Above 300,000",
]

LIVE_SUFFIXES = {".yaml", ".yml", ".json", ".py", ".js"}


def lessthan_offenders(*dirs):
    bad = []
    for d in dirs:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in LIVE_SUFFIXES:
                try:
                    if "lessthan" in p.read_text(encoding="utf-8", errors="ignore").lower():
                        bad.append(str(p.relative_to(ROOT)))
                except OSError:
                    pass
    return bad


off_cfg = lessthan_offenders("config")
check("1 no 'Lessthan' typo anywhere under config/", not off_cfg, str(off_cfg))

off_web = lessthan_offenders("femis-web")
check("2 no 'Lessthan' typo anywhere under femis-web/", not off_web, str(off_web))

MAPPING = yaml.safe_load((ROOT / "config" / "field_mapping.yaml").read_text(encoding="utf-8"))
PORTAL = json.loads((ROOT / "femis-web" / "portal_options.json").read_text(encoding="utf-8"))


def mapping_entries(name, source_field=None, with_options=False):
    """Find a field spec anywhere in the mapping (tab -> section -> field)."""
    out = []

    def is_spec(node):
        return isinstance(node, dict) and (
            "source_field" in node or "options" in node or "label" in node
        )

    def walk(node, path):
        if not isinstance(node, dict):
            return
        for key, val in node.items():
            if is_spec(val):
                if key != name:
                    continue
                if source_field and val.get("source_field") != source_field:
                    continue
                if with_options and not val.get("options"):
                    continue
                out.append((" / ".join(path + [str(key)]), key, val))
            elif isinstance(val, dict):
                walk(val, path + [str(key)])

    walk(MAPPING, [])
    return out


def bracket_check(label, name, source_field):
    entries = mapping_entries(name, source_field, with_options=True)
    ok = len(entries) >= 1 and entries[0][2].get("options") == EXPECTED
    detail = (
        f"{[(t, f, s.get('type'), s.get('options')) for t, f, s in entries]}"
        if entries else "no options-bearing entry found"
    )
    check(label, ok, detail)
    return entries[0][2]["options"] if entries else None


father_opts = bracket_check(
    "3 father income_per_month dropdown = exact 5 FDE brackets",
    "income_per_month", "father_monthly_income")
mother_opts = bracket_check(
    "4 mother_income_per_month dropdown = exact 5 FDE brackets",
    "mother_income_per_month", "mother_monthly_income")
guardian_opts = bracket_check(
    "5 guardian_income dropdown = exact 5 FDE brackets",
    "guardian_income", "guardian_income")

ff = FormFiller()
check("6 legacy 'Lessthan 50,000' repairs to 'Less than 50,000'",
      ff._fuzzy_match("Lessthan 50,000", EXPECTED) == "Less than 50,000",
      str(ff._fuzzy_match("Lessthan 50,000", EXPECTED)))
check("7 exact bracket still matches verbatim",
      ff._fuzzy_match("Less than 50,000", EXPECTED) == "Less than 50,000"
      and ff._fuzzy_match("Above 300,000", EXPECTED) == "Above 300,000")
check("8 unknown value stays unmatched (nothing invented)",
      ff._fuzzy_match("999,999", EXPECTED) is None,
      str(ff._fuzzy_match("999,999", EXPECTED)))


def portal_check(label, key, bot_opts):
    portal_opts = PORTAL.get(key)
    ok = bot_opts is not None and portal_opts == bot_opts == EXPECTED
    check(label, ok, f"portal={portal_opts} bot={bot_opts}")


portal_check("9 portal father_income agrees with bot mapping", "father_income", father_opts)
portal_check("10 portal mother_income agrees with bot mapping", "mother_income", mother_opts)
portal_check("11 portal guardian_income agrees with bot mapping", "guardian_income", guardian_opts)

failed = [n for n, ok in results if not ok]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
