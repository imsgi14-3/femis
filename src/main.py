import asyncio
import json
import yaml
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import os

from playwright.async_api import async_playwright
from src.auth import FEMISAuth, SESSION_PATH
from src.form_filler import FormFiller
from src.data_sources.photo_handler import PhotoHandler
from src.data_sources.excel_handler import ExcelHandler
from src.utils.logger import setup_logger

logger = setup_logger("main")
load_dotenv()


class FEMISBot:
    """Main orchestrator — reads data, logs in, fills forms, reports results."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config = self._load_config(config_path)
        self.auth = FEMISAuth(
            username=os.getenv("FEMIS_USERNAME", ""),
            password=os.getenv("FEMIS_PASSWORD", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            auto_solve_captcha=self.config["captcha"]["auto_solve"],
            captcha_max_retries=self.config["captcha"]["max_retries"],
        )
        self.filler = FormFiller()
        self.submit = False
        self.photo_handler = PhotoHandler(
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_model=self.config["ocr"]["gemini_model"],
        )
        self.excel_handler = ExcelHandler()
        self.results = []

    def _load_config(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def load_student_data(self, source: str, source_type: str = "auto") -> list[dict]:
        """Load student data from various sources."""
        source_path = Path(source)

        if source_type == "auto":
            if source_path.is_dir():
                source_type = "photos"
            elif source_path.suffix.lower() in {".xlsx", ".xls", ".csv"}:
                source_type = "excel"
            else:
                raise ValueError(f"Cannot auto-detect source type for: {source}")

        if source_type == "photos":
            logger.info(f"Loading student data from photos in: {source}")
            return self.photo_handler.process_directory(source)
        elif source_type == "excel":
            logger.info(f"Loading student data from spreadsheet: {source}")
            return self.excel_handler.read_file(source)
        elif source_type == "google_sheets":
            from src.data_sources.google_sheets import GoogleSheetsReader
            reader = GoogleSheetsReader(
                credentials_path=os.getenv("GOOGLE_SHEETS_CREDENTIALS"),
                spreadsheet_id=os.getenv("GOOGLE_FORMS_SPREADSHEET_ID"),
            )
            return reader.read_all()
        elif source_type == "webform":
            from src.data_sources.webform_handler import WebFormHandler
            handler = WebFormHandler()
            return handler.read_all()
        else:
            raise ValueError(f"Unknown source type: {source_type}")

    async def run(self, source: str, source_type: str = "auto", dry_run: bool = False, submit: bool = False):
        """Main entry point — process all students from the given source."""
        self.submit = submit
        students = self.load_student_data(source, source_type)
        if not students:
            logger.error("No student data found. Exiting.")
            return

        logger.info(f"Loaded {len(students)} students. Starting processing...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                channel=self.config.get("browser", {}).get("channel", "msedge"),
                headless=False,
                slow_mo=self.config["portal"]["slow_mo"],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                storage_state=FEMISAuth.storage_state_path(),
            )
            page = await context.new_page()
            self.filler.attach_dialog_handler(page)

            try:
                students_url = self.config["portal"].get("students_url", "")
                login_url = self.config["portal"]["login_url"]
                logged_in = False

                if FEMISAuth.session_exists() and students_url:
                    logger.info("Checking saved session...")
                    logged_in = await self.auth.is_logged_in(page, students_url)
                    if logged_in:
                        logger.info("Saved session valid — skipping CAPTCHA.")
                    else:
                        logger.warning("Saved session invalid; logging in again.")

                if not logged_in:
                    # Prefer interactive login (human solves CAPTCHA once)
                    logger.info("Interactive login — solve CAPTCHA in the browser...")
                    logged_in = await self.auth.login_interactive(page, login_url)
                    if not logged_in:
                        logger.info("Falling back to auto CAPTCHA solve...")
                        logged_in = await self.auth.login(page, login_url)

                if not logged_in:
                    logger.error("Login failed. Aborting.")
                    return

                await self.auth.save_session(context)

                logger.info("Login successful. Navigating to Add Student page...")
                await page.goto(self.config["portal"]["create_url"], wait_until="networkidle")

                for i, student in enumerate(students, 1):
                    logger.info(f"\n{'='*60}")
                    logger.info(f"Processing student {i}/{len(students)}: {student.get('student_name', 'Unknown')}")
                    logger.info(f"{'='*60}")

                    if student.get("_status") == "error":
                        logger.warning(f"Skipping student with error: {student.get('_error')}")
                        self.results.append({
                            "student": student.get("student_name", "Unknown"),
                            "status": "skipped",
                            "reason": student.get("_error"),
                        })
                        continue

                    if dry_run:
                        logger.info("[DRY RUN] Would fill form with:")
                        for k, v in student.items():
                            if v is not None:
                                logger.info(f"  {k}: {v}")
                        self.results.append({
                            "student": student.get("student_name", "Unknown"),
                            "status": "dry_run",
                        })
                        continue

                    try:
                        await self.filler.fill_student_form(page, student)
                        submitted = False
                        if getattr(self, "submit", False):
                            submitted = await self.filler.submit_form(page, student)
                        self.results.append({
                            "student": student.get("student_name") or student.get("name", "Unknown"),
                            "status": "success" if (submitted or not getattr(self, "submit", False)) else "submit_failed",
                            "submitted": submitted if getattr(self, "submit", False) else None,
                        })
                    except Exception as e:
                        logger.error(f"Error filling form for student: {e}")
                        if self.config["batch"]["screenshot_on_error"]:
                            screenshot_path = f"data/logs/error_{i}_{datetime.now().strftime('%H%M%S')}.png"
                            await page.screenshot(path=screenshot_path)
                            logger.info(f"Screenshot saved: {screenshot_path}")
                        self.results.append({
                            "student": student.get("student_name", "Unknown"),
                            "status": "error",
                            "reason": str(e),
                        })

                    delay = self.config["batch"]["delay_between_students"]
                    if delay and i < len(students):
                        logger.info(f"Waiting {delay}ms before next student...")
                        await asyncio.sleep(delay / 1000)

            finally:
                await browser.close()

        self._save_report()

    def _save_report(self):
        """Save a summary report of all processed students."""
        report_path = Path(self.config["output"]["directory"])
        report_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        json_path = report_path / f"report_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        success = sum(1 for r in self.results if r["status"] == "success")
        errors = sum(1 for r in self.results if r["status"] == "error")
        skipped = sum(1 for r in self.results if r["status"] == "skipped")

        summary = f"\n{'='*60}\nBATCH COMPLETE\n{'='*60}\n"
        summary += f"Total: {len(self.results)} | Success: {success} | Errors: {errors} | Skipped: {skipped}\n"
        summary += f"Report saved: {json_path}\n"
        print(summary)
        logger.info(summary)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="FEMIS Student Data Entry Bot")
    parser.add_argument("source", help="Path to data source (image directory, Excel/CSV file)")
    parser.add_argument("--type", choices=["photos", "excel", "google_sheets", "webform", "auto"], default="auto")
    parser.add_argument("--dry-run", action="store_true", help="Load data but don't fill forms")
    parser.add_argument("--submit", action="store_true", help="Submit each form after filling")
    parser.add_argument("--config", default="config/settings.yaml", help="Config file path")
    args = parser.parse_args()

    bot = FEMISBot(config_path=args.config)
    await bot.run(args.source, source_type=args.type, dry_run=args.dry_run, submit=args.submit)


if __name__ == "__main__":
    asyncio.run(main())
