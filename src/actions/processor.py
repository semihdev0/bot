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
from src.engine.models import BonusRequest
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

    async def process_pending_requests(self) -> int:
        """Main processing cycle. Returns number of requests processed."""
        self._stats = {"processed": 0, "approved": 0, "rejected": 0, "errors": 0}
        settings = self.config.settings
        base_url = self.config.credentials.url

        # Step 1: Navigate to bonus requests list
        bonus_list = BonusListPage(self.page, self.config.selectors)
        await bonus_list.navigate_to_list(
            base_url, settings.backoffice.bonus_list_path
        )

        # Step 2: Extract pending requests
        requests = await bonus_list.get_pending_requests(
            max_count=settings.polling.max_requests_per_cycle
        )

        if not requests:
            logger.info("no_pending_requests")
            write_heartbeat(status="healthy", **self._stats)
            return 0

        logger.info("pending_requests_found", count=len(requests))

        # Step 3: Process each request
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
        logger.info("cycle_completed", **self._stats)
        return self._stats["processed"]

    async def _process_single_request(
        self,
        request: BonusRequest,
        row_index: int,
        base_url: str,
        bonus_list: BonusListPage,
    ) -> None:
        """Process a single bonus request end-to-end."""
        logger.info(
            "processing_request",
            request_id=request.request_id,
            user_id=request.user_id,
            bonus_type=request.bonus_type,
        )

        settings = self.config.settings

        # Step 1: Navigate to user profile to get their data
        profile_page = UserProfilePage(self.page, self.config.selectors)
        await profile_page.navigate_to_profile(
            base_url,
            settings.backoffice.user_profile_path_template,
            request.user_id,
        )

        # Step 2: Extract profile data
        profile = await profile_page.extract_profile(
            request.user_id, request.username
        )

        # Step 3: Evaluate rules
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
        )

        # Step 4: Navigate back to bonus list
        await bonus_list.navigate_to_list(
            base_url, settings.backoffice.bonus_list_path
        )

        # Step 5: Find the row again and get action buttons
        # Re-fetch rows since we navigated away
        await asyncio.sleep(1)
        action_buttons = await bonus_list.get_row_action_buttons(row_index)

        # Step 6: Execute the decision
        executor = BonusActionExecutor(self.page, self.config.selectors)

        if decision.action == "approve":
            success = await executor.execute_approve(
                action_buttons["approve"], decision, request.request_id
            )
            if success:
                self._stats["approved"] += 1
        else:
            success = await executor.execute_reject(
                action_buttons["reject"], decision, request.request_id
            )
            if success:
                self._stats["rejected"] += 1

        logger.info(
            "request_completed",
            request_id=request.request_id,
            action=decision.action,
            success=success,
        )
