"""Browser lifecycle management with Playwright."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from src.config.models import BrowserConfig

logger = structlog.get_logger()


class BrowserManager:
    """Manages browser launch, context creation, and cleanup."""

    def __init__(self, config: BrowserConfig) -> None:
        self._config = config
        self._playwright = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        """Launch the browser."""
        logger.info("browser_starting", headless=self._config.headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._config.headless,
            slow_mo=self._config.slow_mo,
        )
        logger.info("browser_started")

    async def cleanup(self) -> None:
        """Close browser and playwright."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("browser_closed")

    async def new_context(self) -> BrowserContext:
        """Create a new browser context with configured viewport."""
        if self._browser is None:
            await self.start()
        assert self._browser is not None
        context = await self._browser.new_context(
            viewport={
                "width": self._config.viewport.width,
                "height": self._config.viewport.height,
            },
        )
        context.set_default_timeout(self._config.timeout)
        return context

    async def new_page(self) -> Page:
        """Create a new page in a fresh context."""
        context = await self.new_context()
        return await context.new_page()

    @asynccontextmanager
    async def managed_page(self) -> AsyncGenerator[Page, None]:
        """Context manager that yields a page and cleans up the context."""
        context = await self.new_context()
        page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()
