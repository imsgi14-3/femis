"""Quick test: reuse saved session (or log in once), then fill one student."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from playwright.async_api import async_playwright
from src.auth import FEMISAuth, SESSION_PATH
from src.form_filler import FormFiller
from src.data_sources.webform_handler import WebFormHandler
from src.utils.logger import setup_logger
from dotenv import load_dotenv
import os

logger = setup_logger("test_bot")
load_dotenv()

LOGIN_URL = "https://femis.fde.gov.pk/login"
STUDENTS_URL = "https://femis.fde.gov.pk/students"


async def ensure_login(page, context, auth: FEMISAuth, force_manual: bool = False) -> bool:
    """Reuse session if valid; otherwise interactive or auto login, then save."""
    state = FEMISAuth.storage_state_path()
    if state and not force_manual:
        logger.info(f"Trying saved session: {SESSION_PATH}")
        if await auth.is_logged_in(page, STUDENTS_URL):
            logger.info("Saved session is valid — skipping CAPTCHA.")
            # Refresh cookie expiry so the next run can reuse it
            try:
                await auth.save_session(context)
            except Exception as e:
                logger.warning(f"Could not refresh session: {e}")
            return True
        logger.warning("Saved session expired or invalid.")

    if force_manual or not state:
        logger.info("Interactive login (you solve CAPTCHA in the browser)...")
        ok = await auth.login_interactive(page, LOGIN_URL)
    else:
        logger.info("Auto login with CAPTCHA solver...")
        ok = await auth.login(page, LOGIN_URL)

    if ok:
        await auth.save_session(context)
    return ok


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-id", type=int, default=None, help="Specific student ID to fill")
    parser.add_argument("--slow", type=int, default=300, help="Slow-mo delay in ms")
    parser.add_argument("--submit", action="store_true", help="Submit the form after filling all tabs")
    parser.add_argument("--manual-login", action="store_true", help="Force interactive CAPTCHA login")
    parser.add_argument("--logout", action="store_true", help="Delete saved session before running")
    args = parser.parse_args()

    if args.logout and SESSION_PATH.exists():
        SESSION_PATH.unlink()
        logger.info("Saved session deleted.")

    handler = WebFormHandler()

    if args.student_id:
        student = handler.read_by_id(args.student_id)
        if not student:
            logger.error(f"Student id={args.student_id} not found")
            return
    else:
        students = handler.read_all(limit=1)
        if not students:
            logger.error("No students in DB")
            return
        student = students[0]
    logger.info(f"Test student: {student.get('name')} | Class: {student.get('class_id')} | Section: {student.get('section_id')}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False, slow_mo=args.slow)
        storage = FEMISAuth.storage_state_path()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            storage_state=storage,
        )
        page = await context.new_page()

        auth = FEMISAuth(
            username=os.getenv("FEMIS_USERNAME", ""),
            password=os.getenv("FEMIS_PASSWORD", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            auto_solve_captcha=True,
            captcha_max_retries=5,
        )

        login_ok = await ensure_login(page, context, auth, force_manual=args.manual_login)
        if not login_ok:
            logger.error("Login failed")
            await browser.close()
            return

        logger.info("Login OK. Opening student form (create or edit if duplicate)...")
        filler = FormFiller()
        filler.attach_dialog_handler(page)
        mode = await filler.open_form(page, student)
        logger.info(f"Form mode: {mode}")

        logger.info("Filling form...")
        await filler.fill_student_form(page, student)

        if args.submit:
            logger.info("Submitting form...")
            ok = await filler.submit_form(page, student)
            logger.info(f"Submit result: {'SUCCESS' if ok else 'NOT CONFIRMED'}")
            if not ok:
                logger.error("Submit failed or success indicator not found")
                await page.screenshot(path="data/logs/submit_failed.png", full_page=True)
        else:
            logger.info("Fill complete (no --submit). Waiting 10s then closing browser...")

        await asyncio.sleep(10)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
