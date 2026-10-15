"""Second-attempt address cascade regression lock (FEMIS portal fill).

Attempt 2 re-opens a record the portal already prefilled.  Selecting an
already-selected option dispatches no change event, so FEMIS's sub-sector
loader never runs: the Sub Sector select stays empty (portal value reads ""
because no matching option exists), the bot's option wait times out, and the
portal rejects the save.  The observed manual workaround is exactly the user
report: re-select Address Type, re-select Sector - then the Sub Sector field
loads.

Locks the fix in src/form_filler.py:
  - ADDRESS_CASCADE_PARENTS maps both sub-sector selects to their parents;
  - _fill_dropdown re-fires the chain via _retrigger_address_cascade when
    the plain option wait is exhausted (covers tab fill, repair pass and
    pre-submit re-fill - all route through _fill_dropdown);
  - the dispatch fires Address Type BEFORE Sector, with change re-fire
    (pass 1) then value toggle (pass 2), restoring captured values.

No network, no browser: behavioral checks use fake page/selector objects
with the option wait stubbed.
"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.form_filler import ADDRESS_CASCADE_PARENTS, FormFiller  # noqa: E402
from src import form_filler as ffmod  # noqa: E402

SRC = (ROOT / "src" / "form_filler.py").read_text(encoding="utf-8")
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" - {detail}" if detail else ""))


def method_body(src, start_pat, end_pat):
    m = re.search(start_pat, src)
    if not m:
        return ""
    rest = src[m.start():]
    e = re.search(end_pat, rest[len(m.group(0)):])
    return rest[:e.start() + len(m.group(0))] if e else rest


# --- 1. parents map -------------------------------------------------------
check("1 parents map: temp sub-sector -> (address_type, sector_id)",
      ADDRESS_CASCADE_PARENTS.get("sub_sector_id") == ("address_type", "sector_id"),
      str(ADDRESS_CASCADE_PARENTS.get("sub_sector_id")))
check("2 parents map: present sub-sector -> (present_address_type, present_sector_id)",
      ADDRESS_CASCADE_PARENTS.get("present_sub_sector_id")
      == ("present_address_type", "present_sector_id"),
      str(ADDRESS_CASCADE_PARENTS.get("present_sub_sector_id")))
check("3 parents map: only sub-sector selects are mapped",
      set(ADDRESS_CASCADE_PARENTS) == {"sub_sector_id", "present_sub_sector_id"},
      str(set(ADDRESS_CASCADE_PARENTS)))

# --- 2. _fill_dropdown hook ------------------------------------------------
fill_dd = method_body(SRC, r"async def _fill_dropdown\(self", r"async def _fill_radio\(self")
hook_pos = fill_dd.find("_retrigger_address_cascade(page, portal_name, sel)")
wait_pos = fill_dd.find("if not await self._wait_options_loaded(sel):")
check("4 _fill_dropdown: cascade branch waits, then re-triggers",
      wait_pos != -1 and hook_pos != -1 and hook_pos > wait_pos,
      f"wait_pos={wait_pos} hook_pos={hook_pos}")
check("5 _fill_dropdown: sub-sector names still in cascade_names",
      all('"' + n + '"' in fill_dd for n in ("sub_sector_id", "present_sub_sector_id")))
check("6 _fill_dropdown: no leftover inline option loop (logic centralized)",
      "range(24)" not in fill_dd)

# --- 3. dispatch JS contract ----------------------------------------------
fire_body = method_body(SRC, r"async def _fire_cascade_change\(self",
                        r"async def _retrigger_address_cascade\(self")
type_pos = fire_body.find("fire(typeSel);")
sector_pos = fire_body.find("fire(sectorSel);")
check("7 dispatch: Address Type fires before Sector",
      type_pos != -1 and sector_pos != -1 and type_pos < sector_pos,
      f"type_pos={type_pos} sector_pos={sector_pos}")
check("8 dispatch: native change event + jQuery trigger",
      "new Event('change'" in fire_body and "jq(el).trigger('change')" in fire_body)
check("9 dispatch: pass 2 value-toggles sector and restores the value",
      "sectorSel.value = ''" in fire_body and "sectorSel.value = savedSector" in fire_body)
check("10 dispatch: address-type re-fire may not lose the sector value",
      "if (sectorSel.value !== savedSector)" in fire_body)

# --- 4. repair path rides the fix -----------------------------------------
repair_body = method_body(SRC, r"async def _repair_address_selects\(self",
                          r"async def submit_form\(self")
check("11 repair: empty sub-sector fills route through _fill_dropdown",
      'await self._fill_dropdown(page, label, str(value), [], name)' in repair_body)
check("12 repair: sub-sector pair present in checks list",
      '"sub_sector_id", "Sub Sector", "sub_sector_id"' in repair_body
      and '"present_sub_sector_id", "Sub Sector", "present_sub_sector_id"' in repair_body)


# --- 5. behavioral: _wait_options_loaded -----------------------------------
class FakeOptLoc:
    def __init__(self, owner):
        self.owner = owner

    async def count(self):
        if self.owner.error:
            raise RuntimeError("select gone")
        return self.owner.n


class FakeSel:
    def __init__(self, n=1, error=False):
        self.n = n
        self.error = error

    def locator(self, query):
        return FakeOptLoc(self)


class ScriptedPage:
    """evaluate(): records args; loads options on the call index in load_on."""

    def __init__(self, load_on=0, result=True):
        self.calls = []
        self.load_on = load_on
        self.result = result
        self.sel = None

    async def evaluate(self, js, arg):
        self.calls.append(list(arg))
        if self.load_on is not None and len(self.calls) - 1 == self.load_on and self.sel:
            self.sel.n = 2
        return self.result


ff = FormFiller()


async def run_wait_checks():
    check("13 wait: real options present -> True (no polling needed)",
          await ff._wait_options_loaded(FakeSel(n=2)))
    check("14 wait: select vanished -> False",
          not await ff._wait_options_loaded(FakeSel(n=1, error=True)))
    check("15 wait: exhausted attempts -> False",
          not await ff._wait_options_loaded(FakeSel(n=1), attempts=1))


async def run_retrigger_checks():
    # fast option wait: state-only, no sleeps
    async def fake_wait(sel, attempts=24):
        return getattr(sel, "n", 0) > 1

    orig_wait = ff._wait_options_loaded
    ff._wait_options_loaded = fake_wait
    warnings = []
    orig_warn = ffmod.logger.warning
    ffmod.logger.warning = lambda msg, *a, **k: warnings.append(str(msg))
    try:
        # 16 unmapped name never touches the page
        page = ScriptedPage()
        page.sel = FakeSel()
        ok = await ff._retrigger_address_cascade(page, "section_id", page.sel)
        check("16 retrigger: unmapped select -> False, zero dispatches",
              ok is False and page.calls == [], str(page.calls))

        # 17 pass 1 (change re-fire) loads options
        page = ScriptedPage(load_on=0)
        page.sel = FakeSel(n=1)
        ok = await ff._retrigger_address_cascade(page, "sub_sector_id", page.sel)
        check("17 retrigger: re-fire pass loads options (one dispatch, temp parents)",
              ok is True and page.calls == [["address_type", "sector_id", False]],
              str(page.calls))

        # 18 guard-on-change handler: only the value toggle (pass 2) loads
        page = ScriptedPage(load_on=1)
        page.sel = FakeSel(n=1)
        ok = await ff._retrigger_address_cascade(page, "sub_sector_id", page.sel)
        check("18 retrigger: escalates to value toggle when re-fire is ignored",
              ok is True and page.calls
              == [["address_type", "sector_id", False],
                  ["address_type", "sector_id", True]],
              str(page.calls))

        # 19 present side uses present parents
        page = ScriptedPage(load_on=0)
        page.sel = FakeSel(n=1)
        ok = await ff._retrigger_address_cascade(page, "present_sub_sector_id", page.sel)
        check("19 retrigger: present sub-sector fires present parents",
              ok is True and page.calls
              == [["present_address_type", "present_sector_id", False]],
              str(page.calls))

        # 20 options never load -> False + honest warning (both passes tried)
        page = ScriptedPage(load_on=None)
        page.sel = FakeSel(n=1)
        ok = await ff._retrigger_address_cascade(page, "sub_sector_id", page.sel)
        check("20 retrigger: still-empty after both passes -> False + warning",
              ok is False and len(page.calls) == 2
              and any("did not load options for sub_sector_id" in w for w in warnings),
              f"calls={len(page.calls)} warnings={warnings[:2]}")

        # 21 sector select empty (nothing to fire) -> False, no crash
        page = ScriptedPage(load_on=0, result=False)
        page.sel = FakeSel(n=1)
        ok = await ff._retrigger_address_cascade(page, "sub_sector_id", page.sel)
        check("21 retrigger: dispatch refused (empty sector) -> False",
              ok is False and len(page.calls) == 2, str(page.calls))
    finally:
        ff._wait_options_loaded = orig_wait
        ffmod.logger.warning = orig_warn


asyncio.run(run_wait_checks())
asyncio.run(run_retrigger_checks())

failed = [n for n, ok in results if not ok]
print(f"\n{'=' * 40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
