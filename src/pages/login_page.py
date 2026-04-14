"""Login page interactions."""

from __future__ import annotations

import structlog

from src.config.models import Credentials
from src.pages.base import BasePage

logger = structlog.get_logger()


class LoginPage(BasePage):
    page_name = "login_page"

    async def login(self, credentials: Credentials) -> bool:
        """Perform login with username, password, and company code.

        Returns True if login was successful.
        """
        logger.info("login_starting", url=credentials.url)

        await self.navigate(credentials.url)

        # Fill login form
        await self.fill("username_input", credentials.username)
        await self.fill("password_input", credentials.password)
        await self.fill("company_code_input", credentials.company_code)

        # Submit
        await self.click("login_button")

        # Wait for navigation after login
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            # Check if we're still on the login page (login failed)
            current_url = self.page.url
            if "login" in current_url.lower():
                logger.error("login_failed", reason="still_on_login_page")
                return False
            logger.info("login_successful")
            return True
        except Exception as e:
            logger.error("login_error", error=str(e))
            return False
