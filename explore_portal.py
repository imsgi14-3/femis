import asyncio, json, os, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from google import genai

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def solve_captcha(page, max_retries=5):
    for attempt in range(1, max_retries + 1):
        print(f"  CAPTCHA attempt {attempt}/{max_retries}...")
        captcha_img = page.locator(".captcha-code img")
        captcha_path = Path("data/logs") / f"captcha_{attempt}.png"
        captcha_path.parent.mkdir(parents=True, exist_ok=True)
        await captcha_img.screenshot(path=str(captcha_path))
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=[
                "Read the 4-digit CAPTCHA code from this image. Return ONLY the 4 digits, nothing else.",
                genai.types.Part.from_bytes(data=captcha_path.read_bytes(), mime_type="image/png"),
            ],
        )
        code = response.text.strip().replace(" ", "").replace("-", "")
        print(f"  Gemini reads: {code}")
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
    return False

JS_EXTRACT = """() => {
    const fields = [];
    document.querySelectorAll('input[type="text"], input[type="number"], input[type="date"], input[type="email"], input[type="tel"]').forEach(el => {
        const c = el.closest('.mb-3, .row, .col-md-4, .col-md-6, .col-lg-4, div');
        const l = c ? c.querySelector('label') : null;
        let label = l ? l.textContent.trim().replace(/\\s*\\*\\s*$/, '') : el.placeholder || el.name || '';
        fields.push({type: el.type === 'tel' ? 'text' : el.type, name: el.name, id: el.id, label: label, placeholder: el.placeholder || '', required: el.required || (c && c.querySelector('.text-danger') !== null)});
    });
    document.querySelectorAll('select').forEach(el => {
        const c = el.closest('.mb-3, .row, .col-md-4, .col-md-6, .col-lg-4, div');
        const l = c ? c.querySelector('label') : null;
        let label = l ? l.textContent.trim().replace(/\\s*\\*\\s*$/, '') : el.name || '';
        const skip = ['Select', 'Select Gender', 'Select Province', 'Select District', 'Select City', 'Select Type', 'Select Religion', 'Select Blood Group'];
        const options = Array.from(el.options).map(o => o.textContent.trim()).filter(o => o && !skip.some(s => o.startsWith(s)));
        fields.push({type: 'select', name: el.name, id: el.id, label: label, options: options, required: el.required || (c && c.querySelector('.text-danger') !== null)});
    });
    const rg = {};
    document.querySelectorAll('input[type="radio"]').forEach(el => {
        const c = el.closest('.mb-3, .row, .col-md-4, .col-md-6, div');
        const l = c ? c.querySelector('label:not(input label)') : null;
        let gl = l ? l.textContent.trim().replace(/\\s*\\*\\s*$/, '') : el.name || '';
        const gk = el.name || gl;
        if (!rg[gk]) rg[gk] = {type: 'radio', name: el.name, label: gl, options: [], required: (c && c.querySelector('.text-danger') !== null)};
        const rl = el.closest('label')?.textContent?.trim() || el.value;
        if (rl && rl !== gl && !rg[gk].options.includes(rl)) rg[gk].options.push(rl);
    });
    Object.values(rg).forEach(g => { if (g.options.length > 0) fields.push(g); });
    document.querySelectorAll('input[type="checkbox"]').forEach(el => {
        const c = el.closest('.mb-3, .row, div');
        const l = c ? c.querySelector('label') : null;
        let label = l ? l.textContent.trim() : el.name || '';
        fields.push({type: 'checkbox', name: el.name, id: el.id, label: label});
    });
    return fields;
}"""

async def explore():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False, slow_mo=800)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        print("Navigating to login...")
        await page.goto("https://femis.fde.gov.pk/login", wait_until="networkidle")
        await page.fill("#username", os.getenv("FEMIS_USERNAME"))
        await page.fill("#password", os.getenv("FEMIS_PASSWORD"))
        print("Attempting CAPTCHA auto-solve...")
        if not await solve_captcha(page):
            print("Auto-solve failed. Exiting.")
            await browser.close()
            return
        print(f"Logged in! URL: {page.url}")
        await asyncio.sleep(2)

        print("Navigating to Add Student...")
        await page.goto("https://femis.fde.gov.pk/students/create", wait_until="networkidle")
        await asyncio.sleep(3)

        tabs = ["Personal Details", "Parents / Guardian", "Educational Details", "Emergency Contact", "IDPs Details", "Health Details", "Digital Access"]
        all_fields = {}

        for i, tab_name in enumerate(tabs, 1):
            print(f"\n{'='*60}\nTab {i}/7: {tab_name}\n{'='*60}")
            try:
                await page.get_by_role("tab", name=tab_name).click(timeout=5000)
                await asyncio.sleep(2)
            except:
                try:
                    await page.locator(f"span.tab-nav-link:has-text('{tab_name}')").first.click(timeout=5000)
                    await asyncio.sleep(2)
                except Exception as e2:
                    print(f"  Skipping: {e2}")
                    continue

            for _ in range(8):
                await page.mouse.wheel(0, 400)
                await asyncio.sleep(0.3)

            fields = await page.evaluate(JS_EXTRACT)
            tab_key = f"tab_{i}_{tab_name.lower().replace(' ', '_').replace('/', '_')}"
            all_fields[tab_key] = {"tab_name": tab_name, "fields": fields}
            print(f"  Found {len(fields)} fields:")
            for f in fields:
                opts = ""
                if f.get("options"):
                    opts_list = f["options"]
                    if len(opts_list) > 8:
                        opts = f" | Options({len(opts_list)}): {opts_list[:5]}..."
                    else:
                        opts = f" | Options: {opts_list}"
                req = " *" if f.get("required") else ""
                lbl = f.get("label", "N/A")[:60]
                print(f"    [{f['type']}] {lbl}{req}{opts}")

            ss = f"data/logs/tab_{i}_{tab_name.replace(' ', '_').replace('/', '_')}.png"
            await page.screenshot(path=ss, full_page=True)
            print(f"  Screenshot: {ss}")

        out = Path("data/output/portal_fields.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fp:
            json.dump(all_fields, fp, indent=2, ensure_ascii=False)
        print(f"\nAll fields saved to: {out}")
        await browser.close()
        print("Done!")

asyncio.run(explore())
