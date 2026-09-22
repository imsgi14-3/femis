"""Quick test: login manually, then fill one student from webform DB."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from playwright.async_api import async_playwright
from src.auth import FEMISAuth
from src.form_filler import FormFiller
from src.data_sources.webform_handler import WebFormHandler
from src.utils.logger import setup_logger
from dotenv import load_dotenv
import os

logger = setup_logger("test_bot")
load_dotenv()


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-id", type=int, default=None, help="Specific student ID to fill")
    parser.add_argument("--slow", type=int, default=300, help="Slow-mo delay in ms")
    args = parser.parse_args()

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
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        auth = FEMISAuth(
            username=os.getenv("FEMIS_USERNAME", ""),
            password=os.getenv("FEMIS_PASSWORD", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            auto_solve_captcha=True,
            captcha_max_retries=1,
        )

        logger.info("Logging in...")
        login_ok = await auth.login(page, "https://femis.fde.gov.pk/login")
        if not login_ok:
            logger.error("Login failed")
            await browser.close()
            return

        logger.info("Login OK. Navigating to Add Student...")
        await page.goto("https://femis.fde.gov.pk/students/create", wait_until="networkidle")
        await asyncio.sleep(2)

        logger.info("Filling form...")
        filler = FormFiller()
        await filler.fill_student_form(page, student)

        logger.info("Done! Waiting 10s then closing browser...")
        await asyncio.sleep(10)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
