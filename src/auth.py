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
                    await asyncio.sleep(1)
                else:
                    logger.warning(f"Gemini returned invalid CAPTCHA: {captcha_text}")
                    await page.click("#btn-refresh")
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"CAPTCHA solve error: {e}")
                await page.click("#btn-refresh")
                await asyncio.sleep(1)

        return False

    async def _solve_captcha_manual(self, page: Page) -> bool:
        """Pause and ask user to enter CAPTCHA manually."""
        print("\n" + "=" * 50)
        print("MANUAL CAPTCHA REQUIRED")
        print("Please look at the CAPTCHA in the browser and type it below.")
        print("=" * 50)

        captcha_text = input("Enter 4-digit CAPTCHA: ").strip()
        await page.fill("#captcha", captcha_text)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        if "login" not in page.url.lower():
            logger.info("Login successful (manual CAPTCHA)")
            return True

        logger.error("Login failed after manual CAPTCHA entry")
        return False
