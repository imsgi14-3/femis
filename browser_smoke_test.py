"""Browser e2e: same-address autofill + save-tab persistence."""
import sys
import time
from pathlib import Path

BASE = "http://127.0.0.1:5000"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # --- login as student (creates record) ---
        page.goto(f"{BASE}/login")
        page.fill('input[name="name"]', "E2E Smoke Student")
        page.select_option('select[name="class_id"]', "5")
        page.fill('input[name="section"]', "A")
        page.fill('input[name="roll_no"]', "99")
        page.click('button[type="submit"]')
        page.wait_for_url("**/student-dashboard**", timeout=10000)
        check("student login", True)

        # open form
        page.click('a:has-text("Fill / Edit Form")')
        page.wait_for_url("**/form/**", timeout=10000)
        check("form opened", "/form/" in page.url, page.url)
        student_id = page.url.rstrip("/").split("/")[-1]
        check("student_id in URL", student_id.isdigit(), student_id)

        # --- fill temporary address ---
        page.select_option("#address_type", "Sector")
        page.wait_for_timeout(200)
        page.select_option("#sector_select", label="F-6")
        page.wait_for_timeout(500)  # sub-sector cascade fetch
        sub_opts = page.locator("#sub_sector_select option").all_text_contents()
        check("sub-sector cascade loaded", any("F-6/" in o for o in sub_opts), str(sub_opts[:5]))
        page.select_option("#sub_sector_select", "F-6/1")
        page.fill('input[name="house"]', "42")
        page.fill('input[name="street"]', "7")

        # --- check same as temporary ---
        page.check("#same_as_temporary")
        page.wait_for_timeout(300)

        # permanent fields should be populated (even if container hidden)
        present_type = page.locator("#present_address_type").input_value()
        present_house = page.locator('input[name="present_house"]').input_value()
        present_street = page.locator('input[name="present_street"]').input_value()
        check("autofill present_address_type", present_type == "Sector", present_type)
        check("autofill present_house", present_house == "42", present_house)
        check("autofill present_street", present_street == "7", present_street)

        # sector select value is portal id (e.g. "6"), text is "F-6"
        present_sector = page.locator("#present_sector_select").input_value()
        present_sector_text = page.locator(
            "#present_sector_select option:checked"
        ).text_content()
        temp_sector = page.locator("#sector_select").input_value()
        check(
            "autofill present_sector",
            present_sector == temp_sector and present_sector_text.strip() == "F-6",
            f"value={present_sector!r} text={present_sector_text!r}",
        )

        # present sub-sector: cascade may not fire when hidden — check value
        present_sub = page.locator("#present_sub_sector_select").input_value()
        present_sub_text = page.locator(
            "#present_sub_sector_select option:checked"
        ).text_content()
        check(
            "autofill present_sub_sector",
            present_sub == "F-6/1" or (present_sub_text or "").strip() == "F-6/1",
            f"value={present_sub!r} text={present_sub_text!r}",
        )

        # --- fill required tab-1 fields for validation ---
        page.fill('input[name="name"]', "E2E Smoke Student")
        page.check("#cnic_avail_yes")
        page.fill('input[name="b_form"]', "3520212345671")
        page.select_option('select[name="gender"]', "Male")
        page.fill('input[name="date_of_birth"]', "2015-03-15")
        page.select_option("#birth_province_id", label="Islamabad Capital Territory")
        page.wait_for_timeout(500)
        page.select_option("#birth_district_id", label="Islamabad")
        page.select_option("#nationality", label="Pakistani")
        page.fill('input[name="contact_number"]', "03001234567")
        page.select_option('select[name="city_id"]', label="Islamabad")
        page.select_option('select[name="religion"]', label="Muslim")
        page.select_option('select[name="language_id"]', label="Urdu")
        page.fill('input[name="email"]', "e2e@test.com")

        # --- Save & Next ---
        dialog_msg = {"text": ""}
        page.on("dialog", lambda d: (dialog_msg.update(text=d.message), d.accept()))
        page.click("#saveNextBtn, button:has-text('Save & Next')")
        page.wait_for_timeout(2000)

        if dialog_msg["text"]:
            check("save no validation alert", "mandatory" not in dialog_msg["text"].lower(), dialog_msg["text"][:200])
        else:
            check("save no validation alert", True, "no dialog")

        # should advance to tab 2 or stay with success
        tab2_active = page.locator("#tab-2.active, a[href='#tab-2'].active").count() > 0
        # bootstrap pill: active class on nav-link and tab-pane
        tab2_pane = page.locator("#tab-2.tab-pane.active").count() > 0
        check("advanced to tab 2", tab2_pane or tab2_active, f"pane={tab2_pane} nav={tab2_active}")

        # --- verify DB via JSON endpoint ---
        page.goto(f"{BASE}/students/{student_id}/json")
        body = page.inner_text("body")
        import json

        try:
            data = json.loads(body)
        except Exception:
            data = {}
            check("JSON parse", False, body[:200])

        if data:
            check(
                "DB same_address",
                str(data.get("same_address")) in ("1", "True", "on"),
                str(data.get("same_address")),
            )
            check("DB sub_sector_id", data.get("sub_sector_id") == "F-6/1", str(data.get("sub_sector_id")))
            check(
                "DB present_sub_sector_id",
                data.get("present_sub_sector_id") == "F-6/1",
                str(data.get("present_sub_sector_id")),
            )
            check("DB sector_id", data.get("sector_id") in ("F-6", "6", "2"), str(data.get("sector_id")))
            check("DB house", str(data.get("house")) == "42", str(data.get("house")))
            check("DB present_house", str(data.get("present_house")) == "42", str(data.get("present_house")))

        browser.close()

    failed = [r for r in results if not r[1]]
    print(f"\n{'='*40}\n{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
