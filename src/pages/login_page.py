"""Login page interactions for Betronix backoffice."""

from __future__ import annotations

import asyncio

import structlog

from src.config.models import Credentials
from src.pages.base import BasePage

logger = structlog.get_logger()


class LoginPage(BasePage):
    page_name = "login_page"

    async def login(self, credentials: Credentials) -> bool:
        """Perform login to Betronix backoffice.

        Form order: Company ID -> Username -> Password -> Sign In
        Returns True if login was successful.
        """
        login_url = f"{credentials.url.rstrip('/')}/login"
        logger.info("login_starting", url=login_url)

        await self.navigate(login_url)

        # Wait for the login form to actually render (SPA may load slowly)
        await self.page.wait_for_selector(
            "input[name='companyId']", state="visible", timeout=30000
        )
        await asyncio.sleep(1)

        # Fill login form in correct order: Company ID first
        await self.fill("company_code_input", credentials.company_code)
        await self.fill("username_input", credentials.username)
        await self.fill("password_input", credentials.password)

        # Click Sign In
        await self.click("login_button")

        # Wait for navigation after login
        try:
            await self.page.wait_for_url(
                lambda url: "login" not in url.lower(),
                timeout=15000,
            )
            logger.info("login_successful", url=self.page.url)
            return True
        except Exception:
            # Fallback: check URL manually
            await asyncio.sleep(3)
            current_url = self.page.url
            if "login" not in current_url.lower():
                logger.info("login_successful", url=current_url)
                return True
            logger.error("login_failed", reason="still_on_login_page")
            return False
