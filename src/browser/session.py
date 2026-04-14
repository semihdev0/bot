"""Session management - login, validation, and re-login on expiry."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import structlog
from playwright.async_api import Page

from src.browser.manager import BrowserManager
from src.config.loader import AppConfig
from src.config.selectors import SelectorRegistry
from src.pages.login_page import LoginPage
from src.utils.exceptions import SessionExpiredError

logger = structlog.get_logger()


class SessionManager:
    """Manages the browser session lifecycle including login and re-login."""

    def __init__(self, browser: BrowserManager, config: AppConfig) -> None:
        self.browser = browser
        self.config = config
        self.page: Page | None = None
        self._login_time: datetime | None = None
        self._context = None

    @property
    def selectors(self) -> SelectorRegistry:
        return self.config.selectors

    async def ensure_logged_in(self) -> Page:
        """Ensure we have a valid session. Login or re-login if needed."""
        if self.page is None or self._needs_relogin():
            await self._login()
        assert self.page is not None
        return self.page

    def _needs_relogin(self) -> bool:
        """Check if session has exceeded the relogin interval."""
        if self._login_time is None:
            return True
        elapsed = datetime.now() - self._login_time
        max_age = timedelta(
            minutes=self.config.settings.session.relogin_interval_minutes
        )
        return elapsed > max_age

    async def _login(self) -> None:
        """Perform login with retry logic."""
        # Clean up old context if exists
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass

        max_retries = self.config.settings.session.max_login_retries
        delay = self.config.settings.session.login_retry_delay_seconds

        for attempt in range(1, max_retries + 1):
            try:
                self._context = await self.browser.new_context()
                self.page = await self._context.new_page()

                login_page = LoginPage(self.page, self.selectors)
                success = await login_page.login(self.config.credentials)

                if success:
                    self._login_time = datetime.now()
                    logger.info("session_established", attempt=attempt)
                    return

                logger.warning(
                    "login_attempt_failed",
                    attempt=attempt,
                    max_retries=max_retries,
                )

            except Exception as e:
                logger.error(
                    "login_exception",
                    attempt=attempt,
                    error=str(e),
                )

            # Cleanup failed attempt
            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass

            if attempt < max_retries:
                await asyncio.sleep(delay)

        raise SessionExpiredError(
            f"Failed to login after {max_retries} attempts"
        )

    async def close(self) -> None:
        """Close the current session."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        self.page = None
        self._login_time = None
        self._context = None
