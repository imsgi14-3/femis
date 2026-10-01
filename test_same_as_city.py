"""Same-as-temporary city rule (user directive: not allowed when City is
other than Islamabad).

Locks the two enforcement surfaces plus the wiring that keeps the probe from
aborting on a skipped checkbox:

  Bot side  - src/form_filler.py _fill_checkbox must honor the portal's
              disabled state (a force-click on a disabled box is a no-op), log
              an honest skip + DATA CONFLICT when PA still says 1, verify the
              click took, and _fill_field must propagate a non-"filled" status
              instead of emitting a false OK line.
  PA side   - femis-web/static/form.js must disable + auto-uncheck
              #same_as_temporary whenever [name="city_id"] is a non-empty
              value other than Islamabad (FEMIS renders the checkbox disabled
              in that case, so data entry must not allow the selection).
  Fill order- address_permanent fills City before the checkbox so the portal
              has already disabled the control when the bot reaches it.
  Probe     - a disabled skip returns "skipped" (never "failed"), so refresh
              can never abort a run on this rule.

Run: python test_same_as_city.py
"""
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import src.form_filler as ffm  # noqa: E402
from src.form_filler import FormFiller  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    status = "ok" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail and not ok:
        line += f" -- {detail}"
    print(line)


ff_src = (ROOT / "src" / "form_filler.py").read_text(encoding="utf-8")


def method_body(name, next_name):
    s = ff_src.index(name)
    e = ff_src.index(next_name, s + 10)
    return ff_src[s:e]


cb_src = method_body("async def _fill_checkbox", "async def _find_label")
field_src = method_body("async def _fill_field", "async def _verify_filled")

# ------------------------------------------------------------------
# A. Source locks on the bot side
# ------------------------------------------------------------------
check("A1 _fill_checkbox returns a tri-state status",
      "async def _fill_checkbox" in cb_src and "-> str:" in cb_src)
check("A2 disabled guard reads the control state",
      "await cb.is_disabled()" in cb_src and "if disabled:" in cb_src)
check("A3 disabled + PA wants it checked -> DATA CONFLICT, honest skip",
      "DATA CONFLICT" in cb_src
      and "not allowed when City is not Islamabad" in cb_src
      and 'return "skipped"' in cb_src)
check("A4 checkbox-not-found skips honestly (no silent OK)",
      "Skip (checkbox not found)" in cb_src and 'return "skipped"' in cb_src)
check("A5 state already correct needs no click",
      "if is_checked == should_check:" in cb_src)
check("A6 post-click verification catches a no-op click",
      "click did not take" in cb_src)
check("A7 _fill_field propagates a non-filled checkbox status",
      "status = await self._fill_checkbox" in field_src
      and 'if status != "filled":' in field_src
      and "return status" in field_src)
pos_status = field_src.index("status = await self._fill_checkbox")
pos_ok = field_src.index('logger.info(f"  OK:')
check("A8 the status check sits before the OK log (no false OK path)",
      pos_status < pos_ok, f"status@{pos_status} ok@{pos_ok}")

# Fill order: City before the checkbox inside the tab-1 address_permanent block
block_at = ff_src.index('if tab_number == 1 and section_name == "address_permanent"')
order_seg = ff_src[block_at:block_at + 700]
check("B1 fill order: City before Same as Temporary",
      '"city"' in order_seg and '"same_as_temporary"' in order_seg
      and order_seg.index('"city"') < order_seg.index('"same_as_temporary"'))

# ------------------------------------------------------------------
# C. Behavior drives against a fake portal box (real _fill_checkbox)
# ------------------------------------------------------------------
class Box:
    def __init__(self, checked=False, disabled=False, toggles=True):
        self.checked = checked
        self.disabled = disabled
        self.toggles = toggles
        self.clicks = 0


class FakePage:
    def __init__(self, box):
        self.box = box

    def locator(self, css):
        if self.box is None:
            return FakeLoc(self, "empty")
        if css == "label":
            return FakeLoc(self, "label")
        if "checkbox" in css:
            return FakeLoc(self, "box")
        return FakeLoc(self, "empty")

    async def evaluate(self, script, *args):
        return True


class FakeLoc:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind

    @property
    def first(self):
        return self

    def filter(self, **kw):
        return self

    def locator(self, sel):
        if self.page.box is None:
            return FakeLoc(self.page, "empty")
        if sel == "..":
            return self
        if "checkbox" in sel:
            return FakeLoc(self.page, "box")
        return FakeLoc(self.page, "empty")

    async def count(self):
        if self.kind == "box":
            return 1
        if self.kind == "label":
            return 1
        return 0

    async def is_checked(self):
        return self.page.box.checked

    async def is_disabled(self):
        return self.page.box.disabled

    async def click(self, force=False):
        self.page.box.clicks += 1
        if self.page.box.toggles:
            self.page.box.checked = not self.page.box.checked


records = []
handler = logging.Handler()
handler.emit = lambda r: records.append(r.getMessage())
ffm.logger.addHandler(handler)
old_level = ffm.logger.level
ffm.logger.setLevel(logging.DEBUG)

try:
    ff = FormFiller()

    # C1: enabled + unchecked + PA=1 -> click, checked, filled
    box = Box(checked=False, disabled=False)
    res = asyncio.run(ff._fill_checkbox(
        FakePage(box), "Same as Temporary Address", "1", "same_as_permanent_address"))
    check("C1 enabled box is clicked and filled",
          res == "filled" and box.checked and box.clicks == 1,
          f"res={res} checked={box.checked} clicks={box.clicks}")

    # C2: disabled (city != Islamabad) + PA=1 -> skip, no click, conflict logged
    records.clear()
    box = Box(checked=False, disabled=True)
    res = asyncio.run(ff._fill_checkbox(
        FakePage(box), "Same as Temporary Address", "1", "same_as_permanent_address"))
    check("C2 disabled + PA wants checked -> skipped, no click",
          res == "skipped" and box.clicks == 0 and not box.checked,
          f"res={res} clicks={box.clicks}")
    check("C3 the skip is logged as a DATA CONFLICT",
          any("DATA CONFLICT" in m for m in records), f"records={records[:3]}")

    # C4: state already matches -> filled without touching the control
    box = Box(checked=True, disabled=True)
    res = asyncio.run(ff._fill_checkbox(
        FakePage(box), "Same as Temporary Address", "1", "same_as_permanent_address"))
    check("C4 already-checked state needs no click (filled)",
          res == "filled" and box.clicks == 0, f"res={res} clicks={box.clicks}")

    # C5: disabled while checked + PA wants it off -> honest skip, no click
    records.clear()
    box = Box(checked=True, disabled=True)
    res = asyncio.run(ff._fill_checkbox(
        FakePage(box), "Same as Temporary Address", "0", "same_as_permanent_address"))
    check("C5 disabled box cannot be cleared -> skipped, no click",
          res == "skipped" and box.clicks == 0 and box.checked,
          f"res={res} clicks={box.clicks}")
    check("C6 the failed clear is logged",
          any("Could not clear" in m for m in records), f"records={records[:3]}")

    # C7: control not found -> skipped, never a silent success
    records.clear()
    res = asyncio.run(ff._fill_checkbox(
        FakePage(None), "Same as Temporary Address", "1", "same_as_permanent_address"))
    check("C7 missing checkbox -> skipped",
          res == "skipped", f"res={res}")

    # C8: click is a no-op -> post-verify reports it as skipped
    records.clear()
    box = Box(checked=False, disabled=False, toggles=False)
    res = asyncio.run(ff._fill_checkbox(
        FakePage(box), "Same as Temporary Address", "1", "same_as_permanent_address"))
    check("C8 no-op click detected by post-verify -> skipped",
          res == "skipped" and box.clicks == 1, f"res={res} clicks={box.clicks}")
    check("C9 the no-op click is logged",
          any("click did not take" in m for m in records), f"records={records[:3]}")

    # C10: desired off + already off -> filled (truthful state match)
    box = Box(checked=False, disabled=True)
    res = asyncio.run(ff._fill_checkbox(
        FakePage(box), "Same as Temporary Address", "0", "same_as_permanent_address"))
    check("C10 already-off box counts as filled (no OK-false-skip)",
          res == "filled" and box.clicks == 0, f"res={res}")

    # C11: full _fill_field drive - disabled skip must come back as skipped
    # (a false "filled" would emit the unconditional OK log line)
    cfg = {"type": "checkbox", "source_field": "same_address",
           "label": "Same as Temporary Address", "required": False}
    page = FakePage(Box(checked=False, disabled=True))
    res = asyncio.run(ff._fill_field(page, "same_as_temporary", cfg,
                                     {"same_address": "1"}, only_if_changed=False))
    check("C11 _fill_field: disabled same-as returns skipped (no false OK)",
          res == "skipped", f"res={res}")

    page = FakePage(Box(checked=False, disabled=False))
    res = asyncio.run(ff._fill_field(page, "same_as_temporary", cfg,
                                     {"same_address": "1"}, only_if_changed=False))
    check("C12 _fill_field: enabled same-as returns filled",
          res == "filled", f"res={res}")
finally:
    ffm.logger.removeHandler(handler)
    ffm.logger.setLevel(old_level)

# ------------------------------------------------------------------
# D. PA-side gating locks (femis-web/static/form.js)
# ------------------------------------------------------------------
js = (ROOT / "femis-web" / "static" / "form.js").read_text(encoding="utf-8")
check("E1 form.js gates #same_as_temporary on [name=city_id]",
      'getElementById("same_as_temporary")' in js
      and 'querySelector(\'[name="city_id"]\')' in js)
check("E2 the gate disables the checkbox when blocked",
      "cb.disabled = blocked" in js)
check("E3 blocked means a non-empty city other than Islamabad",
      'v.toLowerCase() !== "islamabad"' in js and 'var blocked = v !== ""' in js)
check("E4 a blocked change auto-unchecks + notifies listeners",
      "if (blocked && cb.checked)" in js and "cb.checked = false" in js)
check("E5 the gate re-runs on city change and on init",
      'city.addEventListener("change", enforceSameAsCityRule)' in js
      and "enforceSameAsCityRule();" in js)

# ------------------------------------------------------------------
# F. Mapping lock: same_as_temporary entry untouched
# ------------------------------------------------------------------
yml = (ROOT / "config" / "field_mapping.yaml").read_text(encoding="utf-8")
check("F1 mapping keeps the same_as_temporary checkbox entry",
      "    same_as_temporary:" in yml
      and "      label: Same as Temporary Address" in yml
      and "      source_field: same_address" in yml)
check("F2 mapping still feeds City from city_id (the gated control)",
      "    city:" in yml and "      source_field: city_id" in yml)

n_ok = sum(1 for _, ok in results if ok)
print(f"{n_ok}/{len(results)} passed")
sys.exit(0 if n_ok == len(results) else 1)
