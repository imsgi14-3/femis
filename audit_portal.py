"""FEMIS Portal Form Auditor v2

INSTRUCTIONS FOR FUTURE AUDITS:
=================================
1. This script logs into FEMIS portal, navigates to Add Student form.
2. It clicks each of the 7 tab NAMES at the top of the form (not Save & Next).
3. For each tab, it:
   a. Clicks every interactive field (radio, select, checkbox) to trigger conditionals
   b. After each click, records which fields appeared/disappeared
   c. Expands every dropdown to capture all options
   d. Takes a full-page screenshot
4. It cross-audits against our web form and field_mapping.yaml.
5. If Gemini CAPTCHA fails, falls back to manual mode (write code to file).

CAPTCHA HANDLING:
- Auto: Gemini Vision reads the CAPTCHA image
- Manual: Script saves CAPTCHA to data/logs/captcha_current.png
  Write the 4-digit code to data/logs/captcha_code.txt

OUTPUT FILES:
- data/output/portal_audit_<timestamp>.json — full field inventory
- data/output/audit_discrepancies_<timestamp>.json — diff with our form
- data/logs/audit_tab_<N>_<name>_<timestamp>.png — screenshots

TAB NAVIGATION:
- Script clicks tab names at the top of the form directly.
- Does NOT use Save & Next. This avoids creating partial records.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

LOGIN_URL = "https://femis.fde.gov.pk/login"
CREATE_URL = "https://femis.fde.gov.pk/students/create"

# Tab names as they appear in the portal's top navigation.
# The script tries multiple strategies to click each tab.
TABS = [
    ("Personal Details", ["tab-nav-personal", "tab-personal"]),
    ("Parents / Guardian", ["tab-nav-parents", "tab-parents"]),
    ("Educational Details", ["tab-nav-education", "tab-education"]),
    ("Emergency Contact", ["tab-nav-emergency", "tab-emergency"]),
    ("IDPs Details", ["tab-nav-idps", "tab-idps"]),
    ("Health Details", ["tab-nav-health", "tab-health"]),
    ("Digital Access", ["tab-nav-digital", "tab-digital"]),
]


async def solve_captcha(page, max_retries=5):
    from google import genai
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    for attempt in range(1, max_retries + 1):
        print(f"  CAPTCHA attempt {attempt}/{max_retries} (model={model})...")
        captcha_img = page.locator(".captcha-code img")
        captcha_path = Path("data/logs") / f"captcha_{attempt}.png"
        captcha_path.parent.mkdir(parents=True, exist_ok=True)
        await captcha_img.screenshot(path=str(captcha_path))
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    "Read the 4-digit CAPTCHA code from this image. Return ONLY the 4 digits, nothing else.",
                    genai.types.Part.from_bytes(data=captcha_path.read_bytes(), mime_type="image/png"),
                ],
            )
            code = response.text.strip().replace(" ", "").replace("-", "")
            print(f"  Gemini reads: {code}")
        except Exception as e:
            print(f"  Gemini API error: {e}")
            await asyncio.sleep(2)
            continue
        if len(code) == 4 and code.isdigit():
            await page.fill("#captcha", code)
            await page.click("button[type='submit']")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)
            if "login" not in page.url.lower():
                print("  Login successful!")
                return True
            print("  Wrong CAPTCHA, refreshing...")
            await page.click("#btn-refresh")
            await asyncio.sleep(1)
        else:
            print("  Invalid CAPTCHA reading, refreshing...")
            await page.click("#btn-refresh")
            await asyncio.sleep(1)
    # Fallback: manual CAPTCHA via file
    print("\n  Auto CAPTCHA failed. Switching to manual mode...")
    captcha_path = Path("data/logs/captcha_current.png")
    code_file = Path("data/logs/captcha_code.txt")
    if code_file.exists():
        code_file.unlink()

    for attempt in range(1, 20):
        try:
            captcha_img = page.locator(".captcha-code img")
            await captcha_img.screenshot(path=str(captcha_path))
        except Exception:
            pass
        print(f"\n  === Manual CAPTCHA Attempt {attempt} ===")
        print(f"  CAPTCHA image saved to: {captcha_path.absolute()}")
        print(f"  Write the 4-digit code to: {code_file.absolute()}")
        print(f"  (File should contain ONLY the digits, e.g. 4827)")

        for _ in range(90):
            if code_file.exists():
                code = code_file.read_text(encoding="utf-8").strip()
                if code and len(code) == 4 and code.isdigit():
                    code_file.unlink(missing_ok=True)
                    await page.fill("#captcha", code)
                    await page.click("button[type='submit']")
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(2)
                    if "login" not in page.url.lower():
                        print("  Login successful (manual)!")
                        return True
                    print(f"  Wrong CAPTCHA '{code}'. Refreshing...")
                    try:
                        await page.click("#btn-refresh")
                    except Exception:
                        pass
                    await asyncio.sleep(1)
                    break
                elif code:
                    print(f"  Invalid code '{code}' (need exactly 4 digits). Waiting...")
                    code_file.unlink(missing_ok=True)
            await asyncio.sleep(1)
        else:
            print("  Timed out waiting for CAPTCHA code.")
    return False


JS_EXTRACT_FIELDS = """(containerId) => {
    const container = document.getElementById(containerId);
    if (!container) return [];
    const fields = [];
    container.querySelectorAll('input[type="text"], input[type="number"], input[type="date"], input[type="email"], input[type="tel"], textarea').forEach(el => {
        const c = el.closest('.mb-3, .row, .col-md-4, .col-md-6, .col-lg-4, div');
        const l = c ? c.querySelector('label') : null;
        let label = l ? l.textContent.trim().replace(/\\s*\\*\\s*$/, '') : el.placeholder || el.name || '';
        fields.push({
            type: el.tagName === 'TEXTAREA' ? 'textarea' : (el.type === 'tel' ? 'text' : el.type),
            name: el.name, id: el.id, label: label,
            placeholder: el.placeholder || '',
            required: el.required || (c && c.querySelector('.text-danger') !== null),
            visible: el.offsetParent !== null
        });
    });
    container.querySelectorAll('select').forEach(el => {
        const c = el.closest('.mb-3, .row, .col-md-4, .col-md-6, .col-lg-4, div');
        const l = c ? c.querySelector('label') : null;
        let label = l ? l.textContent.trim().replace(/\\s*\\*\\s*$/, '') : el.name || '';
        const options = Array.from(el.options).map(o => ({
            value: o.value, text: o.textContent.trim()
        })).filter(o => o.text && o.text !== 'Select' && !o.text.startsWith('Select '));
        fields.push({
            type: 'select', name: el.name, id: el.id, label: label,
            options: options,
            required: el.required || (c && c.querySelector('.text-danger') !== null)
        });
    });
    const rg = {};
    container.querySelectorAll('input[type="radio"]').forEach(el => {
        const c = el.closest('.mb-3, .row, .col-md-4, .col-md-6, .col-lg-4, div');
        const l = c ? c.querySelector('label:not(input label)') : null;
        let gl = l ? l.textContent.trim().replace(/\\s*\\*\\s*$/, '') : el.name || '';
        const gk = el.name || gl;
        if (!rg[gk]) rg[gk] = {
            type: 'radio', name: el.name, label: gl,
            options: [], required: (c && c.querySelector('.text-danger') !== null),
            selectedValue: null
        };
        const rl = el.closest('label')?.textContent?.trim() || el.value;
        if (rl && rl !== gl && !rg[gk].options.find(o => o.value === el.value)) {
            rg[gk].options.push({value: el.value, label: rl});
        }
        if (el.checked) rg[gk].selectedValue = el.value;
    });
    Object.values(rg).forEach(g => { if (g.options.length > 0) fields.push(g); });
    container.querySelectorAll('input[type="checkbox"]').forEach(el => {
        const c = el.closest('.mb-3, .row, div');
        const l = c ? c.querySelector('label') : null;
        let label = l ? l.textContent.trim() : el.name || '';
        fields.push({
            type: 'checkbox', name: el.name, id: el.id, label: label,
            checked: el.checked
        });
    });
    return fields;
}"""


JS_DETECT_CONDITIONALS = """(containerId) => {
    const container = document.getElementById(containerId);
    if (!container) return [];
    const results = [];
    const radioGroups = {};
    container.querySelectorAll('input[type="radio"]').forEach(el => {
        if (!radioGroups[el.name]) radioGroups[el.name] = [];
        if (!radioGroups[el.name].includes(el.value)) radioGroups[el.name].push(el.value);
    });
    for (const [name, values] of Object.entries(radioGroups)) {
        if (values.length < 2) continue;
        const baseline = {};
        const firstRadio = container.querySelector('input[type="radio"][name="' + name + '"]');
        if (firstRadio) firstRadio.click();
        const countVisible = () => {
            let c = 0;
            container.querySelectorAll('input, select, textarea').forEach(el => {
                if (el.offsetParent !== null && el.name && el.type !== 'hidden') c++;
            });
            return c;
        };
        baseline[values[0]] = countVisible();
        for (let i = 1; i < values.length; i++) {
            const radios = container.querySelectorAll('input[type="radio"][name="' + name + '"]');
            if (radios[i]) radios[i].click();
            baseline[values[i]] = countVisible();
        }
        const resetRadio = container.querySelector('input[type="radio"][name="' + name + '"]');
        if (resetRadio) resetRadio.click();
        results.push({name: name, values: values, fieldCounts: baseline});
    }
    return results;
}"""


JS_EXPAND_DROPDOWNS = """async (containerId) => {
    const container = document.getElementById(containerId);
    if (!container) return [];
    const results = [];
    const selects = container.querySelectorAll('select');
    for (const sel of selects) {
        if (sel.offsetParent === null) continue;
        const c = sel.closest('.mb-3, .row, .col-md-4, .col-md-6, .col-lg-4, div');
        const l = c ? c.querySelector('label') : null;
        let label = l ? l.textContent.trim().replace(/\\s*\\*\\s*$/, '') : sel.name || '';
        sel.click();
        sel.focus();
        await new Promise(r => setTimeout(r, 300));
        const options = Array.from(sel.options).map(o => ({
            value: o.value,
            text: o.textContent.trim()
        })).filter(o => o.text && !o.text.startsWith('Select'));
        results.push({
            name: sel.name,
            id: sel.id,
            label: label,
            optionCount: options.length,
            options: options
        });
    }
    return results;
}"""


JS_CLICK_EVERY_FIELD = """async (containerId) => {
    const container = document.getElementById(containerId);
    if (!container) return [];
    const results = [];
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    const getVisibleFieldNames = () => {
        const names = new Set();
        container.querySelectorAll('input, select, textarea').forEach(el => {
            if (el.offsetParent !== null && el.name && el.type !== 'hidden') {
                names.add(el.name);
            }
        });
        return names;
    };

    const baseline = getVisibleFieldNames();

    const radios = {};
    container.querySelectorAll('input[type="radio"]').forEach(el => {
        if (!radios[el.name]) radios[el.name] = [];
        if (!radios[el.name].find(r => r.value === el.value)) {
            radios[el.name].push({value: el.value, el: el});
        }
    });

    for (const [name, options] of Object.entries(radios)) {
        for (const opt of options) {
            if (opt.el.offsetParent === null) continue;
            const before = getVisibleFieldNames();
            opt.el.click();
            await sleep(400);
            const after = getVisibleFieldNames();
            const appeared = [...after].filter(x => !before.has(x));
            const disappeared = [...before].filter(x => !after.has(x));
            if (appeared.length > 0 || disappeared.length > 0) {
                results.push({
                    trigger: name,
                    triggerType: 'radio',
                    value: opt.value,
                    appeared: appeared,
                    disappeared: disappeared
                });
            }
        }
    }

    const selects = container.querySelectorAll('select');
    for (const sel of selects) {
        if (sel.offsetParent === null) continue;
        for (const opt of sel.options) {
            if (!opt.value || opt.text.startsWith('Select')) continue;
            const before = getVisibleFieldNames();
            sel.value = opt.value;
            sel.dispatchEvent(new Event('change', {bubbles: true}));
            await sleep(400);
            const after = getVisibleFieldNames();
            const appeared = [...after].filter(x => !before.has(x));
            const disappeared = [...before].filter(x => !after.has(x));
            if (appeared.length > 0 || disappeared.length > 0) {
                results.push({
                    trigger: sel.name,
                    triggerType: 'select',
                    value: opt.value,
                    valueText: opt.text.trim(),
                    appeared: appeared,
                    disappeared: disappeared
                });
            }
        }
        sel.value = '';
        sel.dispatchEvent(new Event('change', {bubbles: true}));
        await sleep(200);
    }

    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    for (const cb of checkboxes) {
        if (cb.offsetParent === null) continue;
        const wasChecked = cb.checked;
        const before = getVisibleFieldNames();
        cb.click();
        await sleep(400);
        const after = getVisibleFieldNames();
        const appeared = [...after].filter(x => !before.has(x));
        const disappeared = [...before].filter(x => !after.has(x));
        if (appeared.length > 0 || disappeared.length > 0) {
            results.push({
                trigger: cb.name || cb.id,
                triggerType: 'checkbox',
                value: cb.checked ? 'checked' : 'unchecked',
                appeared: appeared,
                disappeared: disappeared
            });
        }
        if (cb.checked !== wasChecked) cb.click();
        await sleep(200);
    }

    return results;
}"""


def load_our_form_fields():
    form_path = Path("femis-web/templates/form.html")
    if not form_path.exists():
        return {}
    html = form_path.read_text(encoding="utf-8")
    tabs = {}
    tab_ids = [
        ("tab-1", "Personal Details"),
        ("tab-2", "Parents / Guardian"),
        ("tab-3", "Educational Details"),
        ("tab-4", "Emergency Contact"),
        ("tab-5", "IDPs Details"),
        ("tab-6", "Health Details"),
        ("tab-7", "Digital Access"),
    ]
    for tab_id, tab_name in tab_ids:
        pattern = rf'id="{tab_id}"[^>]*>(.*?)(?=<div[^>]*id="tab-|\Z)'
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            tabs[tab_name] = {"inputs": [], "selects": [], "radios": [], "textareas": [], "all_names": []}
            continue
        content = match.group(1)
        inputs = re.findall(r'<input[^>]*name="([^"]*)"[^>]*>', content)
        selects = re.findall(r'<select[^>]*name="([^"]*)"[^>]*>', content)
        radios = re.findall(r'<input[^>]*type="radio"[^>]*name="([^"]*)"[^>]*>', content)
        textareas = re.findall(r'<textarea[^>]*name="([^"]*)"[^>]*>', content)
        all_names = list(set(inputs + selects + textareas))
        tabs[tab_name] = {
            "inputs": list(set(inputs)),
            "selects": list(set(selects)),
            "radios": list(set(radios)),
            "textareas": list(set(textareas)),
            "all_names": all_names,
        }
    return tabs


def load_field_mapping():
    import yaml
    fm_path = Path("config/field_mapping.yaml")
    if not fm_path.exists():
        return {}
    with open(fm_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cross_audit(portal_data):
    our_form = load_our_form_fields()
    portal_names_per_tab = {}
    for tab_key, tab_data in portal_data.items():
        tab_name = tab_data["tab_name"]
        names = set()
        for field in tab_data["fields"]:
            if field.get("name"):
                names.add(field["name"])
            for opt in field.get("options", []):
                if isinstance(opt, dict):
                    pass
        portal_names_per_tab[tab_name] = names

    discrepancies = []
    tab_pairs = [
        ("Personal Details", "Personal Details"),
        ("Parents / Guardian", "Parents / Guardian"),
        ("Educational Details", "Educational Details"),
        ("Emergency Contact", "Emergency Contact"),
        ("IDPs Details", "IDPs Details"),
        ("Health Details", "Health Details"),
        ("Digital Access", "Digital Access"),
    ]

    for portal_tab, our_tab in tab_pairs:
        portal_names = portal_names_per_tab.get(portal_tab, set())
        our_data = our_form.get(our_tab, {})
        our_names = set(our_data.get("all_names", []))

        missing_in_ours = portal_names - our_names
        extra_in_ours = our_names - portal_names

        for name in missing_in_ours:
            discrepancies.append({
                "type": "MISSING_IN_OURS",
                "tab": portal_tab,
                "field_name": name,
                "description": f"Field '{name}' exists in FEMIS but not in our form",
            })
        for name in extra_in_ours:
            if name in ("student_id", "is_locked", "sub_sector"):
                continue
            discrepancies.append({
                "type": "EXTRA_IN_OURS",
                "tab": our_tab,
                "field_name": name,
                "description": f"Field '{name}' exists in our form but not in FEMIS",
            })

    for tab_key, tab_data in portal_data.items():
        tab_name = tab_data["tab_name"]
        for cond in tab_data.get("conditionals", []):
            counts = cond.get("fieldCounts", {})
            unique = set(counts.values())
            if len(unique) > 1:
                discrepancies.append({
                    "type": "CONDITIONAL_FIELD",
                    "tab": tab_name,
                    "field_name": cond["name"],
                    "description": f"Radio '{cond['name']}' reveals/hides fields: {counts}",
                })
        for cond in tab_data.get("click_conditionals", []):
            appeared = cond.get("appeared", [])
            disappeared = cond.get("disappeared", [])
            if appeared or disappeared:
                desc_parts = []
                if appeared:
                    desc_parts.append(f"shows: {appeared}")
                if disappeared:
                    desc_parts.append(f"hides: {disappeared}")
                discrepancies.append({
                    "type": "CLICK_CONDITIONAL",
                    "tab": tab_name,
                    "field_name": cond["trigger"],
                    "description": f"{cond['triggerType']} '{cond['trigger']}'={cond.get('valueText', cond.get('value', ''))}: {', '.join(desc_parts)}",
                })

    return discrepancies


def print_disc_summary(discrepancies):
    if not discrepancies:
        print("\n  No discrepancies found! Forms match.")
        return
    by_type = {}
    for d in discrepancies:
        t = d["type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(d)
    print(f"\n  Total discrepancies: {len(discrepancies)}")
    for dtype, items in by_type.items():
        print(f"\n  [{dtype}] ({len(items)} items)")
        for item in items[:20]:
            print(f"    Tab: {item['tab']} | Field: {item['field_name']}")
            print(f"      {item['description']}")
        if len(items) > 20:
            print(f"    ... and {len(items) - 20} more")


async def audit():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("data/logs")
    out_dir = Path("data/output")
    log_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False, slow_mo=600)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        print("=" * 60)
        print("PHASE 1: Login")
        print("=" * 60)
        await page.goto(LOGIN_URL, wait_until="networkidle")
        await page.fill("#username", os.getenv("FEMIS_USERNAME"))
        await page.fill("#password", os.getenv("FEMIS_PASSWORD"))
        if not await solve_captcha(page):
            print("Auto-solve failed. Exiting.")
            await browser.close()
            return
        await asyncio.sleep(2)

        print("\nNavigating to Add Student...")
        await page.goto(CREATE_URL, wait_until="networkidle")
        await asyncio.sleep(3)

        print("\n" + "=" * 60)
        print("PHASE 2: Tab-by-Tab Field Extraction")
        print("=" * 60)

        all_tabs = {}

        for tab_i, (tab_name, tab_nav_ids) in enumerate(TABS, 1):
            print(f"\n{'─'*60}")
            print(f"Tab {tab_i}/7: {tab_name}")
            print(f"{'─'*60}")

            # Click the tab by its name or ID at the top of the form
            clicked = False
            for nav_id in tab_nav_ids:
                try:
                    el = page.locator(f"#{nav_id}")
                    if await el.count() > 0:
                        await el.click(timeout=5000)
                        clicked = True
                        break
                except Exception:
                    pass

            if not clicked:
                # Try clicking by visible text (the tab name)
                try:
                    el = page.get_by_role("tab", name=tab_name)
                    await el.click(timeout=5000)
                    clicked = True
                except Exception:
                    pass

            if not clicked:
                # Try clicking any element containing the tab name text
                try:
                    el = page.locator(f"text={tab_name}").first
                    await el.click(timeout=5000)
                    clicked = True
                except Exception:
                    pass

            if not clicked:
                print(f"  ERROR: Could not click tab '{tab_name}'. Skipping.")
                continue

            await asyncio.sleep(1.5)

            # Handle Confirm dialog if it appears
            try:
                confirm_btn = page.locator("button:has-text('CONFIRM'), button:has-text('Confirm')")
                await confirm_btn.wait_for(state="visible", timeout=2000)
                await confirm_btn.click()
                await asyncio.sleep(1)
                print("  Handled Confirm dialog")
            except Exception:
                pass

            # Scroll down to load all content
            for _ in range(10):
                await page.mouse.wheel(0, 500)
                await asyncio.sleep(0.3)

            ss_path = log_dir / f"audit_tab_{tab_i}_{tab_name.replace(' ', '_').replace('/', '_')}_{ts}.png"
            await page.screenshot(path=str(ss_path), full_page=True)
            print(f"  Screenshot: {ss_path}")

            # Extract all fields
            fields = await page.evaluate(JS_EXTRACT_FIELDS, panel_id)
            print(f"  Found {len(fields)} fields:")
            for f in fields:
                opts_str = ""
                if f.get("options"):
                    opts = f["options"]
                    if opts and isinstance(opts[0], dict):
                        opt_texts = [o.get("text", o.get("label", "")) for o in opts]
                    else:
                        opt_texts = [str(o) for o in opts]
                    if len(opt_texts) > 6:
                        opts_str = f"  [{len(opt_texts)} opts: {', '.join(opt_texts[:4])}...]"
                    else:
                        opts_str = f"  [{', '.join(opt_texts)}]"
                req = " *" if f.get("required") else ""
                vis = "" if f.get("visible", True) else " [HIDDEN]"
                lbl = f.get("label", "N/A")[:50]
                print(f"    [{f['type']:8s}] {lbl}{req}{opts_str}{vis}")

            # Detect conditional fields by clicking every field
            print("  Clicking every field to detect conditionals...")
            click_conditionals = await page.evaluate(JS_CLICK_EVERY_FIELD, panel_id)
            if click_conditionals:
                print(f"    Found {len(click_conditionals)} conditional triggers:")
                for cond in click_conditionals:
                    trigger = cond['trigger']
                    ttype = cond['triggerType']
                    val = cond.get('valueText', cond.get('value', ''))
                    appeared = cond.get('appeared', [])
                    disappeared = cond.get('disappeared', [])
                    if appeared or disappeared:
                        print(f"      {ttype} '{trigger}' = '{val}': +{appeared} -{disappeared}")
            else:
                print("    No conditional triggers found")

            # Also run the original radio-based detection for comparison
            print("  Running radio-group detection...")
            conditionals = await page.evaluate(JS_DETECT_CONDITIONALS, panel_id)
            if conditionals:
                for cond in conditionals:
                    counts = cond["fieldCounts"]
                    unique_counts = set(counts.values())
                    if len(unique_counts) > 1:
                        print(f"    CONDITIONAL: radio '{cond['name']}' -> field counts: {counts}")

            # Expand dropdowns
            print("  Expanding dropdowns...")
            dropdowns = await page.evaluate(JS_EXPAND_DROPDOWNS, panel_id)
            for dd in dropdowns:
                opt_count = dd["optionCount"]
                print(f"    Select '{dd['label']}' ({dd['name']}): {opt_count} options")

            tab_key = f"tab_{tab_i}"
            all_tabs[tab_key] = {
                "tab_name": tab_name,
                "fields": fields,
                "conditionals": conditionals,
                "click_conditionals": click_conditionals,
                "dropdowns": dropdowns,
                "screenshot": str(ss_path),
            }

        audit_path = out_dir / f"portal_audit_{ts}.json"
        with open(audit_path, "w", encoding="utf-8") as fp:
            json.dump(all_tabs, fp, indent=2, ensure_ascii=False, default=str)
        print(f"\nRaw audit saved: {audit_path}")

        print("\n" + "=" * 60)
        print("PHASE 3: Cross-Audit Against Our Form")
        print("=" * 60)

        discrepancies = cross_audit(all_tabs)

        disc_path = out_dir / f"audit_discrepancies_{ts}.json"
        with open(disc_path, "w", encoding="utf-8") as fp:
            json.dump(discrepancies, fp, indent=2, ensure_ascii=False, default=str)
        print(f"Discrepancies saved: {disc_path}")

        print_disc_summary(discrepancies)

        await browser.close()
        print("\nAudit complete!")


if __name__ == "__main__":
    asyncio.run(audit())
