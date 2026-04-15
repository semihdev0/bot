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

# Broad selectors to detect any modal/dialog overlay
_MODAL_SELECTORS = ", ".join([
    "[role='dialog']",
    "[aria-modal='true']",
    "dialog[open]",
    "[data-state='open'][role='dialog']",
    "[class*='DialogContent']",
    "[class*='ModalContent']",
    "[class*='modal-content']",
])


class BonusActionExecutor:
    """Handles approve/reject interactions on Betronix modals."""

    def __init__(self, page: Page, selectors: SelectorRegistry) -> None:
        self.page = page
        self.selectors = selectors

    # ------------------------------------------------------------------
    # Modal helpers
    # ------------------------------------------------------------------

    async def _wait_for_modal(self, timeout_ms: int = 8000) -> Locator | None:
        """Wait for a modal/dialog to become visible after a button click.

        Tries multiple selector strategies since the Betronix panel may
        use Radix, Headless UI, shadcn, or custom modal implementations.
        """
        modal = self.page.locator(_MODAL_SELECTORS).first
        try:
            await modal.wait_for(state="visible", timeout=timeout_ms)
            logger.debug("modal_detected")
            return modal
        except Exception:
            # Fallback: any fixed/absolute overlay that just appeared
            fallback_selectors = [
                "div.fixed[class*='inset']",
                "div[class*='overlay'] ~ div",
                "div[class*='Overlay'] ~ div",
                "[class*='backdrop'] ~ div",
            ]
            for sel in fallback_selectors:
                try:
                    fb = self.page.locator(sel).first
                    if await fb.is_visible():
                        logger.debug("modal_detected_fallback", selector=sel)
                        return fb
                except Exception:
                    continue

            logger.warning("modal_not_detected_using_page_scope")
            return None

    async def _find_button(
        self,
        preferred_texts: list[str],
        color_classes: list[str] | None = None,
        modal: Locator | None = None,
    ) -> Locator | None:
        """Find a button using cascading strategies.

        Searches within the modal scope if provided, otherwise the full page.
        Tries: exact text -> partial text -> role -> color class -> submit type.
        """
        # Use modal scope when available for precision
        scope = modal if modal is not None else self.page

        for text in preferred_texts:
            # Strategy 1: Exact text on a <button>
            try:
                btn = scope.get_by_role("button", name=text, exact=True)
                if await btn.count() > 0:
                    logger.debug("button_found", strategy="role_exact", text=text)
                    return btn.first
            except Exception:
                pass

            # Strategy 2: Exact text match (any element)
            try:
                btn = scope.get_by_text(text, exact=True)
                if await btn.count() > 0:
                    logger.debug("button_found", strategy="text_exact", text=text)
                    return btn.first
            except Exception:
                pass

            # Strategy 3: Partial / case-insensitive text on button role
            try:
                btn = scope.get_by_role("button", name=text, exact=False)
                if await btn.count() > 0:
                    logger.debug("button_found", strategy="role_partial", text=text)
                    return btn.first
            except Exception:
                pass

        # Strategy 4: Color-class based buttons (Tailwind CSS)
        if color_classes:
            for cls in color_classes:
                try:
                    btn = scope.locator(f"button[class*='{cls}']")
                    if await btn.count() > 0:
                        logger.debug("button_found", strategy="color_class", cls=cls)
                        return btn.first
                except Exception:
                    continue

        # Strategy 5: Submit button
        try:
            btn = scope.locator("button[type='submit']")
            if await btn.count() > 0:
                logger.debug("button_found", strategy="submit_type")
                return btn.first
        except Exception:
            pass

        # If modal scope failed, retry on full page (modal might not contain buttons)
        if modal is not None:
            logger.debug("retrying_button_search_on_page")
            return await self._find_button(preferred_texts, color_classes, modal=None)

        return None

    async def _debug_log_all_buttons(self) -> None:
        """Log every visible button on the page for debugging."""
        try:
            buttons = self.page.locator("button:visible")
            count = await buttons.count()
            logger.info("debug_visible_buttons", total=count)
            for i in range(min(count, 20)):
                btn = buttons.nth(i)
                text = (await btn.text_content() or "").strip()
                cls = (await btn.get_attribute("class") or "")[:100]
                btn_type = await btn.get_attribute("type") or ""
                logger.info(
                    "debug_button",
                    index=i,
                    text=text[:60],
                    type=btn_type,
                    class_preview=cls,
                )
        except Exception as e:
            logger.warning("debug_log_buttons_failed", error=str(e))

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------

    async def execute_approve(
        self,
        approve_button: Locator,
        decision: Decision,
        request_id: str,
    ) -> bool:
        """Click approve button and handle the 'Talebi Onayla' modal.

        If decision has a custom bonus_amount, enables "Ozel degerler kullan"
        and fills in the custom amount (and optionally turnover).
        """
        try:
            # Click the approve button on the row
            await approve_button.click()
            logger.debug("approve_button_clicked", request_id=request_id)

            # Wait for modal to appear
            await asyncio.sleep(1)
            modal = await self._wait_for_modal()

            # Check if we need to set custom values
            if decision.bonus_amount is not None and decision.bonus_amount > 0:
                await self._fill_custom_values(
                    modal, decision.bonus_amount, decision.bonus_turnover, request_id
                )

            # Find and click confirm button (panel uses English UI)
            confirm_btn = await self._find_button(
                preferred_texts=["Approve", "Confirm", "OK", "Onayla", "Tamam", "Evet", "Kaydet"],
                color_classes=["emerald", "green", "primary", "success"],
                modal=modal,
            )

            if confirm_btn is None:
                logger.error("approve_confirm_button_not_found", request_id=request_id)
                await self._debug_log_all_buttons()
                await self._try_close_modal()
                raise ActionExecutionError(
                    f"Approve confirm button not found for request {request_id}"
                )

            await confirm_btn.click()
            await asyncio.sleep(1.5)

            logger.info(
                "bonus_approved",
                request_id=request_id,
                amount=str(decision.bonus_amount),
                turnover=decision.bonus_turnover,
            )
            return True

        except ActionExecutionError:
            raise
        except Exception as e:
            await self._try_close_modal()
            logger.error("approve_failed", request_id=request_id, error=str(e))
            raise ActionExecutionError(
                f"Failed to approve {request_id}: {e}"
            ) from e

    async def _fill_custom_values(
        self,
        modal: Locator | None,
        amount: Decimal,
        turnover: int | None,
        request_id: str,
    ) -> None:
        """Enable custom values checkbox and fill amount/turnover inputs."""
        scope = modal if modal is not None else self.page

        # Click custom values checkbox (try English first, then Turkish)
        checkbox_found = False
        for text in ["Use custom values", "Custom values", "Özel değerler kullan"]:
            checkbox = scope.get_by_text(text)
            if await checkbox.count() > 0:
                await checkbox.click()
                await asyncio.sleep(0.5)
                checkbox_found = True
                break
        if not checkbox_found:
            for text in ["Use custom values", "Custom values", "Özel değerler kullan"]:
                checkbox = self.page.get_by_text(text)
                if await checkbox.count() > 0:
                    await checkbox.click()
                    await asyncio.sleep(0.5)
                    break

        # Fill custom amount - try multiple selectors
        amount_str = str(int(amount))
        amount_filled = False
        for sel in [
            "input[placeholder*='Tutar']",
            "input[name*='amount']",
            "input[type='number']",
        ]:
            try:
                inp = scope.locator(sel).first
                if await inp.count() > 0 and await inp.is_visible():
                    await inp.fill(amount_str)
                    amount_filled = True
                    break
            except Exception:
                continue

        if not amount_filled:
            # Fallback: try on page scope
            for sel in [
                "input[placeholder*='Tutar']",
                "input[name*='amount']",
            ]:
                try:
                    inp = self.page.locator(sel).first
                    if await inp.count() > 0 and await inp.is_visible():
                        await inp.fill(amount_str)
                        amount_filled = True
                        break
                except Exception:
                    continue

        # Fill custom turnover if specified
        if turnover is not None:
            for sel in [
                "input[placeholder*='Çevrim']",
                "input[name*='turnover']",
            ]:
                try:
                    inp = scope.locator(sel).first
                    if await inp.count() > 0 and await inp.is_visible():
                        await inp.fill(str(turnover))
                        break
                except Exception:
                    continue

        logger.debug(
            "custom_values_set",
            request_id=request_id,
            amount=amount_str,
            turnover=turnover,
            amount_filled=amount_filled,
        )

    # ------------------------------------------------------------------
    # Reject
    # ------------------------------------------------------------------

    async def execute_reject(
        self,
        reject_button: Locator,
        decision: Decision,
        request_id: str,
    ) -> bool:
        """Click reject button and handle the rejection modal.

        Fills in the rejection reason and confirms.
        SAFETY: Never falls back to approve if reject button is not found.
        """
        try:
            # Click the reject button on the row
            await reject_button.click()
            logger.debug("reject_button_clicked", request_id=request_id)

            # Wait for modal to appear
            await asyncio.sleep(1)
            modal = await self._wait_for_modal()

            # Fill rejection reason
            if decision.reject_message:
                await self._fill_reject_reason(modal, decision.reject_message)

            # Find and click reject confirm button (panel uses English UI)
            confirm_btn = await self._find_button(
                preferred_texts=["Reject", "Confirm", "Reddet", "Evet", "Tamam"],
                color_classes=["red", "danger", "destructive", "rose"],
                modal=modal,
            )

            if confirm_btn is None:
                logger.error("reject_confirm_button_not_found", request_id=request_id)
                await self._debug_log_all_buttons()
                await self._try_close_modal()
                raise ActionExecutionError(
                    f"Reddet button not found for request {request_id} - "
                    "aborting to prevent accidental approval"
                )

            await confirm_btn.click()
            await asyncio.sleep(1.5)

            logger.info(
                "bonus_rejected",
                request_id=request_id,
                message_preview=decision.reject_message[:50] if decision.reject_message else "",
            )
            return True

        except ActionExecutionError:
            raise
        except Exception as e:
            await self._try_close_modal()
            logger.error("reject_failed", request_id=request_id, error=str(e))
            raise ActionExecutionError(
                f"Failed to reject {request_id}: {e}"
            ) from e

    async def _fill_reject_reason(
        self, modal: Locator | None, message: str
    ) -> None:
        """Fill the rejection reason into the modal's textarea or input."""
        scope = modal if modal is not None else self.page

        # Try textarea first (most common for rejection reasons)
        for sel in [
            "textarea",
            "input[type='text']",
            "[contenteditable='true']",
        ]:
            try:
                inp = scope.locator(sel).first
                if await inp.count() > 0 and await inp.is_visible():
                    await inp.fill(message)
                    await asyncio.sleep(0.5)
                    logger.debug("reject_reason_filled", selector=sel)
                    return
            except Exception:
                continue

        # Fallback: try on full page
        for sel in ["textarea", "input[type='text']"]:
            try:
                inp = self.page.locator(sel).first
                if await inp.count() > 0 and await inp.is_visible():
                    await inp.fill(message)
                    await asyncio.sleep(0.5)
                    logger.debug("reject_reason_filled_fallback", selector=sel)
                    return
            except Exception:
                continue

        logger.warning("reject_reason_input_not_found")

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    async def _try_close_modal(self) -> None:
        """Try to close any open modal to recover from errors."""
        try:
            # Try clicking Cancel (English UI)
            for cancel_text in ["Cancel", "İptal"]:
                cancel = self.page.get_by_text(cancel_text, exact=True).first
                if await cancel.count() > 0:
                    await cancel.click()
                    await asyncio.sleep(0.5)
                    return

            # Try clicking X close button
            for sel in [
                "[class*='modal'] button[class*='close']",
                "[role='dialog'] button[class*='close']",
                "button[aria-label='Close']",
                "button[aria-label='Kapat']",
                "[class*='DialogClose']",
            ]:
                close = self.page.locator(sel).first
                if await close.count() > 0:
                    await close.click()
                    await asyncio.sleep(0.5)
                    return

            # Press Escape as last resort
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception:
            pass
