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
        """Navigate to the bonus requests list page."""
        url = f"{base_url.rstrip('/')}{path}"
        await self.navigate(url)
        await asyncio.sleep(2)  # Wait for table to load
        # Reinstall observer after navigation (JS state lost)
        await self.install_toast_observer()
        logger.info("bonus_list_loaded", url=url)

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

    async def install_toast_observer(self) -> None:
        """Install a MutationObserver that detects Sonner toast notifications.

        The backoffice uses the Sonner library for toasts.  Toasts are
        rendered as ``<ol data-sonner-toaster>`` with ``<li>`` children.
        Playwright's ``wait_for(state='visible')`` fails because the
        container has ``--front-toast-height: 0px``.  Instead we watch
        for new DOM nodes whose text contains bonus-related keywords.
        """
        await self.page.evaluate(
            """() => {
            window.__bonusToastDetected = false;
            window.__bonusToastText = '';
            if (window.__bonusObserver) {
                window.__bonusObserver.disconnect();
            }
            window.__bonusObserver = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    for (const n of m.addedNodes) {
                        if (n.nodeType === 1) {
                            const txt = (n.textContent || '').toLowerCase();
                            if (txt.includes('yeni bonus') || txt.includes('new bonus')) {
                                window.__bonusToastDetected = true;
                                window.__bonusToastText = (n.textContent || '').substring(0, 200);
                            }
                        }
                    }
                }
            });
            window.__bonusObserver.observe(document.body, {
                childList: true,
                subtree: true
            });
        }"""
        )
        logger.debug("toast_observer_installed")

    async def wait_for_notification(self, timeout_seconds: int = 300) -> bool:
        """Wait for the 'Yeni Bonus Talebi' Sonner toast notification.

        Uses a MutationObserver (installed via ``install_toast_observer``)
        that sets ``window.__bonusToastDetected`` when a new DOM node
        containing 'yeni bonus' or 'new bonus' is added.  We poll this
        flag every 2 seconds.

        Returns True if a notification was detected, False on timeout.
        """
        logger.debug("waiting_for_notification", timeout_seconds=timeout_seconds)

        # Make sure observer is installed
        observer_exists = await self.page.evaluate(
            "() => typeof window.__bonusObserver !== 'undefined'"
        )
        if not observer_exists:
            await self.install_toast_observer()

        # Reset the flag before waiting
        await self.page.evaluate("() => { window.__bonusToastDetected = false; }")

        elapsed = 0
        poll_interval = 2  # seconds

        while elapsed < timeout_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            try:
                detected = await self.page.evaluate(
                    "() => window.__bonusToastDetected"
                )
                if detected:
                    toast_text = await self.page.evaluate(
                        "() => window.__bonusToastText || ''"
                    )
                    logger.info("notification_detected", text=toast_text[:100])
                    # Reset for next cycle
                    await self.page.evaluate(
                        "() => { window.__bonusToastDetected = false; window.__bonusToastText = ''; }"
                    )
                    return True
            except Exception:
                # Page might have navigated away – reinstall observer
                logger.debug("observer_check_failed_reinstalling")
                try:
                    await self.install_toast_observer()
                except Exception:
                    pass

        logger.debug("notification_wait_timeout", timeout_seconds=timeout_seconds)
        return False

    async def reload_page(self) -> None:
        """Reload the current page to reflect new requests."""
        await self.page.reload(wait_until="domcontentloaded")
        await asyncio.sleep(2)  # Wait for table to re-render
        # Reinstall observer – page reload destroys JS state
        await self.install_toast_observer()
        logger.info("page_reloaded")

    async def has_pending_notification(self) -> bool:
        """Quick check if a notification is currently visible (non-blocking)."""
        try:
            # Check MutationObserver flag first
            detected = await self.page.evaluate(
                "() => window.__bonusToastDetected === true"
            )
            if detected:
                await self.page.evaluate(
                    "() => { window.__bonusToastDetected = false; window.__bonusToastText = ''; }"
                )
                return True

            # Fallback: check if Sonner toaster has visible toast content
            has_sonner = await self.page.evaluate(
                """() => {
                const toaster = document.querySelector('[data-sonner-toaster]');
                if (!toaster) return false;
                const items = toaster.querySelectorAll('li');
                return items.length > 0;
            }"""
            )
            return has_sonner
        except Exception:
            return False

    # Status values that indicate a pending (actionable) request
    _PENDING_STATUSES = ("pending", "beklemede")

    async def get_pending_requests(self, max_count: int = 50) -> list[BonusRequest]:
        """Extract pending bonus requests from the current table page.

        Only rows with "Pending" / "Beklemede" status are included.
        Rows that are already "Approved", "Rejected", etc. are skipped
        because they only have a view button (no approve/reject).

        Returns requests in REVERSE order (bottom-to-top = oldest first)
        so that the oldest pending request is processed first.
        """
        rows_locator = self.locate("request_rows")
        await asyncio.sleep(1)
        count = await rows_locator.count()
        logger.info("bonus_rows_found", count=count)

        requests: list[BonusRequest] = []
        skipped = 0
        for i in range(min(count, max_count)):
            try:
                row = rows_locator.nth(i)
                request = await self._extract_request_from_row(row, i)
                if request:
                    # Only include pending requests
                    if request.status.lower() in self._PENDING_STATUSES:
                        requests.append(request)
                    else:
                        skipped += 1
                        logger.debug(
                            "row_skipped_not_pending",
                            row_index=i,
                            status=request.status,
                            request_id=request.request_id,
                        )
            except Exception as e:
                logger.warning("row_extraction_error", row_index=i, error=str(e))
                continue

        # Reverse: oldest (bottom of table) processed first
        requests.reverse()

        logger.info(
            "pending_requests_extracted",
            count=len(requests),
            skipped_non_pending=skipped,
        )
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
            logger.debug(
                "bonus_type_normalized",
                raw=bonus_type[:80],
                key=bonus_type_key,
            )

            # The #number in the PLAYER column is the player ID.
            # Profile URL is /players/{player_id}, so we use this as user_id.
            # For request tracking we need a unique key per request,
            # so we combine player_id with bonus_type.
            player_id = request_id  # #number = player ID

            return BonusRequest(
                request_id=f"{player_id}_{bonus_type_key}",
                user_id=player_id,  # Numeric ID for /players/{id} URL
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
        """Find a table row by its player ID (#1234...) text.

        The request_id format is '{player_id}_{bonus_type}'.
        We extract the player_id part and search for #{player_id} in rows.
        """
        # Extract player_id from composite request_id
        player_id = request_id.split("_")[0] if "_" in request_id else request_id

        rows_locator = self.locate("request_rows")
        count = await rows_locator.count()

        for i in range(count):
            row = rows_locator.nth(i)
            text = await row.text_content() or ""
            if f"#{player_id}" in text:
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

        Uses a cascading strategy:
        1. Try configured CSS selectors (color-class based)
        2. Fallback: find ALL buttons in the last cell and assign by
           position (1st=approve, 2nd=reject, 3rd=view)
        """
        row = await self.find_row_by_request_id(request_id)
        if row is None:
            return None

        # Strategy 1: configured selectors
        approve_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "approve_button"
        )
        reject_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "reject_button"
        )

        approve_loc = row.locator(approve_sel.value).first
        reject_loc = row.locator(reject_sel.value).first

        approve_ok = await approve_loc.count() > 0
        reject_ok = await reject_loc.count() > 0

        if approve_ok and reject_ok:
            return {
                "approve": approve_loc,
                "reject": reject_loc,
                "view": row.locator("td:last-child button").nth(2),
            }

        # Strategy 2: find all clickable elements in the last cell by position
        # Some panels use <button>, others use <a> or <div role="button">
        last_cell_buttons = row.locator(
            "td:last-child button, td:last-child a[role='button'], "
            "td:last-child [role='button']"
        )
        btn_count = await last_cell_buttons.count()

        if btn_count == 0:
            # Try just buttons in last cell
            last_cell_buttons = row.locator("td:last-child button")
            btn_count = await last_cell_buttons.count()

        if btn_count == 0:
            # Try broader: last 2 cells
            last_cell_buttons = row.locator("td:nth-last-child(-n+2) button")
            btn_count = await last_cell_buttons.count()

        logger.info(
            "action_buttons_fallback",
            request_id=request_id,
            button_count=btn_count,
        )

        if btn_count == 0:
            # Debug: log what's actually in the last cell
            try:
                last_cell_html = await row.locator("td:last-child").first.evaluate(
                    "e => e.innerHTML"
                )
                logger.warning(
                    "no_action_buttons_found",
                    request_id=request_id,
                    last_cell_html=last_cell_html[:300],
                )
            except Exception:
                pass
            return None

        # Debug: log button details for selector tuning
        for i in range(min(btn_count, 4)):
            try:
                btn = last_cell_buttons.nth(i)
                cls = await btn.get_attribute("class") or ""
                variant = await btn.get_attribute("data-variant") or ""
                tag = await btn.evaluate("e => e.tagName") or ""
                inner = (await btn.text_content() or "").strip()[:20]
                logger.info(
                    "action_button_discovered",
                    index=i,
                    tag=tag,
                    variant=variant,
                    text=inner,
                    class_preview=cls[:120],
                )
            except Exception:
                pass

        # Typical order: approve (green/check), reject (red/x), view (eye)
        # SAFETY: Never assign the same button for both approve and reject.
        # If only 1 button exists, set reject to None to prevent accidental approve.
        result = {
            "approve": last_cell_buttons.nth(0),
            "reject": last_cell_buttons.nth(1) if btn_count >= 2 else None,
            "view": last_cell_buttons.nth(2) if btn_count >= 3 else None,
        }

        return result

    async def get_row_action_buttons(self, row_index: int) -> dict[str, Locator]:
        """Get action buttons by row index (legacy fallback)."""
        rows_locator = self.locate("request_rows")
        row = rows_locator.nth(row_index)

        last_cell_buttons = row.locator("td:last-child button")
        btn_count = await last_cell_buttons.count()

        if btn_count >= 2:
            return {
                "approve": last_cell_buttons.nth(0),
                "reject": last_cell_buttons.nth(1),
                "view": last_cell_buttons.nth(2) if btn_count > 2 else last_cell_buttons.nth(0),
            }

        # Fallback to configured selectors
        approve_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "approve_button"
        )
        reject_sel = self.selectors.get_nested(
            self.page_name, "row_actions", "reject_button"
        )

        return {
            "approve": row.locator(approve_sel.value).first,
            "reject": row.locator(reject_sel.value).first,
            "view": row.locator("td:last-child button").nth(2),
        }
