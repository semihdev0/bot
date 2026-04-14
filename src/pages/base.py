"""Base page object with common helpers."""

from __future__ import annotations

import structlog
from playwright.async_api import Locator, Page

from src.config.models import SelectorEntry
from src.config.selectors import SelectorRegistry

logger = structlog.get_logger()


class BasePage:
    """Base class for all page objects.

    Uses the SelectorRegistry to resolve logical element names
    into Playwright locators. No hardcoded selectors in code.
    """

    page_name: str = ""

    def __init__(self, page: Page, selectors: SelectorRegistry) -> None:
        self.page = page
        self.selectors = selectors

    def _to_locator(self, entry: SelectorEntry) -> Locator:
        """Convert a SelectorEntry to a Playwright Locator."""
        if entry.strategy == "css":
            return self.page.locator(entry.value)
        elif entry.strategy == "xpath":
            return self.page.locator(f"xpath={entry.value}")
        elif entry.strategy == "text":
            return self.page.get_by_text(entry.value)
        elif entry.strategy == "role":
            role = entry.role or "button"
            return self.page.get_by_role(role, name=entry.value)
        raise ValueError(f"Unknown selector strategy: {entry.strategy}")

    def locate(self, element_name: str) -> Locator:
        """Get a Playwright locator for a logical element name."""
        entry = self.selectors.get(self.page_name, element_name)
        return self._to_locator(entry)

    def locate_nested(self, group: str, element_name: str) -> Locator:
        """Get a locator from a nested group (e.g., row_columns.username)."""
        entry = self.selectors.get_nested(self.page_name, group, element_name)
        return self._to_locator(entry)

    async def click(self, element_name: str) -> None:
        """Click an element by its logical name."""
        locator = self.locate(element_name)
        await locator.click()
        logger.debug("element_clicked", page=self.page_name, element=element_name)

    async def fill(self, element_name: str, value: str) -> None:
        """Fill an input element by its logical name."""
        locator = self.locate(element_name)
        await locator.fill(value)
        logger.debug("element_filled", page=self.page_name, element=element_name)

    async def extract_text(self, element_name: str) -> str:
        """Extract text content from an element."""
        locator = self.locate(element_name)
        text = await locator.text_content() or ""
        return text.strip()

    async def extract_text_nested(self, group: str, element_name: str) -> str:
        """Extract text content from a nested element."""
        locator = self.locate_nested(group, element_name)
        text = await locator.text_content() or ""
        return text.strip()

    async def is_visible(self, element_name: str, timeout: int = 5000) -> bool:
        """Check if an element is visible on the page."""
        try:
            locator = self.locate(element_name)
            await locator.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    async def navigate(self, url: str) -> None:
        """Navigate to a URL and wait for the page to load."""
        await self.page.goto(url, wait_until="domcontentloaded")
        logger.debug("navigated", url=url)
