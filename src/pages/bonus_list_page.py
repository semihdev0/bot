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

    async def navigate_to_list(self, base_url: str, path: str) -> None:
        """Navigate to the bonus requests list page."""
        url = f"{base_url.rstrip('/')}{path}"
        await self.navigate(url)
        await asyncio.sleep(2)  # Wait for table to load
        logger.info("bonus_list_loaded", url=url)

    async def get_pending_requests(self, max_count: int = 50) -> list[BonusRequest]:
        """Extract pending bonus requests from the Betronix table.

        Betronix table structure per row:
        OYUNCU | KULLANICI ADI | BONUS | TUTAR | ÇEVRİM | DURUM | TARİH | İŞLEMLER(✓ ✗ 👁)

        The request ID is embedded as #ID in the player info column.
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
                if request and request.status.lower() in ("beklemede", "pending"):
                    requests.append(request)
            except Exception as e:
                logger.warning("row_extraction_error", row_index=i, error=str(e))
                continue

        logger.info("pending_requests_extracted", count=len(requests))
        return requests

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
        # Remove percentage prefix
        cleaned = re.sub(r"^%?\d+\s*", "", raw)
        # Turkish char normalization
        tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
        cleaned = cleaned.translate(tr_map)
        # Lowercase, replace spaces with underscore
        return re.sub(r"\s+", "_", cleaned.strip().lower())

    async def get_row_action_buttons(self, row_index: int) -> dict[str, Locator]:
        """Get the approve/reject/view action button locators for a row."""
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
