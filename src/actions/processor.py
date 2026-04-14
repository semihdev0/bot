"""Main workflow processor - orchestrates the full bonus processing cycle."""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from playwright.async_api import Page

from src.actions.executor import BonusActionExecutor
from src.config.loader import AppConfig
from src.engine import rule_engine
from src.engine.models import BonusRequest, UserProfile
from src.monitoring.health import write_heartbeat
from src.pages.bonus_list_page import BonusListPage
from src.pages.user_profile_page import UserProfilePage
from src.utils.exceptions import ActionExecutionError, NavigationError
from src.utils.retry import retry

logger = structlog.get_logger()

PROCESSED_IDS_FILE = Path("processed_requests.json")


class BonusProcessor:
    """Orchestrates: fetch list -> check profile -> evaluate rules -> act."""

    def __init__(self, page: Page, config: AppConfig) -> None:
        self.page = page
        self.config = config
        self._processed_ids: set[str] = set()
        self._load_processed_ids()

        # Stats for current cycle
        self._stats = {"processed": 0, "approved": 0, "rejected": 0, "errors": 0}

    def _load_processed_ids(self) -> None:
        """Load previously processed request IDs from disk."""
        if PROCESSED_IDS_FILE.exists():
            try:
                data = json.loads(PROCESSED_IDS_FILE.read_text(encoding="utf-8"))
                self._processed_ids = set(data)
                logger.info(
                    "processed_ids_loaded", count=len(self._processed_ids)
                )
            except Exception:
                self._processed_ids = set()

    def _save_processed_ids(self) -> None:
        """Persist processed request IDs to disk."""
        # Keep only the last 10000 IDs to prevent unbounded growth
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

        # Navigate to bonus list
        bonus_list = BonusListPage(self.page, self.config.selectors)
        await bonus_list.navigate_to_list(
            base_url, settings.backoffice.bonus_list_path
        )

        # Get pending requests
        requests = await bonus_list.get_pending_requests(
            max_count=settings.polling.max_requests_per_cycle
        )

        if not requests:
            logger.info("no_pending_requests")
            write_heartbeat(status="healthy", **self._stats)
            return 0

        # Process each request
        for request in requests:
            if request.request_id in self._processed_ids:
                logger.debug(
                    "request_already_processed",
                    request_id=request.request_id,
                )
                continue

            try:
                await self._process_single_request(request, base_url)
                self._processed_ids.add(request.request_id)
                self._stats["processed"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(
                    "request_processing_failed",
                    request_id=request.request_id,
                    error=str(e),
                )

        # Save state and write health
        self._save_processed_ids()
        write_heartbeat(status="healthy", **self._stats)

        logger.info("cycle_completed", **self._stats)
        return self._stats["processed"]

    @retry(
        max_attempts=2,
        backoff_base=2.0,
        retryable=(NavigationError, ActionExecutionError),
    )
    async def _process_single_request(
        self, request: BonusRequest, base_url: str
    ) -> None:
        """Process a single bonus request end-to-end."""
        logger.info(
            "processing_request",
            request_id=request.request_id,
            user_id=request.user_id,
            bonus_type=request.bonus_type,
        )

        settings = self.config.settings

        # Step 1: Navigate to user profile and extract data
        profile_page = UserProfilePage(self.page, self.config.selectors)
        await profile_page.navigate_to_profile(
            base_url,
            settings.backoffice.user_profile_path_template,
            request.user_id,
        )
        profile = await profile_page.extract_profile(
            request.user_id, request.username
        )

        # Step 2: Evaluate rules to get a decision
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

        # Step 3: Navigate back to bonus list and execute action
        bonus_list = BonusListPage(self.page, self.config.selectors)
        await bonus_list.navigate_to_list(
            base_url, settings.backoffice.bonus_list_path
        )

        # Find and open the specific request detail
        # For now, navigate to a detail URL pattern if available
        # This may need customization based on actual panel structure
        executor = BonusActionExecutor(self.page, self.config.selectors)
        success = await executor.execute_decision(decision, request.request_id)

        if success:
            if decision.action == "approve":
                self._stats["approved"] += 1
            else:
                self._stats["rejected"] += 1
            logger.info(
                "request_completed",
                request_id=request.request_id,
                action=decision.action,
            )
