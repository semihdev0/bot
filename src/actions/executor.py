"""Executes approve/reject actions on the bonus request page."""

from __future__ import annotations

from decimal import Decimal

import structlog
from playwright.async_api import Page

from src.config.selectors import SelectorRegistry
from src.engine.models import Decision
from src.pages.base import BasePage
from src.utils.exceptions import ActionExecutionError

logger = structlog.get_logger()


class BonusActionExecutor(BasePage):
    """Handles the approve/reject UI interactions."""

    page_name = "bonus_action"

    async def execute_decision(
        self, decision: Decision, request_id: str
    ) -> bool:
        """Execute a decision (approve or reject) on the current page.

        Returns True if the action was successful.
        """
        try:
            if decision.action == "approve":
                return await self._approve(decision.bonus_amount, request_id)
            else:
                return await self._reject(decision.reject_message, request_id)
        except Exception as e:
            logger.error(
                "action_execution_failed",
                request_id=request_id,
                action=decision.action,
                error=str(e),
            )
            raise ActionExecutionError(
                f"Failed to execute {decision.action} for {request_id}: {e}"
            ) from e

    async def _approve(
        self, amount: Decimal | None, request_id: str
    ) -> bool:
        """Fill bonus amount and click approve."""
        if amount is not None and amount > 0:
            await self.fill("amount_input", str(amount))
            logger.debug(
                "amount_filled",
                request_id=request_id,
                amount=str(amount),
            )

        await self.click("approve_button")

        # Wait for and click confirm if it appears
        if await self.is_visible("confirm_button", timeout=3000):
            await self.click("confirm_button")

        logger.info(
            "bonus_approved",
            request_id=request_id,
            amount=str(amount),
        )
        return True

    async def _reject(
        self, message: str | None, request_id: str
    ) -> bool:
        """Fill rejection reason and click reject."""
        await self.click("reject_button")

        if message and await self.is_visible("rejection_reason_input", timeout=3000):
            await self.fill("rejection_reason_input", message)
            logger.debug(
                "rejection_reason_filled",
                request_id=request_id,
            )

        # Wait for and click confirm if it appears
        if await self.is_visible("confirm_button", timeout=3000):
            await self.click("confirm_button")

        logger.info(
            "bonus_rejected",
            request_id=request_id,
            message_preview=message[:50] if message else "",
        )
        return True
