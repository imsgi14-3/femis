import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext
from src.ocr.gemini_client import GeminiClient
from src.ocr.local_captcha import solve_local
from src.utils.logger import setup_logger

logger = setup_logger("auth")

SESSION_PATH = Path("data/logs/femis_session.json")


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

    @staticmethod
    def session_exists() -> bool:
        return SESSION_PATH.exists() and SESSION_PATH.stat().st_size > 2

    @staticmethod
    def storage_state_path() -> str | None:
        return str(SESSION_PATH) if FEMISAuth.session_exists() else None

    async def save_session(self, context: BrowserContext) -> None:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(SESSION_PATH))
        logger.info(f"Session saved to {SESSION_PATH}")

    async def is_logged_in(self, page: Page, students_url: str) -> bool:
        """Check whether the current session is still authenticated."""
        try:
            await page.goto(students_url, wait_until="domcontentloaded", timeout=25000)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            url = page.url.lower()
            logger.info(f"Session check URL: {page.url}")
            if "login" in url:
                return False
            # Logged-in pages typically show nav/dashboard, not the login form
            login_form = page.locator("#username, #password, form[action*='login']")
            if await login_form.count() > 0 and await login_form.first.is_visible():
                return False
            # Positive signal: students list / nav present
            if await page.locator("table, .card, nav, .navbar").count() > 0:
                return True
            # Fallback: not on login and no visible login form
            return "login" not in url
        except Exception as e:
            logger.warning(f"Session check failed: {e}")
            return False

    async def login_interactive(
        self,
        page: Page,
        login_url: str,
        prefill: bool = True,
        timeout_s: int = 180,
    ) -> bool:
        """Open login page and wait for the user to complete it in the browser.

        Prefills username/password so only the CAPTCHA needs a human.
        Returns True once the URL leaves /login.
        """
        logger.info(f"Interactive login: opening {login_url}")
        await page.goto(login_url, wait_until="networkidle")

        if prefill:
            try:
                if await page.locator("#username").count():
                    await page.fill("#username", self.username)
                if await page.locator("#password").count():
                    await page.fill("#password", self.password)
                logger.info("Username/password prefilled — solve CAPTCHA in the browser.")
            except Exception as e:
                logger.warning(f"Prefill failed: {e}")

        print("\n" + "=" * 50)
        print("MANUAL LOGIN IN BROWSER")
        print("Solve the CAPTCHA and click login.")
        print("The bot will continue automatically once logged in.")
        print("=" * 50)

        for i in range(timeout_s):
            await asyncio.sleep(1)
            url = page.url.lower()
            if "login" not in url and url.rstrip("/") != "":
                # Confirm not still showing login form on a same-origin redirect
                try:
                    still_login = False
                    if await page.locator("#password").count() > 0:
                        if await page.locator("#password").first.is_visible():
                            still_login = True
                except Exception:
                    still_login = False
                if not still_login:
                    logger.info(f"Interactive login successful ({i + 1}s). URL={page.url}")
                    return True
            if i and i % 15 == 0:
                logger.info(f"Still waiting for manual login... ({i}s / {timeout_s}s)")

        logger.error("Timeout waiting for manual login")
        return False

    async def _refill_credentials(self, page: Page) -> None:
        """Portal clears username/password after a failed CAPTCHA — restore them."""
        try:
            await page.fill("#username", self.username)
            await page.fill("#password", self.password)
        except Exception as e:
            logger.warning(f"Could not refill credentials: {e}")

    async def login(self, page: Page, login_url: str) -> bool:
        """Navigate to login page and authenticate. Returns True if successful."""
        logger.info(f"Navigating to login: {login_url}")
        await page.goto(login_url, wait_until="networkidle")

        await self._refill_credentials(page)
        logger.info("Credentials entered.")

        if self.auto_solve_captcha:
            success = await self._solve_captcha_auto(page)
            if success:
                return True
            logger.warning("Auto CAPTCHA solve failed, falling back to manual...")

        return await self._solve_captcha_manual(page)

    async def _solve_captcha_auto(self, page: Page) -> bool:
        """Attempt to solve CAPTCHA: local OCR first, Gemini fallback."""
        for attempt in range(1, self.captcha_max_retries + 1):
            logger.info(f"CAPTCHA auto-solve attempt {attempt}/{self.captcha_max_retries}")

            # Failed submits clear the login fields — always re-enter them first.
            await self._refill_credentials(page)

            captcha_img = page.locator(".captcha-code img")
            captcha_path = Path("data/logs") / f"captcha_attempt_{attempt}.png"
            captcha_path.parent.mkdir(parents=True, exist_ok=True)
            await captcha_img.screenshot(path=str(captcha_path))

            captcha_text = ""
            # Local OCR first (free, no quota)
            try:
                captcha_text = solve_local(str(captcha_path))
                if captcha_text:
                    logger.info(f"Local OCR read CAPTCHA as: {captcha_text}")
            except Exception as e:
                logger.warning(f"Local OCR error: {e}")

            # Gemini fallback if local failed or returned invalid
            if (not captcha_text or len(captcha_text) != 4 or not captcha_text.isdigit()) and self.gemini:
                try:
                    captcha_text = self.gemini.solve_captcha(str(captcha_path))
                    logger.info(f"Gemini read CAPTCHA as: {captcha_text}")
                except Exception as e:
                    logger.error(f"Gemini CAPTCHA solve error: {e}")
                    wait_time = 10 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 2
                    logger.info(f"Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                    captcha_text = ""

            if captcha_text and len(captcha_text) == 4 and captcha_text.isdigit():
                await self._refill_credentials(page)
                await page.fill("#captcha", captcha_text)
                await page.click("button[type='submit']")
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                if "login" not in page.url.lower():
                    logger.info("Login successful (auto-solved CAPTCHA)")
                    return True

                logger.warning(f"CAPTCHA attempt {attempt} failed, refreshing...")
                try:
                    await page.click("#btn-refresh")
                except Exception:
                    pass
                await asyncio.sleep(2)
                await self._refill_credentials(page)
            else:
                logger.warning(f"Invalid CAPTCHA result: {captcha_text!r}")
                try:
                    await page.click("#btn-refresh")
                except Exception:
                    pass
                await asyncio.sleep(2)
                await self._refill_credentials(page)

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
                for _ in range(600):  # Wait up to 10 minutes
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
            for _ in range(600):
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

        await self._refill_credentials(page)
        await page.fill("#captcha", captcha_text)
        await page.click("button[type='submit']")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        if "login" not in page.url.lower():
            logger.info("Login successful (manual CAPTCHA)")
            # Clear the file for next time
            captcha_path.write_text("", encoding="utf-8")
            return True

        logger.error("Login failed after manual CAPTCHA entry")
        await self._refill_credentials(page)
        return False
