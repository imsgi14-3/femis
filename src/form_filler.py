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
            for field_name, config in section_fields.items():
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
        container = page.locator(f"label:has-text('{label}')").first
        if await container.count() == 0:
            container = page.locator(f"label:has-text('{label[:30]}')").first
        inp = container.locator("..").locator("input[type='text'], input[type='number'], input[type='email'], input[type='tel'], input:not([type])").first
        if await inp.count() == 0:
            inp = container.locator("..").locator("input").first
        await inp.click()
        await inp.fill("")
        await inp.fill(value)

    async def _fill_dropdown(self, page: Page, label: str, value: str, options: list):
        container = page.locator(f"label:has-text('{label}')").first
        if await container.count() == 0:
            container = page.locator(f"label:has-text('{label[:30]}')").first
        sel = container.locator("..").locator("select").first
        if await sel.count() == 0:
            sel = page.locator(f"label:has-text('{label}') ~ select").first

        try:
            await sel.select_option(label=value, timeout=3000)
        except Exception:
            try:
                await sel.select_option(label=value[:50], timeout=3000)
            except Exception:
                matched = self._fuzzy_match(value, options)
                if matched:
                    await sel.select_option(label=matched, timeout=3000)
                else:
                    logger.warning(f"    No match for '{value}' in '{label}'")

    async def _fill_radio(self, page: Page, label: str, value: str):
        value_lower = value.lower()
        portal_value = "1" if value_lower in ("yes", "true") else "0" if value_lower in ("no", "false") else value

        container = page.locator(f"label:has-text('{label}')").first
        if await container.count() == 0:
            container = page.locator(f"label:has-text('{label[:30]}')").first

        radio_by_val = container.locator("..").locator(f"input[type='radio'][value='{portal_value}']")
        if await radio_by_val.count() > 0:
            await radio_by_val.click(force=True)
            return

        radio_by_label = container.locator("..").locator(f"label:has-text('{value}')")
        if await radio_by_label.count() > 0:
            await radio_by_label.click()
            return

        radio_by_text = page.locator(f"input[type='radio'][value='{portal_value}']").first
        if await radio_by_text.count() > 0:
            await radio_by_text.click(force=True)

    async def _fill_date(self, page: Page, label: str, value: str):
        container = page.locator(f"label:has-text('{label}')").first
        if await container.count() == 0:
            container = page.locator(f"label:has-text('{label[:30]}')").first
        inp = container.locator("..").locator("input").first
        await inp.click()
        await inp.fill("")
        await inp.fill(value)

    async def _fill_checkbox(self, page: Page, label: str, value: str):
        container = page.locator(f"label:has-text('{label}')").first
        if await container.count() == 0:
            container = page.locator(f"label:has-text('{label[:30]}')").first
        cb = container.locator("..").locator("input[type='checkbox']").first
        if await cb.count() == 0:
            cb = page.locator(f"label:has-text('{label}')").locator("..").locator("input[type='checkbox']").first

        is_checked = await cb.is_checked()
        should_check = value.lower() in ("yes", "true", "1", "on")
        if is_checked != should_check:
            await cb.click()

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
