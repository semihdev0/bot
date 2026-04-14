"""Executes approve/reject actions on Betronix bonus requests.

Betronix flow:
- Approve: Click ✓ -> "Talebi Onayla" modal opens
  - Shows: Oyuncu, Bonus, Varsayılan Tutar, Varsayılan Çevrim
  - Check "Özel değerler kullan" to enter custom amount/turnover
  - Click "Onayla" to confirm
- Reject: Click ✗ -> "Talebi Reddet" modal opens
  - Enter rejection reason
  - Click "Reddet" to confirm
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import structlog
from playwright.async_api import Locator, Page

from src.config.selectors import SelectorRegistry
from src.engine.models import Decision
from src.pages.base import BasePage
from src.utils.exceptions import ActionExecutionError

logger = structlog.get_logger()


class BonusActionExecutor:
    """Handles approve/reject interactions on Betronix modals."""

    def __init__(self, page: Page, selectors: SelectorRegistry) -> None:
        self.page = page
        self.selectors = selectors

    async def execute_approve(
        self,
        approve_button: Locator,
        decision: Decision,
        request_id: str,
    ) -> bool:
        """Click approve button and handle the 'Talebi Onayla' modal.

        If decision has a custom bonus_amount, enables "Özel değerler kullan"
        and fills in the custom amount (and optionally turnover).
        """
        try:
            # Click the ✓ approve button on the row
            await approve_button.click()
            await asyncio.sleep(1)

            # Modal should now be open: "Talebi Onayla"
            # Check if we need to set custom values
            if decision.bonus_amount is not None and decision.bonus_amount > 0:
                # Click "Özel değerler kullan" checkbox
                checkbox = self.page.get_by_text("Özel değerler kullan")
                if await checkbox.count() > 0:
                    await checkbox.click()
                    await asyncio.sleep(0.5)

                    # Fill custom amount
                    amount_input = self.page.locator(
                        "input[type='number']:nth-of-type(1), "
                        "input[placeholder*='Tutar'], "
                        "input[name*='amount']"
                    ).first
                    if await amount_input.count() > 0:
                        await amount_input.fill(str(int(decision.bonus_amount)))

                    # Fill custom turnover if specified
                    if decision.bonus_turnover is not None:
                        turnover_input = self.page.locator(
                            "input[type='number']:nth-of-type(2), "
                            "input[placeholder*='Çevrim'], "
                            "input[name*='turnover']"
                        ).first
                        if await turnover_input.count() > 0:
                            await turnover_input.fill(str(decision.bonus_turnover))

                    logger.debug(
                        "custom_values_set",
                        request_id=request_id,
                        amount=str(decision.bonus_amount),
                        turnover=decision.bonus_turnover,
                    )

            # Click "Onayla" button
            confirm_btn = self.page.get_by_text("Onayla", exact=True).first
            await confirm_btn.click()
            await asyncio.sleep(1)

            logger.info(
                "bonus_approved",
                request_id=request_id,
                amount=str(decision.bonus_amount),
                turnover=decision.bonus_turnover,
            )
            return True

        except Exception as e:
            # Try to close modal if it's still open
            await self._try_close_modal()
            logger.error(
                "approve_failed",
                request_id=request_id,
                error=str(e),
            )
            raise ActionExecutionError(
                f"Failed to approve {request_id}: {e}"
            ) from e

    async def execute_reject(
        self,
        reject_button: Locator,
        decision: Decision,
        request_id: str,
    ) -> bool:
        """Click reject button and handle the rejection modal.

        Fills in the rejection reason and confirms.
        """
        try:
            # Click the ✗ reject button on the row
            await reject_button.click()
            await asyncio.sleep(1)

            # Fill rejection reason if there's an input
            if decision.reject_message:
                reason_input = self.page.locator(
                    "textarea, "
                    "[class*='modal'] input[type='text'], "
                    "[class*='dialog'] textarea"
                ).first
                if await reason_input.count() > 0:
                    await reason_input.fill(decision.reject_message)
                    await asyncio.sleep(0.5)

            # Click "Reddet" confirm button
            confirm_btn = self.page.get_by_text("Reddet", exact=True).first
            if await confirm_btn.count() > 0:
                await confirm_btn.click()
            else:
                # Fallback: try "Onayla" or generic confirm
                confirm_alt = self.page.get_by_text("Onayla", exact=True).first
                if await confirm_alt.count() > 0:
                    await confirm_alt.click()

            await asyncio.sleep(1)

            logger.info(
                "bonus_rejected",
                request_id=request_id,
                message_preview=decision.reject_message[:50] if decision.reject_message else "",
            )
            return True

        except Exception as e:
            await self._try_close_modal()
            logger.error(
                "reject_failed",
                request_id=request_id,
                error=str(e),
            )
            raise ActionExecutionError(
                f"Failed to reject {request_id}: {e}"
            ) from e

    async def _try_close_modal(self) -> None:
        """Try to close any open modal to recover from errors."""
        try:
            # Try clicking İptal
            cancel = self.page.get_by_text("İptal", exact=True).first
            if await cancel.count() > 0:
                await cancel.click()
                return
            # Try clicking X close button
            close = self.page.locator("[class*='modal'] button[class*='close']").first
            if await close.count() > 0:
                await close.click()
                return
            # Press Escape
            await self.page.keyboard.press("Escape")
        except Exception:
            pass
