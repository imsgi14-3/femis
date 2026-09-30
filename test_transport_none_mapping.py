"""Transport 'None' -> FEMIS mapping regression lock.

PA's form offers transport = Institution Bus | Private | None, but the FEMIS
portal has no 'None' radio. Before this fix the filler sent 'None' verbatim
(no radio found), the repair scan then force-checked the FIRST radio
(Institution Bus), the portal demanded bus_route, and every 'None' student
(35 of 49) failed with the bus_route trap (jobs 41/43 today).

Two user-approved layers now lock the behavior:
  1. FormFiller._fill_field maps PA 'None' -> 'Private' (and keeps the
     bus_route => Institution Bus default for blank transport),
  2. _fill_default_required never defaults the transport_facility radio
     group (no first-radio guess => honest failure instead of the trap).

No network, no browser: _fill_field runs against a fake page with the
radio helpers stubbed.
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


class FakePage:
    async def evaluate(self, *args, **kwargs):
        return True


def fill_transport(value, bus_route=None):
    """Run _fill_field for transport; return (radios_filled, warned_missing)."""
    ff = FormFiller()
    filled = []
    warned = []

    async def fake_radio(page, label, val, portal_name=""):
        filled.append((label, val, portal_name))

    async def fake_checked(page, name):
        return True

    ff._fill_radio = fake_radio
    ff._radio_checked = fake_checked

    orig_warning = ff._fill_field.__globals__["logger"].warning

    def capture_warning(msg, *a, **k):
        warned.append(str(msg))

    ff._fill_field.__globals__["logger"].warning = capture_warning
    try:
        data = {"transport_facility": value}
        if bus_route is not None:
            data["bus_route"] = bus_route
        config = {
            "source_field": "transport_facility",
            "label": "Transport Facility",
            "type": "radio",
            "required": True,
        }
        asyncio.run(ff._fill_field(FakePage(), "transport_facility", config, data))
    finally:
        ff._fill_field.__globals__["logger"].warning = orig_warning
    return filled, warned


f, w = fill_transport("None")
check("1 PA 'None' fills portal radio 'Private'",
      [(x[1]) for x in f] == ["Private"], f"filled={f}")

f, w = fill_transport(None, bus_route="TARNOL")
check("2 blank transport + bus_route still defaults to 'Institution Bus'",
      [(x[1]) for x in f] == ["Institution Bus"], f"filled={f}")

f, w = fill_transport("Private")
check("3 'Private' passes through unchanged",
      [(x[1]) for x in f] == ["Private"], f"filled={f}")

f, w = fill_transport("Institution Bus", bus_route="TARNOL")
check("4 'Institution Bus' passes through unchanged",
      [(x[1]) for x in f] == ["Institution Bus"], f"filled={f}")

f, w = fill_transport("none")
check("5 case-insensitive 'none' also maps to 'Private'",
      [(x[1]) for x in f] == ["Private"], f"filled={f}")

f, w = fill_transport(None)
check("6 blank transport with no route fills nothing (honest miss)",
      f == [] and any("Missing required: Transport Facility" in m for m in w),
      f"filled={f} warned={w[:2]}")

src = (ROOT / "src" / "form_filler.py").read_text(encoding="utf-8")
start = src.index("async def _fill_default_required")
end = src.index("\n    async def ", start + 10)
body = src[start:end]
check("7 repair scan skips transport_facility group",
      "if (name === 'transport_facility') return;" in body)
check("8 repair scan still defaults OTHER empty radios",
      "target.checked = true;" in body)
fs = src.index("async def _fill_field")
fe = src.index("async def _verify_filled")
fbody = src[fs:fe]
check("9 None->Private mapping lives in _fill_field",
      'str(value).strip().lower() == "none"' in fbody
      and 'value = "Private"' in fbody)

failed = [n for n, ok in results if not ok]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
