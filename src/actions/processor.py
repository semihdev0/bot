"""Main workflow processor for Betronix bonus approval.

Flow per request:
1. From bonus list, note the request details (user, bonus type, etc.)
2. Click username link to open user profile in new tab or navigate
3. Extract profile data (balance, deposits, active bonus, etc.)
4. Navigate back to bonus list
5. Evaluate rules against profile data
6. Click ✓ or ✗ on the request row
7. Handle the approval/rejection modal
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog
from playwright.async_api import Page

from src.actions.executor import BonusActionExecutor
from src.config.loader import AppConfig
from src.engine import rule_engine
from decimal import Decimal

from src.engine.models import BonusRequest, Decision
from src.monitoring.health import write_heartbeat
from src.pages.bonus_list_page import BonusListPage
from src.pages.user_profile_page import UserProfilePage
from src.utils.exceptions import ActionExecutionError, NavigationError
from src.utils.retry import retry

logger = structlog.get_logger()

PROCESSED_IDS_FILE = Path("processed_requests.json")


class BonusProcessor:
    """Orchestrates the full Betronix bonus processing cycle."""

    def __init__(self, page: Page, config: AppConfig) -> None:
        self.page = page
        self.config = config
        self._processed_ids: set[str] = set()
        self._load_processed_ids()
        self._stats = {"processed": 0, "approved": 0, "rejected": 0, "errors": 0}

    def _load_processed_ids(self) -> None:
        if PROCESSED_IDS_FILE.exists():
            try:
                data = json.loads(PROCESSED_IDS_FILE.read_text(encoding="utf-8"))
                self._processed_ids = set(data)
                logger.info("processed_ids_loaded", count=len(self._processed_ids))
            except Exception:
                self._processed_ids = set()

    def _save_processed_ids(self) -> None:
        ids_list = list(self._processed_ids)
        if len(ids_list) > 10000:
            ids_list = ids_list[-10000:]
            self._processed_ids = set(ids_list)
        PROCESSED_IDS_FILE.write_text(
            json.dumps(ids_list, ensure_ascii=False), encoding="utf-8"
        )

    async def run_notification_loop(self) -> None:
        """Main loop: wait for notification → reload → process → repeat.

        Instead of polling the page at intervals, we stay on the bonus
        list page and watch for the 'Yeni Bonus Talebi' toast that the
        backoffice pushes in the bottom-right corner.  Only when this
        notification appears do we reload and process.

        Processing order:
        1. Set rows per page to 50 (backoffice defaults to 20)
        2. Go to the LAST page (oldest requests)
        3. Process rows bottom-to-top (oldest first)
        4. Move to previous page, repeat
        5. Continue until page 1 is done
        """
        settings = self.config.settings
        base_url = self.config.credentials.url

        # Navigate to the bonus list once
        bonus_list = BonusListPage(self.page, self.config.selectors)
        await bonus_list.navigate_to_list(
            base_url, settings.backoffice.bonus_list_path
        )

        # Increase rows per page from default 20 → 50
        await bonus_list.set_rows_per_page(50)

        # Install Sonner toast observer for notification detection
        await bonus_list.install_toast_observer()

        # Process any already-pending requests on first load (all pages)
        await self._process_all_pages(bonus_list, base_url)

        # Enter the notification-driven loop
        while True:
            # Make sure we're back on page 1 for notification watching
            await bonus_list.go_to_first_page()

            logger.info("waiting_for_notification")
            write_heartbeat(status="healthy", **self._stats)

            # Block until a toast appears (or timeout)
            got_notification = await bonus_list.wait_for_notification(
                timeout_seconds=settings.polling.notification_timeout_seconds,
            )

            if got_notification:
                # Reload the page so the new request appears in the table
                await bonus_list.reload_page()
                await self._process_all_pages(bonus_list, base_url)

                # Drain: if more notifications arrived while we were
                # processing, reload and process again immediately
                while await bonus_list.has_pending_notification():
                    logger.info("additional_notification_detected")
                    await bonus_list.reload_page()
                    await self._process_all_pages(bonus_list, base_url)
            else:
                # Timeout – do a safety reload to catch anything missed
                logger.debug("notification_timeout_safety_reload")
                await bonus_list.reload_page()
                await self._process_all_pages(bonus_list, base_url)

    async def _process_all_pages(
        self, bonus_list: BonusListPage, base_url: str
    ) -> int:
        """Process ALL pages of pending requests, oldest first.

        Flow:
        1. Go to the last page (oldest requests)
        2. Process that page's pending rows (bottom-to-top)
        3. Go to previous page, repeat
        4. Stop after page 1 is done

        Only "Beklemede" rows are processed; "Onaylandı" and
        "Reddedildi" rows are automatically skipped.
        """
        total_pages = await bonus_list.get_total_pages()
        total_processed = 0

        if total_pages > 1:
            # Navigate to last page first (oldest requests)
            await bonus_list.go_to_last_page()
            logger.info("starting_from_last_page", total_pages=total_pages)

        # Process current page (which is the last page), then work backwards
        while True:
            current_page = await bonus_list.get_current_page()
            logger.info("processing_page", page=current_page, total=total_pages)

            count = await self._process_current_page(bonus_list, base_url)
            total_processed += count

            # Move to previous page
            if current_page > 1:
                went_back = await bonus_list.go_to_prev_page()
                if not went_back:
                    break
            else:
                break

        logger.info("all_pages_completed", total_processed=total_processed)
        return total_processed

    async def _process_current_page(
        self, bonus_list: BonusListPage, base_url: str
    ) -> int:
        """Extract and process every pending request on the current table page.

        Only "Beklemede" rows are included; "Onaylandı" / "Reddedildi"
        rows are filtered out.  Requests are returned in bottom-to-top
        order (oldest first) by get_pending_requests().
        """
        self._stats = {"processed": 0, "approved": 0, "rejected": 0, "errors": 0}
        settings = self.config.settings

        requests = await bonus_list.get_pending_requests(
            max_count=settings.polling.max_requests_per_cycle
        )

        if not requests:
            logger.info("no_pending_requests_on_page")
            write_heartbeat(status="healthy", **self._stats)
            return 0

        logger.info("pending_requests_found", count=len(requests))

        for i, request in enumerate(requests):
            if request.request_id in self._processed_ids:
                logger.debug("request_already_processed", request_id=request.request_id)
                continue

            try:
                await self._process_single_request(request, i, base_url, bonus_list)
                self._processed_ids.add(request.request_id)
                self._stats["processed"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(
                    "request_processing_failed",
                    request_id=request.request_id,
                    error=str(e),
                )
                # Make sure we're back on the bonus list for the next request
                try:
                    await bonus_list.navigate_to_list(
                        base_url, settings.backoffice.bonus_list_path
                    )
                except Exception:
                    pass

        self._save_processed_ids()
        write_heartbeat(status="healthy", **self._stats)
        logger.info("page_completed", **self._stats)
        return self._stats["processed"]

    async def _open_profile_via_click(
        self,
        bonus_list: BonusListPage,
        request: BonusRequest,
    ) -> tuple:
        """Open user profile by clicking the username link in the table row.

        The username cell contains a link icon that opens the profile
        in a new browser tab.  We:
        1. Find the row by player_id
        2. Click the link icon in the USERNAME cell
        3. Wait for the new tab to open
        4. Extract profile data from the new tab
        5. Close the new tab (returns to bonus list tab)

        Returns (UserProfile, new_tab_page) or (None, None) on failure.
        """
        try:
            # Extract player_id from composite request_id
            player_id = request.user_id

            row = await bonus_list.find_row_by_request_id(request.request_id)
            if row is None:
                return None, None

            # Find the username cell (cell index 1) and its link icon
            username_cell = row.locator("td").nth(1)

            # The link icon is typically an SVG or anchor element in the cell
            # Try clicking the external link icon (↗)
            link_icon = username_cell.locator("a, svg, [class*='external'], [class*='link']").first

            # Listen for new tab
            context = self.page.context
            async with context.expect_page(timeout=10000) as new_page_info:
                if await link_icon.count() > 0:
                    await link_icon.click()
                else:
                    # Fallback: click the username text itself
                    username_text = username_cell.locator("span[class*='cursor'], span[class*='pointer'], span[class*='primary']").first
                    if await username_text.count() > 0:
                        await username_text.click()
                    else:
                        # Last resort: click the cell
                        await username_cell.click()

            new_tab = await new_page_info.value
            await new_tab.wait_for_load_state("networkidle", timeout=30000)

            logger.info("profile_tab_opened", url=new_tab.url)

            # Wait for profile content to load
            for attempt in range(10):
                text_nodes = await new_tab.evaluate(
                    """() => {
                    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let c = 0;
                    while (w.nextNode()) {
                        if (w.currentNode.textContent.includes('₺') ||
                            w.currentNode.textContent.includes('Balance') ||
                            w.currentNode.textContent.includes('Bakiye')) c++;
                    }
                    return c;
                }"""
                )
                if text_nodes > 2:
                    break
                await asyncio.sleep(1)

            # Extract profile data from the new tab
            profile_page = UserProfilePage(new_tab, self.config.selectors)
            profile = await profile_page.extract_profile(
                request.user_id, request.username
            )

            # Close the new tab - returns to bonus list
            await new_tab.close()
            logger.info("profile_tab_closed")

            return profile, None

        except Exception as e:
            logger.warning("profile_click_failed", error=str(e))
            # Try to close any extra tabs
            try:
                pages = self.page.context.pages
                while len(pages) > 1:
                    await pages[-1].close()
                    pages = self.page.context.pages
            except Exception:
                pass
            return None, None

    # Bonus types that are auto-approved without profile checks
    DIRECT_APPROVE_TYPES = frozenset({
        "spor_kayip_bonusu",
    })

    async def _process_single_request(
        self,
        request: BonusRequest,
        row_index: int,
        base_url: str,
        bonus_list: BonusListPage,
    ) -> None:
        """Process a single bonus request end-to-end.

        IMPORTANT: After navigating to a user profile and back, the
        table row order may have changed (new requests inserted by
        other users).  We always re-find the row by its unique
        request_id (#ID) instead of using the original row_index,
        so we never approve/reject the wrong request.
        """
        logger.info(
            "processing_request",
            request_id=request.request_id,
            user_id=request.user_id,
            bonus_type=request.bonus_type,
        )

        settings = self.config.settings

        # Check if this bonus type is auto-approved (no profile check needed)
        if request.bonus_type in self.DIRECT_APPROVE_TYPES:
            decision = Decision(
                action="approve",
                bonus_amount=Decimal("0"),
                matched_rule_name="direct_approve",
                confidence="rule_matched",
            )
            logger.info(
                "direct_approve",
                request_id=request.request_id,
                bonus_type=request.bonus_type,
            )
        else:
            # Step 1: Click username link in the row to open profile in new tab
            profile, new_tab = await self._open_profile_via_click(
                bonus_list, request
            )

            if profile is None:
                # Fallback: navigate via URL
                logger.warning("click_navigation_failed_using_url", user_id=request.user_id)
                profile_page = UserProfilePage(self.page, self.config.selectors)
                await profile_page.navigate_to_profile(
                    base_url,
                    settings.backoffice.user_profile_path_template,
                    request.user_id,
                )
                profile = await profile_page.extract_profile(
                    request.user_id, request.username
                )
                await bonus_list.navigate_to_list(
                    base_url, settings.backoffice.bonus_list_path
                )

            # Step 2: Evaluate rules
            decision = rule_engine.evaluate(
                profile=profile,
                request=request,
                rules_config=self.config.bonus_rules,
                messages=self.config.messages.rejection_messages,
            )

        logger.info(
            "decision_made",
            request_id=request.request_id,
            action=decision.action,
            matched_rule=decision.matched_rule_name,
            bonus_amount=str(decision.bonus_amount) if decision.bonus_amount else None,
            bonus_turnover=decision.bonus_turnover,
        )

        # Step 5: Find the row by request_id (NOT by index – table may have changed)
        await asyncio.sleep(1)
        action_buttons = await bonus_list.get_row_action_buttons_by_id(
            request.request_id
        )

        if action_buttons is None:
            logger.error(
                "row_not_found_after_return",
                request_id=request.request_id,
            )
            raise ActionExecutionError(
                f"Row for request #{request.request_id} not found in table"
            )

        # Step 6: Execute the decision
        executor = BonusActionExecutor(self.page, self.config.selectors)

        if decision.action == "approve":
            success = await executor.execute_approve(
                action_buttons["approve"], decision, request.request_id
            )
            if success:
                self._stats["approved"] += 1
        else:
            reject_btn = action_buttons.get("reject")
            if reject_btn is None:
                logger.error(
                    "reject_button_not_available",
                    request_id=request.request_id,
                    hint="Only 1 action button found in row - cannot reject safely",
                )
                raise ActionExecutionError(
                    f"Reject button not available for {request.request_id}"
                )
            success = await executor.execute_reject(
                reject_btn, decision, request.request_id
            )
            if success:
                self._stats["rejected"] += 1

        logger.info(
            "request_completed",
            request_id=request.request_id,
            action=decision.action,
            success=success,
        )
