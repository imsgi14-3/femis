import asyncio
import yaml
from pathlib import Path
from playwright.async_api import Page
from src.utils.logger import setup_logger
from src.utils.validators import format_cnic, format_mobile

logger = setup_logger("form_filler")

FIELD_MAP_PATH = Path(__file__).parent.parent / "config" / "field_mapping.yaml"

TAB_IDS = [
    ("Personal Details", "tab-nav-personal"),
    ("Parents / Guardian", "tab-nav-parents"),
    ("Educational Details", "tab-nav-education"),
    ("Emergency Contact", "tab-nav-emergency"),
    ("IDPs Details", "tab-nav-idp"),
    ("Health Details", "tab-nav-health"),
    ("Digital Access", "tab-nav-digital"),
]


class FormFiller:
    """Fills the FEMIS SPA form by clicking tabs and filling fields by name/id."""

    def __init__(self):
        self.field_map = self._load_field_map()

    def _load_field_map(self) -> dict:
        with open(FIELD_MAP_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    async def fill_student_form(self, page: Page, student_data: dict) -> bool:
        logger.info(f"Filling form for: {student_data.get('student_name', 'Unknown')}")

        for i, (tab_name, tab_id) in enumerate(TAB_IDS, 1):
            logger.info(f"--- Tab {i}/7: {tab_name} ---")

            try:
                tab_loc = page.locator(f"#{tab_id}").first
                if await tab_loc.count() > 0:
                    await tab_loc.click(timeout=5000)
                else:
                    await page.get_by_role("tab", name=tab_name).click(timeout=5000)
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Tab click failed: {e}")
                continue

            await self._fill_tab_fields(page, i, student_data)

            try:
                save_btn = page.locator("button:has-text('Save & Next')").first
                if await save_btn.count() > 0 and i < 7:
                    await save_btn.click(timeout=5000)
                    await asyncio.sleep(1.5)
                    logger.info(f"  Saved tab {i}")
            except Exception as e:
                logger.warning(f"  Save & Next failed: {e}")

        logger.info("All tabs filled.")
        return True

    async def _fill_tab_fields(self, page: Page, tab_number: int, data: dict):
        tab_key = f"tab_{tab_number}_"
        tab_data = None
        for key in self.field_map:
            if key.startswith(tab_key):
                tab_data = self.field_map[key]
                break

        if not tab_data:
            return

        for section_name, section_fields in tab_data.items():
            if not isinstance(section_fields, dict) or "status" in section_fields:
                continue
            # Check if this is a section with nested fields, or a direct field config
            if "type" in section_fields:
                # Direct field config (flat structure)
                await self._fill_field(page, section_name, section_fields, data)
            else:
                # Nested section structure
                for field_name, config in section_fields.items():
                    if isinstance(config, dict) and "type" in config:
                        await self._fill_field(page, field_name, config, data)

    async def _fill_field(self, page: Page, field_name: str, config: dict, data: dict):
        source_field = config.get("source_field", field_name)
        value = data.get(source_field)

        if value is None or str(value).strip() == "":
            if config.get("required"):
                logger.warning(f"  Missing required: {config.get('label', field_name)}")
            return

        value = str(value).strip()
        field_type = config.get("type", "text")
        label = config.get("label", field_name)
        validation = config.get("validation")

        if validation and value:
            if validation == "cnic":
                value = format_cnic(value)
            elif validation == "mobile_pakistani":
                value = format_mobile(value)

        try:
            if field_type == "text":
                await self._fill_text(page, label, value)
            elif field_type == "dropdown":
                await self._fill_dropdown(page, label, value, config.get("options", []))
            elif field_type == "radio":
                await self._fill_radio(page, label, value)
            elif field_type == "date":
                await self._fill_date(page, label, value)
            elif field_type == "checkbox":
                await self._fill_checkbox(page, label, value)
            logger.info(f"  OK: {label} = {value[:50]}")
        except Exception as e:
            logger.error(f"  FAIL: {label}: {e}")

    async def _fill_text(self, page: Page, label: str, value: str):
        container = await self._find_label(page, label)
        inp = container.locator("..").locator("input[type='text'], input[type='number'], input[type='email'], input[type='tel'], input:not([type])").first
        if await inp.count() == 0:
            inp = container.locator("..").locator("input").first
        try:
            await inp.scroll_into_view_if_needed(timeout=3000)
            await inp.click(timeout=5000)
            await inp.fill("")
            await inp.fill(value)
        except Exception:
            # JS fallback for not-visible or non-editable elements
            name = await inp.get_attribute("name")
            if name:
                await page.evaluate("""(args) => {
                    const [name, val] = args;
                    const input = document.querySelector(`[name="${name}"]`);
                    if (input) {
                        const nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeSet.call(input, val);
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        input.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }""", [name, value])

    async def _fill_dropdown(self, page: Page, label: str, value: str, options: list):
        container = await self._find_label(page, label)
        sel = container.locator("..").locator("select").first
        if await sel.count() == 0:
            sel = page.locator("label").filter(has_text=label).locator("..").locator("select").first

        try:
            await sel.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass

        # 1. Try exact label match
        try:
            await sel.select_option(label=value, timeout=5000)
            return
        except Exception:
            pass

        # 2. Try value attribute match (DB may store portal IDs like "1" for Punjab)
        try:
            await sel.select_option(value=value, timeout=3000)
            return
        except Exception:
            pass

        # 3. Try truncated label
        try:
            await sel.select_option(label=value[:50], timeout=3000)
            return
        except Exception:
            pass

        # 4. Fuzzy match against options list
        matched = self._fuzzy_match(value, options)
        if matched:
            try:
                await sel.select_option(label=matched, timeout=3000)
                return
            except Exception:
                pass

        # 5. JS fallback — iterate all <option> elements
        name = None
        try:
            name = await sel.get_attribute("name") if await sel.count() > 0 else None
        except Exception:
            pass
        if not name:
            try:
                name = await page.evaluate("""(labelText) => {
                    const labels = document.querySelectorAll('label');
                    for (const lbl of labels) {
                        if (lbl.textContent.includes(labelText)) {
                            const parent = lbl.closest('.col-md-6, .form-group, div');
                            if (parent) {
                                const sel = parent.querySelector('select');
                                if (sel) return sel.name;
                            }
                        }
                    }
                    return null;
                }""", label[:30])
            except Exception:
                pass
        if name:
            try:
                await page.evaluate("""(args) => {
                    const [name, val] = args;
                    const sel = document.querySelector(`[name="${name}"]`);
                    if (sel) {
                        for (let opt of sel.options) {
                            if (opt.value === val || opt.text.includes(val) || val.includes(opt.text)) {
                                sel.value = opt.value;
                                sel.dispatchEvent(new Event('change', {bubbles: true}));
                                if (window.jQuery) { jQuery(sel).trigger('change'); }
                                break;
                            }
                        }
                    }
                }""", [name, matched or value])
                return
            except Exception:
                pass

        logger.warning(f"    No match for '{value}' in '{label}'")

    async def _fill_radio(self, page: Page, label: str, value: str):
        value_lower = value.lower()
        portal_value = "1" if value_lower in ("yes", "true") else "0" if value_lower in ("no", "false") else value

        container = await self._find_label(page, label)

        radio_by_val = container.locator("..").locator(f"input[type='radio'][value='{portal_value}']")
        if await radio_by_val.count() > 0:
            try:
                await radio_by_val.click(force=True, timeout=3000)
            except Exception:
                # JS fallback - click the label to trigger proper event chain
                name = await radio_by_val.get_attribute("name")
                rid = await radio_by_val.get_attribute("id")
                if name:
                    await page.evaluate("""(args) => {
                        const [name, val, id] = args;
                        // Try clicking the label first (triggers proper event chain)
                        const label = document.querySelector(`label[for="${id}"]`);
                        if (label) { label.click(); return; }
                        // Fallback: set checked and dispatch multiple events
                        const radio = document.querySelector(`input[type='radio'][name='${name}'][value='${val}']`);
                        if (radio) {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('click', {bubbles: true}));
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            radio.dispatchEvent(new Event('input', {bubbles: true}));
                            // jQuery fallback
                            if (window.jQuery) { jQuery(radio).trigger('click').trigger('change'); }
                        }
                    }""", [name, portal_value, rid or ""])
            return

        radio_by_label = container.locator("..").locator(f"label:has-text('{value}')")
        if await radio_by_label.count() > 0:
            await radio_by_label.click(force=True)
            return

        radio_by_text = page.locator(f"input[type='radio'][value='{portal_value}']").first
        if await radio_by_text.count() > 0:
            try:
                await radio_by_text.click(force=True, timeout=3000)
            except Exception:
                name = await radio_by_text.get_attribute("name")
                rid = await radio_by_text.get_attribute("id")
                if name:
                    await page.evaluate("""(args) => {
                        const [name, val, id] = args;
                        const label = document.querySelector(`label[for="${id}"]`);
                        if (label) { label.click(); return; }
                        const radio = document.querySelector(`input[type='radio'][name='${name}'][value='${val}']`);
                        if (radio) {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('click', {bubbles: true}));
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            radio.dispatchEvent(new Event('input', {bubbles: true}));
                            if (window.jQuery) { jQuery(radio).trigger('click').trigger('change'); }
                        }
                    }""", [name, portal_value, rid or ""])

    async def _fill_date(self, page: Page, label: str, value: str):
        container = await self._find_label(page, label)
        inp = container.locator("..").locator("input").first
        # Use JavaScript to set date value (handles readonly datepickers)
        await page.evaluate("""(args) => {
            const [val, name] = args;
            const input = document.querySelector(`input[name="${name}"]`) || document.querySelector('input[type="date"]');
            if (input) {
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(input, val);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                // For jQuery datepicker
                if (window.jQuery) { jQuery(input).val(val).trigger('change'); }
            }
        }""", [value, label.split(' ')[0].lower() if label else 'date'])

    async def _fill_checkbox(self, page: Page, label: str, value: str):
        container = await self._find_label(page, label)
        cb = container.locator("..").locator("input[type='checkbox']").first
        if await cb.count() == 0:
            cb = page.locator("label").filter(has_text=label).locator("..").locator("input[type='checkbox']").first

        is_checked = await cb.is_checked()
        should_check = value.lower() in ("yes", "true", "1", "on")
        if is_checked != should_check:
            await cb.click(force=True)

    async def _find_label(self, page: Page, label: str):
        """Find a label element, handling apostrophes and special characters."""
        # Use locator filter which handles special characters properly
        loc = page.locator("label").filter(has_text=label).first
        if await loc.count() > 0:
            return loc
        # Fallback: truncated label
        return page.locator("label").filter(has_text=label[:30]).first

    def _fuzzy_match(self, value: str, options: list) -> str | None:
        if not options:
            return None
        vl = value.lower()
        for opt in options:
            if vl == opt.lower():
                return opt
        for opt in options:
            if vl in opt.lower() or opt.lower() in vl:
                return opt
        return None
