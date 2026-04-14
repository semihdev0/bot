"""Bonus requests listing page - extracts pending requests."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import structlog

from src.engine.models import BonusRequest
from src.pages.base import BasePage

logger = structlog.get_logger()


class BonusListPage(BasePage):
    page_name = "bonus_list_page"

    async def navigate_to_list(self, base_url: str, path: str) -> None:
        """Navigate to the bonus requests list page."""
        url = f"{base_url.rstrip('/')}{path}"
        await self.navigate(url)
        logger.info("bonus_list_loaded", url=url)

    async def get_pending_requests(self, max_count: int = 50) -> list[BonusRequest]:
        """Extract pending bonus requests from the table.

        Returns a list of BonusRequest objects.
        """
        rows_locator = self.locate("request_rows")
        count = await rows_locator.count()
        logger.info("bonus_rows_found", count=count)

        requests: list[BonusRequest] = []
        for i in range(min(count, max_count)):
            try:
                row = rows_locator.nth(i)
                request = await self._extract_request_from_row(row)
                if request:
                    requests.append(request)
            except Exception as e:
                logger.warning("row_extraction_error", row_index=i, error=str(e))
                continue

        logger.info("pending_requests_extracted", count=len(requests))
        return requests

    async def _extract_request_from_row(self, row) -> BonusRequest | None:
        """Extract a BonusRequest from a single table row."""
        try:
            # Get selectors for row columns
            req_id_sel = self.selectors.get_nested(
                self.page_name, "row_columns", "request_id"
            )
            user_id_sel = self.selectors.get_nested(
                self.page_name, "row_columns", "user_id"
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

            request_id = await row.locator(req_id_sel.value).text_content() or ""
            user_id = await row.locator(user_id_sel.value).text_content() or ""
            username = await row.locator(username_sel.value).text_content() or ""
            bonus_type = await row.locator(bonus_type_sel.value).text_content() or ""
            amount_text = await row.locator(amount_sel.value).text_content() or "0"
            status = await row.locator(status_sel.value).text_content() or ""

            # Parse amount
            try:
                requested_amount = Decimal(
                    amount_text.strip().replace(",", ".").replace(" ", "")
                )
            except (InvalidOperation, ValueError):
                requested_amount = None

            return BonusRequest(
                request_id=request_id.strip(),
                user_id=user_id.strip(),
                username=username.strip(),
                bonus_type=bonus_type.strip().lower().replace(" ", "_"),
                requested_amount=requested_amount,
                status=status.strip(),
            )

        except Exception as e:
            logger.warning("request_parse_error", error=str(e))
            return None

    async def open_request_detail(self, row_index: int) -> None:
        """Click the detail link on a specific row."""
        rows_locator = self.locate("request_rows")
        row = rows_locator.nth(row_index)
        detail_sel = self.selectors.get_nested(
            self.page_name, "row_columns", "detail_link"
        )
        await row.locator(detail_sel.value).click()
        await self.page.wait_for_load_state("domcontentloaded")
