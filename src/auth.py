import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page
from src.ocr.gemini_client import GeminiClient
from src.utils.logger import setup_logger

logger = setup_logger("auth")


class FEMISAuth:
    """Handles FEMIS portal login including CAPTCHA solving."""

    def __init__(
        self,
        username: str,
        password: str,
        gemini_api_key: str = None,
        auto_solve_captcha: bool = True,
        captcha_max_retries: int = 3,
    ):
        self.username = username
        self.password = password
        self.auto_solve_captcha = auto_solve_captcha
        self.captcha_max_retries = captcha_max_retries
        self.gemini = GeminiClient(api_key=gemini_api_key) if gemini_api_key else None

    async def login(self, page: Page, login_url: str) -> bool:
        """Navigate to login page and authenticate. Returns True if successful."""
        logger.info(f"Navigating to login: {login_url}")
        await page.goto(login_url, wait_until="networkidle")

        await page.fill("#username", self.username)
        await page.fill("#password", self.password)
        logger.info("Credentials entered.")

        if self.auto_solve_captcha and self.gemini:
            success = await self._solve_captcha_auto(page)
            if success:
                return True
            logger.warning("Auto CAPTCHA solve failed, falling back to manual...")

        return await self._solve_captcha_manual(page)

    async def _solve_captcha_auto(self, page: Page) -> bool:
        """Attempt to solve CAPTCHA using Gemini Vision API."""
        for attempt in range(1, self.captcha_max_retries + 1):
            logger.info(f"CAPTCHA auto-solve attempt {attempt}/{self.captcha_max_retries}")

            captcha_img = page.locator(".captcha-code img")
            captcha_path = Path("data/logs") / f"captcha_attempt_{attempt}.png"
            captcha_path.parent.mkdir(parents=True, exist_ok=True)
            await captcha_img.screenshot(path=str(captcha_path))

            try:
                captcha_text = self.gemini.solve_captcha(str(captcha_path))
                logger.info(f"Gemini read CAPTCHA as: {captcha_text}")

                if len(captcha_text) == 4 and captcha_text.isdigit():
                    await page.fill("#captcha", captcha_text)
                    await page.click("button[type='submit']")
                    await page.wait_for_load_state("networkidle")

                    if "login" not in page.url.lower():
                        logger.info("Login successful (auto-solved CAPTCHA)")
                        return True

                    logger.warning(f"CAPTCHA attempt {attempt} failed, refreshing...")
                    await page.click("#btn-refresh")
                    await asyncio.sleep(2)
                else:
                    logger.warning(f"Gemini returned invalid CAPTCHA: {captcha_text}")
                    await page.click("#btn-refresh")
                    await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"CAPTCHA solve error: {e}")
                # Wait longer on rate limit errors
                wait_time = 10 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 2
                logger.info(f"Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                try:
                    await page.click("#btn-refresh")
                except Exception:
                    pass
                await asyncio.sleep(1)

        return False

    async def _solve_captcha_manual(self, page: Page) -> bool:
        """Pause and ask user to enter CAPTCHA manually.
        Checks data/logs/captcha_code.txt for content.
        """
        captcha_path = Path("data/logs") / "captcha_code.txt"
        captcha_path.parent.mkdir(parents=True, exist_ok=True)

        # Take screenshot of CAPTCHA for user reference
        captcha_img = page.locator(".captcha-code img")
        if await captcha_img.count() > 0:
            screenshot_path = captcha_path.parent / "captcha_current.png"
            await captcha_img.screenshot(path=str(screenshot_path))
            logger.info(f"CAPTCHA screenshot saved to {screenshot_path}")

        print("\n" + "=" * 50)
        print("MANUAL CAPTCHA REQUIRED")
        print("Please look at the CAPTCHA in the browser.")
        print(f"Write the CAPTCHA code to: {captcha_path}")
        print("=" * 50)

        # Check if file already has content
        if captcha_path.exists():
            existing = captcha_path.read_text(encoding="utf-8").strip()
            if existing and len(existing) >= 4:
                captcha_text = existing
                logger.info(f"Read CAPTCHA from file: {captcha_text}")
            else:
                # Poll for file content
                logger.info(f"Waiting for CAPTCHA in {captcha_path}...")
                captcha_text = ""
                for _ in range(120):  # Wait up to 2 minutes
                    await asyncio.sleep(1)
                    if captcha_path.exists():
                        content = captcha_path.read_text(encoding="utf-8").strip()
                        if content and len(content) >= 4:
                            captcha_text = content
                            logger.info(f"Read CAPTCHA from file: {captcha_text}")
                            break
                if not captcha_text:
                    logger.error("Timeout waiting for CAPTCHA file")
                    return False
        else:
            logger.info(f"Waiting for CAPTCHA in {captcha_path}...")
            captcha_text = ""
            for _ in range(120):
                await asyncio.sleep(1)
                if captcha_path.exists():
                    content = captcha_path.read_text(encoding="utf-8").strip()
                    if content and len(content) >= 4:
                        captcha_text = content
                        logger.info(f"Read CAPTCHA from file: {captcha_text}")
                        break
            if not captcha_text:
                logger.error("Timeout waiting for CAPTCHA file")
                return False

        await page.fill("#captcha", captcha_text)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        if "login" not in page.url.lower():
            logger.info("Login successful (manual CAPTCHA)")
            # Clear the file for next time
            captcha_path.write_text("", encoding="utf-8")
            return True

        logger.error("Login failed after manual CAPTCHA entry")
        return False
