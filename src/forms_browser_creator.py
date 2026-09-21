import asyncio, yaml, sys, json
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIELD_MAP_PATH = Path(__file__).parent.parent / "config" / "field_mapping.yaml"
USER_DATA = str(Path.home() / "AppData" / "Local" / "FemisBot" / "chrome_profile")

SECTION_TITLES = {
    "tab_1_personal_details": "Personal Details",
    "tab_2_parents_guardian": "Parents / Guardian Information",
    "tab_3_educational_details": "Educational Details",
    "tab_4_emergency_contact": "Emergency Contact",
    "tab_5_idps_details": "IDPs Details",
    "tab_6_health_details": "Health Details",
    "tab_7_digital_access": "Digital Access",
}


def load_fields():
    with open(FIELD_MAP_PATH, "r", encoding="utf-8") as f:
        field_map = yaml.safe_load(f)
    sections = []
    for tab_key, title in SECTION_TITLES.items():
        if tab_key not in field_map:
            continue
        tab_data = field_map[tab_key]
        if isinstance(tab_data, dict) and tab_data.get("status") == "PENDING_PHASE_2":
            continue
        questions = []
        for group_name, group_fields in tab_data.items():
            if not isinstance(group_fields, dict):
                continue
            has_nested = any(isinstance(v, dict) and "label" in v for v in group_fields.values())
            if has_nested:
                for fn, fc in group_fields.items():
                    if isinstance(fc, dict) and "label" in fc:
                        questions.append(fc)
            elif "label" in group_fields:
                questions.append(group_fields)
        sections.append({"title": title, "questions": questions})
    return sections


async def main():
    sections = load_fields()
    total_q = sum(len(s["questions"]) for s in sections)
    print(f"Form: {len(sections)} sections, {total_q} questions\n", flush=True)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA,
            headless=False,
            slow_mo=50,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Create a NEW blank form
        print("Creating new blank form...", flush=True)
        await page.goto("https://docs.google.com/forms/create", wait_until="domcontentloaded", timeout=60000)

        # Wait for form editor to appear
        print("Waiting for form editor...", flush=True)
        for i in range(120):
            await asyncio.sleep(2)
            url = page.url
            try:
                has_add_q = await page.evaluate('() => !!document.querySelector(\'[data-tooltip="Add question"]\')')
                if has_add_q:
                    print(f"Form editor ready ({i*2}s)", flush=True)
                    break
            except:
                pass
            if i % 15 == 0 and i > 0:
                print(f"  waiting... ({i*2}s) {url[:60]}", flush=True)

        await asyncio.sleep(3)

        # Take screenshot to see state
        await page.screenshot(path="data/logs/new_form_start.png")
        print("Screenshot saved to data/logs/new_form_start.png", flush=True)

        # Get form URL
        form_url = page.url
        print(f"Form URL: {form_url}", flush=True)

        # === PHASE 1: Set title and description via JS ===
        print("\nSetting title...", flush=True)
        await page.evaluate('''() => {
            const el = document.querySelector('[aria-label="Form title"]');
            if (el) {
                el.focus();
                document.execCommand('selectAll');
                document.execCommand('insertText', false, 'FDE Student Admission Form');
            }
        }''')
        await asyncio.sleep(0.3)

        print("Setting description...", flush=True)
        await page.evaluate('''() => {
            const el = document.querySelector('[aria-label="Form description"]');
            if (el) {
                el.focus();
                document.execCommand('selectAll');
                document.execCommand('insertText', false, 'Federal Directorate of Education - Student data collection form');
            }
        }''')
        await asyncio.sleep(0.3)

        # === PHASE 2: Fill the first existing question, then add more ===
        print("\nCreating questions...", flush=True)

        q_num = 0

        for si, section in enumerate(sections):
            # Add section break (except first)
            if si > 0:
                await page.evaluate('''() => {
                    const btn = document.querySelector('[data-tooltip="Add section"]');
                    if (btn) btn.click();
                }''')
                await asyncio.sleep(0.8)
                # Title the section
                await page.evaluate(f'''() => {{
                    const els = document.querySelectorAll('[aria-label="Section title (optional)"]');
                    const last = els[els.length - 1];
                    if (last) {{
                        last.focus();
                        document.execCommand('selectAll');
                        document.execCommand('insertText', false, '{section["title"].replace("'", "\\'")}');
                    }}
                }}''')
                await asyncio.sleep(0.3)
                print(f"\nSection: {section['title']}", flush=True)

            for qi, q in enumerate(section["questions"]):
                label = q.get("label", f"Q{qi+1}")
                qtype = q.get("type", "text")
                required = q.get("required", False)
                options = q.get("options", [])

                # Add new question (skip first one which already exists)
                if q_num > 0:
                    await page.evaluate('''() => {
                        const btn = document.querySelector('[data-tooltip="Add question"]');
                        if (btn) btn.click();
                    }''')
                    await asyncio.sleep(0.4)

                # Fill question title — find the LAST question div
                escaped_label = label.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
                await page.evaluate(f'''() => {{
                    const els = document.querySelectorAll('[aria-label="Question"]');
                    const last = els[els.length - 1];
                    if (last) {{
                        last.focus();
                        document.execCommand('selectAll');
                        document.execCommand('insertText', false, "{escaped_label}");
                    }}
                }}''')
                await asyncio.sleep(0.15)

                # Set type
                if qtype in ("dropdown", "radio"):
                    # Click question type button
                    await page.evaluate('''() => {
                        const btns = document.querySelectorAll('[data-tooltip="Question types"]');
                        const last = btns[btns.length - 1];
                        if (last) last.click();
                    }''')
                    await asyncio.sleep(0.5)

                    target_type = "Dropdown" if qtype == "dropdown" else "Multiple choice"
                    await page.evaluate(f'''() => {{
                        const items = document.querySelectorAll('[role="option"], [data-value]');
                        for (const item of items) {{
                            if (item.textContent.trim().includes("{target_type}")) {{
                                item.click();
                                return true;
                            }}
                        }}
                        // Try divs inside menu
                        const divs = document.querySelectorAll('[role="listbox"] div, [role="menu"] div');
                        for (const d of divs) {{
                            if (d.textContent.trim().includes("{target_type}")) {{
                                d.click();
                                return true;
                            }}
                        }}
                        return false;
                    }}''')
                    await asyncio.sleep(0.3)

                    # Add options
                    if options:
                        for oi, opt in enumerate(options):
                            escaped_opt = opt.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
                            if oi > 0:
                                # Click "Add option"
                                await page.evaluate('''() => {
                                    const els = document.querySelectorAll('[aria-label="Add option"]');
                                    if (els.length > 0) els[els.length - 1].click();
                                }''')
                                await asyncio.sleep(0.2)

                            # Fill option value
                            await page.evaluate(f'''() => {{
                                const inputs = document.querySelectorAll('[aria-label="option value"]');
                                const last = inputs[inputs.length - 1];
                                if (last) {{
                                    last.focus();
                                    last.value = '';
                                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                    setter.call(last, "{escaped_opt}");
                                    last.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    last.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                }}
                            }}''')
                            await asyncio.sleep(0.1)

                # Required toggle
                if required:
                    await page.evaluate('''() => {
                        const toggles = document.querySelectorAll('[data-tooltip="Required"]');
                        const last = toggles[toggles.length - 1];
                        if (last) {
                            // Check if already on
                            const ariaChecked = last.querySelector('[aria-checked]');
                            if (ariaChecked && ariaChecked.getAttribute('aria-checked') === 'false') {
                                last.click();
                            } else if (!ariaChecked) {
                                last.click();
                            }
                        }
                    }''')
                    await asyncio.sleep(0.1)

                q_num += 1
                print(f"  [{q_num}] {label[:55]}", flush=True)

        print(f"\n{'='*60}", flush=True)
        print(f"DONE! {q_num} questions across {len(sections)} sections", flush=True)
        print(f"URL: {form_url}", flush=True)
        print(f"{'='*60}", flush=True)

        # Final screenshot
        await asyncio.sleep(1)
        await page.screenshot(path="data/logs/form_complete.png")
        print("Final screenshot saved.", flush=True)

        # Keep browser open for 5 min so user can review
        print("Browser stays open for 5 min. Close when done.", flush=True)
        await asyncio.sleep(300)
        await ctx.close()


asyncio.run(main())
