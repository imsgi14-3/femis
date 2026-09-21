import asyncio, os, json, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from google import genai

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

JS_DISCOVER = """() => {
    const tabs = [];
    document.querySelectorAll('[role="tab"], .nav-link, .tab-nav-link, a[data-bs-toggle="pill"], a[data-bs-toggle="tab"]').forEach(el => {
        tabs.push({tag: el.tagName, text: el.textContent.trim(), id: el.id, classes: el.className, href: el.getAttribute('href'), ariaControls: el.getAttribute('aria-controls')});
    });
    const panels = [];
    document.querySelectorAll('[role="tabpanel"], .tab-pane, .tab-content > div').forEach(el => {
        panels.push({tag: el.tagName, id: el.id, classes: el.className, childInputs: el.querySelectorAll('input, select, textarea').length, display: getComputedStyle(el).display});
    });
    const sections = [];
    document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(el => {
        const text = el.textContent.trim().substring(0, 80);
        if (text) sections.push({tag: el.tagName, text: text, id: el.id});
    });
    const cards = [];
    document.querySelectorAll('.card, fieldset, [class*="section"], [class*="group"]').forEach(el => {
        const h = el.querySelector('h1,h2,h3,h4,h5,h6');
        if (h) {
            cards.push({
                header: h.textContent.trim().substring(0, 80),
                tag: el.tagName,
                classes: el.className.substring(0, 100),
                childInputs: el.querySelectorAll('input, select, textarea').length,
                visible: el.offsetParent !== null
            });
        }
    });
    return {tabs, panels, sections, cards};
}"""

async def discover():
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False, slow_mo=400)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        await page.goto("https://femis.fde.gov.pk/login", wait_until="networkidle")
        await page.fill("#username", os.getenv("FEMIS_USERNAME"))
        await page.fill("#password", os.getenv("FEMIS_PASSWORD"))
        for attempt in range(1, 6):
            captcha_path = Path("data/logs") / f"disc_{attempt}.png"
            captcha_path.parent.mkdir(parents=True, exist_ok=True)
            await page.locator(".captcha-code img").screenshot(path=str(captcha_path))
            resp = client.models.generate_content(model="gemini-3.6-flash", contents=["Read the 4-digit CAPTCHA. Return ONLY digits.", genai.types.Part.from_bytes(data=captcha_path.read_bytes(), mime_type="image/png")])
            code = resp.text.strip().replace(" ", "").replace("-", "")
            if len(code) == 4 and code.isdigit():
                await page.fill("#captcha", code)
                await page.click("button[type='submit']")
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)
                if "login" not in page.url.lower():
                    break
                await page.click("#btn-refresh")
                await asyncio.sleep(1)
        await page.goto("https://femis.fde.gov.pk/students/create", wait_until="networkidle")
        await asyncio.sleep(3)
        result = await page.evaluate(JS_DISCOVER)
        with open("data/output/dom_structure.json", "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(json.dumps(result, indent=2, default=str))
        await browser.close()

asyncio.run(discover())
