"""Address textarea mapping regression lock.

The FEMIS portal requires two free-text address textareas at Finish —
`address` (permanent) and `present_address` (present) — whenever the
address family type is Other. field_mapping.yaml had no entry for either,
so the bot never filled them and every address_type=Other student failed
with "address: Please fill out this field.; present_address: Please fill
out this field." (jobs 45/50/51/55/57 — even Manahil Nadeem, whose PA
record was otherwise clean).

Two user-approved layers lock the fix:
  1. yaml entries: address <- source address (address_temporary section),
     present_address <- source present_address_other (address_permanent
     section, present-side family), both type text / required;
  2. PORTAL_NAME_ALIASES maps present_address_other -> present_address
     (the snapshot key is the PA DB column; the portal input is named
     present_address).

No network, no browser: _fill_field runs against a fake page with the
text helpers stubbed.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from src.form_filler import FormFiller, PORTAL_NAME_ALIASES  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" - {detail}" if detail else ""))


with open(ROOT / "config" / "field_mapping.yaml", encoding="utf-8") as fh:
    mapping = yaml.safe_load(fh)

tab1 = mapping.get("tab_1_personal_details") or {}
temp = tab1.get("address_temporary") or {}
perm = tab1.get("address_permanent") or {}

addr = temp.get("address") or {}
check("1 yaml: address entry in address_temporary",
      addr.get("type") == "text" and addr.get("source_field") == "address"
      and addr.get("required") is True, str(addr))

check("2 yaml: address fills AFTER address_type is set",
      list(temp).index("address") > list(temp).index("address_type"))

paddr = perm.get("present_address") or {}
check("3 yaml: present_address entry in address_permanent",
      paddr.get("type") == "text"
      and paddr.get("source_field") == "present_address_other"
      and paddr.get("required") is True, str(paddr))

check("4 yaml: present_address fills in the same pass as the present family",
      list(perm).index("present_address") > list(perm).index("street_number"))

check("5 alias present_address_other -> present_address",
      PORTAL_NAME_ALIASES.get("present_address_other") == "present_address")


class FakePage:
    async def evaluate(self, *args, **kwargs):
        return True


def fill_text(field_name, config, data):
    """Run _fill_field for a text field; return (calls, warned)."""
    ff = FormFiller()
    calls = []
    warned = []

    async def fake_fill_text(page, label, value, portal_name=""):
        calls.append((label, value, portal_name))

    async def fake_verify(page, label, portal_name, expected):
        return None

    ff._fill_text = fake_fill_text
    ff._verify_filled = fake_verify

    orig_warning = ff._fill_field.__globals__["logger"].warning

    def capture_warning(msg, *a, **k):
        warned.append(str(msg))

    ff._fill_field.__globals__["logger"].warning = capture_warning
    try:
        asyncio.run(ff._fill_field(FakePage(), field_name, config, data))
    finally:
        ff._fill_field.__globals__["logger"].warning = orig_warning
    return calls, warned


ff = FormFiller()
check("6 _portal_name resolves PA column to portal textarea",
      ff._portal_name({"source_field": "present_address_other"}) == "present_address")
check("7 _portal_name passes address through unchanged",
      ff._portal_name({"source_field": "address"}) == "address")

calls, warned = fill_text("address", addr, {"address": "PESHAWAR ROAD NASEERABAD"})
check("8 address fills portal textarea named 'address'",
      calls == [("Address", "PESHAWAR ROAD NASEERABAD", "address")], f"calls={calls}")

calls, warned = fill_text("present_address", paddr,
                          {"present_address_other": "HOUSE 12 G-11"})
check("9 present_address fills portal textarea named 'present_address'",
      calls == [("Present Address", "HOUSE 12 G-11", "present_address")],
      f"calls={calls}")

calls, warned = fill_text("address", addr, {"address": "  "})
check("10 empty address warns Missing required and fills nothing",
      calls == [] and any("Missing required: Address" in m for m in warned),
      f"calls={calls} warned={warned[:2]}")

calls, warned = fill_text("present_address", paddr, {})
check("11 empty present_address warns Missing required and fills nothing",
      calls == [] and any("Missing required: Present Address" in m for m in warned),
      f"calls={calls} warned={warned[:2]}")

failed = [n for n, ok in results if not ok]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
