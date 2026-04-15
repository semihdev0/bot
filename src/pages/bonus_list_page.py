"""Bonus requests listing page for Betronix - extracts pending requests."""

from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation

import structlog
from playwright.async_api import Locator

from src.engine.models import BonusRequest
from src.pages.base import BasePage

logger = structlog.get_logger()


class BonusListPage(BasePage):
    page_name = "bonus_list_page"

    # Keywords that indicate a new bonus request notification
    _NOTIFICATION_KEYWORDS = ("yeni bonus", "bonus talebi", "new bonus")

    async def navigate_to_list(self, base_url: str, path: str) -> None:
        """Navigate to the bonus requests list page and select Beklemede tab."""
        url = f"{base_url.rstrip('/')}{path}"
        await self.navigate(url)
        await asyncio.sleep(2)  # Wait for table to load

        # Click the "Beklemede" filter tab so only pending requests are shown
        await self._click_pending_filter()
        logger.info("bonus_list_loaded", url=url)

    async def _click_pending_filter(self) -> None:
        """Click the 'Beklemede' filter tab at the top of the page."""
        try:
            pending_tab = self.locate("pending_filter")
            if await pending_tab.count() > 0:
                await pending_tab.click()
                await asyncio.sleep(2)
                logger.info("pending_filter_clicked")
            else:
                logger.warning("pending_filter_not_found")
        except Exception as e:
            logger.warning("pending_filter_click_failed", error=str(e))

    async def set_rows_per_page(self, count: int = 50) -> None:
        """Change the 'Satır' (rows per page) dropdown to show more rows.

        The backoffice defaults to 20 rows.  We switch to 50 so that
        a single page covers more requests before we need to paginate.
        """
        try:
            select_sel = self.selectors.get_nested(
                self.page_name, "rows_per_page", "rows_per_page_select"
            )
            locator = self._to_locator(select_sel)

            if await locator.first.count() > 0:
                await locator.first.select_option(str(count))
                await asyncio.sleep(2)  # Wait for table to re-render
                logger.info("rows_per_page_changed", count=count)
                return

            # Fallback: try clicking the current value and selecting from a list
            # Some UI frameworks use a custom dropdown instead of <select>
            current = self.page.locator(
                f"text='{count}', "
                "[class*='page-size'] [class*='option'], "
                "[class*='rows-per-page'] [class*='option']"
            )
            if await current.first.count() > 0:
                await current.first.click()
                await asyncio.sleep(2)
                logger.info("rows_per_page_changed_fallback", count=count)
                return

            logger.debug("rows_per_page_selector_not_found")
        except Exception as e:
            logger.warning("rows_per_page_change_failed", error=str(e))

    async def wait_for_notification(self, timeout_seconds: int = 300) -> bool:
        """Wait for a 'Yeni Bonus Talebi' toast notification to appear.

        The backoffice pushes a toast to the bottom-right corner whenever
        a new bonus request is submitted. Instead of polling, we watch
        for this DOM element and only refresh when it appears.

        Returns True if a notification was detected, False on timeout.
        """
        timeout_ms = timeout_seconds * 1000
        notification_sel = self.selectors.get(self.page_name, "new_request_notification")

        logger.debug("waiting_for_notification", timeout_seconds=timeout_seconds)

        try:
            # Wait for any toast/notification container to appear
            locator = self._to_locator(notification_sel)
            await locator.first.wait_for(state="visible", timeout=timeout_ms)

            # Verify it's actually a bonus notification by checking text
            text = (await locator.first.text_content() or "").lower()
            is_bonus = any(kw in text for kw in self._NOTIFICATION_KEYWORDS)

            if is_bonus:
                logger.info("bonus_notification_detected", text=text.strip()[:80])
                return True

            # It's some other notification, not a bonus one
            logger.debug("non_bonus_notification", text=text.strip()[:80])
            return False

        except Exception:
            # Timeout or element not found
            logger.debug("notification_wait_timeout", timeout_seconds=timeout_seconds)
            return False

    async def reload_page(self) -> None:
        """Reload the current page to reflect new requests."""
        await self.page.reload(wait_until="domcontentloaded")
        await asyncio.sleep(2)  # Wait for table to re-render
        await self._click_pending_filter()
        logger.info("page_reloaded")

    async def has_pending_notification(self) -> bool:
        """Quick check if a notification is currently visible (non-blocking).

        Used after processing to detect notifications that arrived
        while previous requests were being handled.
        """
        try:
            notification_sel = self.selectors.get(
                self.page_name, "new_request_notification"
            )
            locator = self._to_locator(notification_sel)
            if await locator.first.is_visible():
                text = (await locator.first.text_content() or "").lower()
                return any(kw in text for kw in self._NOTIFICATION_KEYWORDS)
        except Exception:
            pass
        return False

    async def get_pending_requests(self, max_count: int = 50) -> list[BonusRequest]:
        """Extract pending bonus requests from the current table page.

        Returns requests in REVERSE order (bottom-to-top = oldest first)
        so that the oldest pending request is processed first.
        """
        rows_locator = self.locate("request_rows")
        await asyncio.sleep(1)
        count = await rows_locator.count()
        logger.info("bonus_rows_found", count=count)

        requests: list[BonusRequest] = []
        for i in range(min(count, max_count)):
            try:
                row = rows_locator.nth(i)
                request = await self._extract_request_from_row(row, i)
                if request:
                    requests.append(request)
            except Exception as e:
                logger.warning("row_extraction_error", row_index=i, error=str(e))
                continue

        # Reverse: oldest (bottom of table) processed first
        requests.reverse()

        logger.info("pending_requests_extracted", count=len(requests))
        return requests

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    async def get_total_pages(self) -> int:
        """Read the current page indicator (e.g. '1 / 25') and return total pages."""
        try:
            indicator_sel = self.selectors.get_nested(
                self.page_name, "pagination", "page_indicator"
            )
            locator = self._to_locator(indicator_sel)
            # Try each matching element for text like "1 / 25" or "Sayfa 1/25"
            count = await locator.count()
            for i in range(count):
                text = (await locator.nth(i).text_content() or "").strip()
                match = re.search(r"(\d+)\s*/\s*(\d+)", text)
                if match:
                    total = int(match.group(2))
                    logger.debug("pagination_detected", total_pages=total)
                    return total
        except Exception as e:
            logger.debug("pagination_not_found", error=str(e))
        return 1  # No pagination = single page

    async def get_current_page(self) -> int:
        """Read the current page number from the indicator."""
        try:
            indicator_sel = self.selectors.get_nested(
                self.page_name, "pagination", "page_indicator"
            )
            locator = self._to_locator(indicator_sel)
            count = await locator.count()
            for i in range(count):
                text = (await locator.nth(i).text_content() or "").strip()
                match = re.search(r"(\d+)\s*/\s*(\d+)", text)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
        return 1

    async def go_to_last_page(self) -> bool:
        """Navigate to the last page of the table."""
        try:
            last_btn_sel = self.selectors.get_nested(
                self.page_name, "pagination", "last_page_button"
            )
            locator = self._to_locator(last_btn_sel)
            if await locator.first.count() > 0:
                await locator.first.click()
                await asyncio.sleep(1.5)
                logger.info("navigated_to_last_page", page=await self.get_current_page())
                return True
        except Exception as e:
            logger.debug("last_page_button_failed", error=str(e))
        return False

    async def go_to_prev_page(self) -> bool:
        """Navigate to the previous page. Returns False if already on page 1."""
        current = await self.get_current_page()
        if current <= 1:
            return False

        try:
            prev_btn_sel = self.selectors.get_nested(
                self.page_name, "pagination", "prev_page_button"
            )
            locator = self._to_locator(prev_btn_sel)
            if await locator.first.count() > 0:
                await locator.first.click()
                await asyncio.sleep(1.5)
                new_page = await self.get_current_page()
                logger.debug("navigated_to_prev_page", page=new_page)
                return new_page < current
        except Exception as e:
            logger.debug("prev_page_button_failed", error=str(e))
        return False

    async def go_to_first_page(self) -> bool:
        """Navigate back to the first page."""
        try:
            first_btn_sel = self.selectors.get_nested(
                self.page_name, "pagination", "first_page_button"
            )
            locator = self._to_locator(first_btn_sel)
            if await locator.first.count() > 0:
                await locator.first.click()
                await asyncio.sleep(1.5)
                return True
        except Exception:
            pass
        return False

    async def _extract_request_from_row(
        self, row: Locator, index: int
    ) -> BonusRequest | None:
        """Extract a BonusRequest from a single Betronix table row."""
        try:
            # Get full row text to extract data
            row_text = await row.text_content() or ""

            # Extract request ID from text (format: #1767785498823)
            id_match = re.search(r"#(\d+)", row_text)
            request_id = id_match.group(1) if id_match else f"row_{index}"

            # Extract column data using selectors
            player_sel = self.selectors.get_nested(
                self.page_name, "row_columns", "player_name"
            )
            username_sel = self.selectors.get_nested(
                self.page_name, "row_columns", "username"
            )
            bonus_type_sel = self.selectors.get_nested(
                self.page_name, "row_columns", "bonus_type"
            )
            amount_sel = self.selectors.get_nested(
                self.page_name, "row_columns", "requested_amount"
            )
            status_sel = self.selectors.get_nested(
                self.page_name, "row_columns", "status"
            )

            player_name = await self._safe_text(row, player_sel.value)
            username = await self._safe_text(row, username_sel.value)
            bonus_type = await self._safe_text(row, bonus_type_sel.value)
            amount_text = await self._safe_text(row, amount_sel.value)
            status = await self._safe_text(row, status_sel.value)

            # Clean username (remove @ prefix)
            username = username.replace("@", "").strip()

            # Parse amount - strip currency symbols and text
            requested_amount = self._parse_amount(amount_text)

            # Normalize bonus type for rule matching
            bonus_type_key = self._normalize_bonus_type(bonus_type)

            return BonusRequest(
                request_id=request_id,
                user_id=username,  # In Betronix, username serves as user_id
                username=player_name,
                bonus_type=bonus_type_key,
                requested_amount=requested_amount,
                status=status.strip(),
            )

        except Exception as e:
            logger.warning("request_parse_error", row_index=index, error=str(e))
            return None

    async def _safe_text(self, row: Locator, selector: str) -> str:
        """Safely extract text from a row cell, trying each selector option."""
        # Handle comma-separated fallback selectors
        for sel in selector.split(","):
            sel = sel.strip()
            try:
                locator = row.locator(sel).first
                if await locator.count() > 0:
                    text = await locator.text_content() or ""
                    return text.strip()
            except Exception:
                continue
        return ""

    @staticmethod
    def _parse_amount(text: str) -> Decimal | None:
        """Parse amount from text like '0 ₺', '150,50 TL', etc."""
        cleaned = (
            text.replace("₺", "")
            .replace("TL", "")
            .replace("$", "")
            .replace("€", "")
            .replace(",", ".")
            .replace(" ", "")
            .strip()
        )
        try:
            return Decimal(cleaned) if cleaned else None
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _normalize_bonus_type(raw: str) -> str:
        """Normalize bonus type text to a config-friendly key.

        E.g., '%15 KRİPTO YATIRIM BONUSU' -> 'kripto_yatirim_bonusu'
        """
        # Remove all percentage patterns (e.g. %15, %100, %300)
        cleaned = re.sub(r"%\d+\s*", "", raw)
        # Turkish char normalization
        tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
        cleaned = cleaned.translate(tr_map)
        # Lowercase, replace spaces with underscore
        return re.sub(r"\s+", "_", cleaned.strip().lower())

    async def find_row_by_request_id(self, request_id: str) -> Locator | None:
        """Find a table row by its request ID (#1234...) text.

        After navigating to a user profile and back, the row order may
        have changed (new requests inserted).  Instead of relying on a
        stale row index we search every row for the matching #ID.
        """
        rows_locator = self.locate("request_rows")
        count = await rows_locator.count()

        for i in range(count):
            row = rows_locator.nth(i)
            text = await row.text_content() or ""
            if f"#{request_id}" in text:
                logger.debug("row_found_by_id", request_id=request_id, row_index=i)
                return row

        logger.warning("row_not_found_by_id", request_id=request_id)
        return None

    async def get_row_action_buttons_by_id(
        self, request_id: str
    ) -> dict[str, Locator] | None:
        """Get action buttons for a row identified by its request ID.

        This is safe against table reordering – it always finds the
        correct row regardless of new inserts or removals.
        """
        row = await self.find_row_by_request_id(request_id)
        if row is None:
            return None

        approve_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "approve_button"
        )
        reject_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "reject_button"
        )
        view_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "view_button"
        )

        return {
            "approve": row.locator(approve_sel.value).first,
            "reject": row.locator(reject_sel.value).first,
            "view": row.locator(view_sel.value).first,
        }

    async def get_row_action_buttons(self, row_index: int) -> dict[str, Locator]:
        """Get action buttons by row index (legacy fallback)."""
        rows_locator = self.locate("request_rows")
        row = rows_locator.nth(row_index)

        approve_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "approve_button"
        )
        reject_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "reject_button"
        )
        view_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "view_button"
        )

        return {
            "approve": row.locator(approve_sel.value).first,
            "reject": row.locator(reject_sel.value).first,
            "view": row.locator(view_sel.value).first,
        }
