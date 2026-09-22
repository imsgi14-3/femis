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
    ("Personal Details", ["tab-nav-personal", "tab-personal"], "tab-1"),
    ("Parents / Guardian", ["tab-nav-parents", "tab-parents"], "tab-2"),
    ("Educational Details", ["tab-nav-education", "tab-education"], "tab-3"),
    ("Emergency Contact", ["tab-nav-emergency", "tab-emergency"], "tab-4"),
    ("IDPs Details", ["tab-nav-idps", "tab-idps"], "tab-5"),
    ("Health Details", ["tab-nav-health", "tab-health"], "tab-6"),
    ("Digital Access", ["tab-nav-digital", "tab-digital"], "tab-7"),
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
            options: options, multiple: el.multiple || false,
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
        const rl = el.nextElementSibling ? el.nextElementSibling.textContent.trim() : el.value;
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


JS_TRIGGER_CASCADES = """async (containerId) => {
    const container = document.getElementById(containerId);
    if (!container) return [];
    const results = [];
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    const cascades = [
        {parent: 'birth_province_id', child: 'birth_district_id', type: 'province'},
        {parent: 'domicile_province_id', child: 'domicile_district_id', type: 'province'},
        {parent: 'father_domicile_province_id', child: 'father_domicile_district_id', type: 'province'},
        {parent: 'sector_id', child: 'sub_sector_id', type: 'sector'},
        {parent: 'present_sector_id', child: 'present_sub_sector_id', type: 'sector'},
        {parent: 'class_id', child: 'section_id', type: 'class'},
    ];

    for (const cascade of cascades) {
        const parentSel = container.querySelector('select[name="' + cascade.parent + '"]');
        const childSel = container.querySelector('select[name="' + cascade.child + '"]');
        if (!parentSel || !childSel) continue;
        if (parentSel.offsetParent === null) continue;

        for (const opt of parentSel.options) {
            if (!opt.value || opt.text.startsWith('Select')) continue;
            parentSel.value = opt.value;
            parentSel.dispatchEvent(new Event('change', {bubbles: true}));
            await sleep(800);

            const childOpts = Array.from(childSel.options).map(o => ({
                value: o.value, text: o.textContent.trim()
            })).filter(o => o.value && !o.text.startsWith('Select'));

            if (childOpts.length > 0) {
                results.push({
                    cascade: cascade.type,
                    parentName: cascade.parent,
                    parentValue: opt.value,
                    parentText: opt.text.trim(),
                    childName: cascade.child,
                    childOptions: childOpts
                });
                break;
            }
        }
        parentSel.value = '';
        parentSel.dispatchEvent(new Event('change', {bubbles: true}));
        await sleep(300);
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
            tabs[tab_name] = {"fields": [], "all_names": []}
            continue
        content = match.group(1)
        fields = []

        # Extract inputs with type and required
        for m in re.finditer(r'<input[^>]*name="([^"]*)"[^>]*type="([^"]*)"[^>]*>', content):
            name, ftype = m.group(1), m.group(2)
            full = m.group(0)
            required = 'required' in full or 'text-danger' in full
            label = _extract_label(content, name)
            fields.append({"name": name, "type": ftype, "required": required, "label": label})

        for m in re.finditer(r'<input[^>]*type="([^"]*)"[^>]*name="([^"]*)"[^>]*>', content):
            ftype, name = m.group(1), m.group(2)
            if any(f["name"] == name and f["type"] == ftype for f in fields):
                continue
            full = m.group(0)
            required = 'required' in full or 'text-danger' in full
            label = _extract_label(content, name)
            fields.append({"name": name, "type": ftype, "required": required, "label": label})

        # Extract selects with options
        for m in re.finditer(r'<select[^>]*name="([^"]*)"[^>]*>(.*?)</select>', content, re.DOTALL):
            name = m.group(1)
            body = m.group(2)
            required = 'required' in m.group(0) or 'text-danger' in m.group(0)
            opts = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', body)
            opts = [{"value": v, "text": t.strip()} for v, t in opts if v and t.strip() and not t.strip().startswith("Select")]
            label = _extract_label(content, name)
            fields.append({"name": name, "type": "select", "required": required, "label": label, "options": opts})

        # Extract radios grouped by name
        radio_groups = {}
        for m in re.finditer(r'<input[^>]*type="radio"[^>]*name="([^"]*)"[^>]*value="([^"]*)"[^>]*>', content):
            name, value = m.group(1), m.group(2)
            if name not in radio_groups:
                radio_groups[name] = {"name": name, "type": "radio", "options": [], "required": False}
            # Find the label for this radio
            label_match = re.search(rf'for="[^"]*{re.escape(value)}[^"]*"[^>]*>([^<]*)<', content)
            opt_label = label_match.group(1).strip() if label_match else value
            radio_groups[name]["options"].append({"value": value, "label": opt_label})
            if 'required' in m.group(0) or 'text-danger' in m.group(0):
                radio_groups[name]["required"] = True
        for rg in radio_groups.values():
            rg["label"] = _extract_label(content, rg["name"])
            fields.append(rg)

        # Extract textareas
        for m in re.finditer(r'<textarea[^>]*name="([^"]*)"[^>]*>', content):
            name = m.group(1)
            required = 'required' in m.group(0) or 'text-danger' in m.group(0)
            label = _extract_label(content, name)
            fields.append({"name": name, "type": "textarea", "required": required, "label": label})

        all_names = list(set(f["name"] for f in fields))
        tabs[tab_name] = {"fields": fields, "all_names": all_names}
    return tabs


def _extract_label(content, field_name):
    """Find the label text for a field by name."""
    patterns = [
        rf'<label[^>]*for="[^"]*"[^>]*>[^<]*<[^>]*name="{re.escape(field_name)}"',
        rf'name="{re.escape(field_name)}"[^>]*',
    ]
    # Simple approach: find label before the field
    idx = content.find(f'name="{field_name}"')
    if idx < 0:
        return field_name
    before = content[:idx]
    label_match = re.findall(r'<label[^>]*>([^<]+)</label>', before)
    if label_match:
        return label_match[-1].strip().replace("*", "").strip()
    return field_name


def load_field_mapping():
    import yaml
    fm_path = Path("config/field_mapping.yaml")
    if not fm_path.exists():
        return {}
    with open(fm_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cross_audit(portal_data):
    our_form = load_our_form_fields()
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
        tab_data = portal_data.get(f"tab_{tab_pairs.index((portal_tab, our_tab)) + 1}", {})
        portal_fields = tab_data.get("fields", [])
        our_data = our_form.get(our_tab, {})
        our_fields = our_data.get("fields", [])

        portal_by_name = {}
        for f in portal_fields:
            if f.get("name"):
                portal_by_name[f["name"]] = f
        our_by_name = {}
        for f in our_fields:
            if f.get("name"):
                our_by_name[f["name"]] = f

        portal_names = set(portal_by_name.keys())
        our_names = set(our_by_name.keys())

        # RULE 1: Missing/extra fields (name comparison)
        for name in portal_names - our_names:
            discrepancies.append({
                "type": "MISSING_IN_OURS",
                "tab": portal_tab,
                "field_name": name,
                "severity": "HIGH",
                "description": f"Field '{name}' exists in FEMIS but not in our form",
            })
        for name in our_names - portal_names:
            if name in ("student_id", "is_locked"):
                continue
            discrepancies.append({
                "type": "EXTRA_IN_OURS",
                "tab": our_tab,
                "field_name": name,
                "severity": "MEDIUM",
                "description": f"Field '{name}' exists in our form but not in FEMIS",
            })

        # RULE 2: Field type mismatch
        for name in portal_names & our_names:
            pf = portal_by_name[name]
            of = our_by_name[name]
            pt = pf.get("type", "")
            ot = of.get("type", "")
            # Normalize types
            type_map = {"text": "text", "number": "number", "email": "text", "tel": "text",
                        "date": "date", "textarea": "textarea", "select": "select",
                        "radio": "radio", "checkbox": "checkbox"}
            pt_norm = type_map.get(pt, pt)
            ot_norm = type_map.get(ot, ot)
            if pt_norm != ot_norm:
                discrepancies.append({
                    "type": "TYPE_MISMATCH",
                    "tab": portal_tab,
                    "field_name": name,
                    "severity": "HIGH",
                    "description": f"Field '{name}': portal is '{pt}' but ours is '{ot}'",
                })

        # RULE 3: Mandatory/required mismatch
        for name in portal_names & our_names:
            pf = portal_by_name[name]
            of = our_by_name[name]
            portal_req = pf.get("required", False)
            our_req = of.get("required", False)
            if portal_req and not our_req:
                discrepancies.append({
                    "type": "MISSING_REQUIRED",
                    "tab": portal_tab,
                    "field_name": name,
                    "severity": "HIGH",
                    "description": f"Field '{name}' is REQUIRED in portal but optional in our form",
                })

        # RULE 4: Select option comparison
        for name in portal_names & our_names:
            pf = portal_by_name[name]
            of = our_by_name[name]
            if pf.get("type") != "select" or of.get("type") != "select":
                continue
            portal_opts = {o.get("value", o.get("text", "")) for o in pf.get("options", []) if o.get("value")}
            our_opts = {o.get("value", o.get("text", "")) for o in of.get("options", []) if o.get("value")}
            if not portal_opts and not our_opts:
                continue
            if not portal_opts:
                discrepancies.append({
                    "type": "EMPTY_PORTAL_OPTIONS",
                    "tab": portal_tab,
                    "field_name": name,
                    "severity": "LOW",
                    "description": f"Select '{name}' has empty options in portal (cascade not triggered)",
                })
                continue
            if not our_opts:
                discrepancies.append({
                    "type": "EMPTY_OUR_OPTIONS",
                    "tab": our_tab,
                    "field_name": name,
                    "severity": "HIGH",
                    "description": f"Select '{name}' has no options in our form",
                })
                continue
            missing_opts = portal_opts - our_opts
            extra_opts = our_opts - portal_opts
            if missing_opts:
                discrepancies.append({
                    "type": "MISSING_OPTIONS",
                    "tab": our_tab,
                    "field_name": name,
                    "severity": "HIGH",
                    "description": f"Select '{name}' missing options: {sorted(missing_opts)[:5]}",
                })
            if extra_opts:
                discrepancies.append({
                    "type": "EXTRA_OPTIONS",
                    "tab": our_tab,
                    "field_name": name,
                    "severity": "MEDIUM",
                    "description": f"Select '{name}' has extra options not in portal: {sorted(extra_opts)[:5]}",
                })

        # RULE 5: Radio option comparison
        for name in portal_names & our_names:
            pf = portal_by_name[name]
            of = our_by_name[name]
            if pf.get("type") != "radio" or of.get("type") != "radio":
                continue
            portal_vals = {o.get("value", "") for o in pf.get("options", [])}
            our_vals = {o.get("value", "") for o in of.get("options", [])}
            if portal_vals != our_vals:
                discrepancies.append({
                    "type": "RADIO_OPTIONS_MISMATCH",
                    "tab": portal_tab,
                    "field_name": name,
                    "severity": "HIGH",
                    "description": f"Radio '{name}': portal has {sorted(portal_vals)}, ours has {sorted(our_vals)}",
                })

        # RULE 6: Multi-select detection
        for name in portal_names & our_names:
            pf = portal_by_name[name]
            of = our_by_name[name]
            if pf.get("type") == "select" and pf.get("multiple") and not of.get("multiple"):
                discrepancies.append({
                    "type": "MULTI_SELECT_MISSING",
                    "tab": our_tab,
                    "field_name": name,
                    "severity": "HIGH",
                    "description": f"Select '{name}' is multi-select in portal but single-select in ours",
                })

        # RULE 7: Label text mismatch
        for name in portal_names & our_names:
            pf = portal_by_name[name]
            of = our_by_name[name]
            pl = pf.get("label", "").lower().strip()
            ol = of.get("label", "").lower().strip()
            if pl and ol and pl != ol and pl != name and ol != name:
                discrepancies.append({
                    "type": "LABEL_MISMATCH",
                    "tab": portal_tab,
                    "field_name": name,
                    "severity": "LOW",
                    "description": f"Label mismatch for '{name}': portal='{pf.get('label')}', ours='{of.get('label')}'",
                })

    # RULE 8: Conditional logic validation
    for tab_key, tab_data in portal_data.items():
        tab_name = tab_data.get("tab_name", "")
        for cond in tab_data.get("conditionals", []):
            counts = cond.get("fieldCounts", {})
            unique = set(counts.values())
            if len(unique) > 1:
                discrepancies.append({
                    "type": "CONDITIONAL_FIELD",
                    "tab": tab_name,
                    "field_name": cond["name"],
                    "severity": "MEDIUM",
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
                    "severity": "MEDIUM",
                    "description": f"{cond['triggerType']} '{cond['trigger']}'={cond.get('valueText', cond.get('value', ''))}: {', '.join(desc_parts)}",
                })

    return discrepancies


def print_disc_summary(discrepancies):
    if not discrepancies:
        print("\n  No discrepancies found! Forms match.")
        return
    by_severity = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for d in discrepancies:
        sev = d.get("severity", "MEDIUM")
        by_severity.setdefault(sev, []).append(d)
    print(f"\n  Total discrepancies: {len(discrepancies)}")
    for sev in ["HIGH", "MEDIUM", "LOW"]:
        items = by_severity.get(sev, [])
        if not items:
            continue
        print(f"\n  [{sev}] ({len(items)} items)")
        by_type = {}
        for item in items:
            t = item["type"]
            by_type.setdefault(t, []).append(item)
        for dtype, type_items in by_type.items():
            print(f"    [{dtype}] ({len(type_items)} items)")
            for item in type_items[:15]:
                print(f"      Tab: {item['tab']} | Field: {item['field_name']}")
                print(f"        {item['description']}")
            if len(type_items) > 15:
                print(f"      ... and {len(type_items) - 15} more")


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

        for tab_i, (tab_name, tab_nav_ids, panel_id) in enumerate(TABS, 1):
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

            # Trigger cascades to capture populated child dropdowns
            print("  Triggering cascades...")
            cascades = await page.evaluate(JS_TRIGGER_CASCADES, panel_id)
            if cascades:
                print(f"    Found {len(cascades)} cascade results:")
                for c in cascades:
                    print(f"      {c['cascade']}: {c['parentText']} -> {c['childName']} ({len(c['childOptions'])} options)")

            tab_key = f"tab_{tab_i}"
            all_tabs[tab_key] = {
                "tab_name": tab_name,
                "fields": fields,
                "conditionals": conditionals,
                "click_conditionals": click_conditionals,
                "dropdowns": dropdowns,
                "cascades": cascades,
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
