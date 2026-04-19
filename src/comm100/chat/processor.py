"""Main chat processing orchestrator for Comm100 live chat."""

from __future__ import annotations

import asyncio

import structlog

from src.comm100.ai.claude_client import ClaudeClient
from src.comm100.api.client import Comm100Client
from src.comm100.api.models import Comm100Chat, Comm100Message
from src.comm100.chat.state import ChatStateTracker
from src.comm100.chat.template_matcher import TemplateMatcher
from src.comm100.config.models import Comm100Settings
from src.comm100.exceptions import Comm100ApiError, Comm100AuthError
from src.monitoring.health import write_heartbeat

logger = structlog.get_logger()


class ChatProcessor:
    """Orchestrates Comm100 chat processing."""

    def __init__(
        self,
        api_client: Comm100Client,
        claude_client: ClaudeClient,
        template_matcher: TemplateMatcher,
        state: ChatStateTracker,
        config: Comm100Settings,
    ) -> None:
        self._api = api_client
        self._claude = claude_client
        self._templates = template_matcher
        self._state = state
        self._config = config
        self._stats = {
            "processed": 0,
            "template_responses": 0,
            "ai_responses": 0,
            "errors": 0,
        }

    async def run_polling_cycle(self) -> None:
        try:
            chats = await self._api.get_active_chats()
            chats = chats[: self._config.polling.max_chats_per_cycle]

            for chat in chats:
                try:
                    await self._process_chat(chat)
                except Comm100AuthError:
                    raise
                except Exception as e:
                    logger.error(
                        "chat_process_error",
                        chat_id=chat.id,
                        error=str(e),
                        exc_info=True,
                    )
                    self._stats["errors"] += 1

            write_heartbeat(
                status="healthy",
                processed=self._stats["processed"],
            )

        except Comm100AuthError:
            raise
        except Comm100ApiError as e:
            logger.error("polling_cycle_error", error=str(e))
            self._stats["errors"] += 1

    async def _process_chat(self, chat: Comm100Chat) -> None:
        if not self._state.is_active_chat(chat.id):
            try:
                await self._api.accept_chat(chat.id)
            except Comm100ApiError:
                pass
            self._state.add_active_chat(chat.id)

        messages = await self._api.get_chat_messages(
            chat.id, limit=self._config.polling.message_fetch_limit
        )

        unresponded = self._state.get_unresponded_visitor_messages(messages)
        if not unresponded:
            return

        chat.messages = messages

        for msg in unresponded:
            response = await self._generate_response(chat, msg)
            await self._api.send_message(chat.id, response)
            self._state.mark_responded(msg.id)
            self._stats["processed"] += 1

            logger.info(
                "message_responded",
                chat_id=chat.id,
                message_id=msg.id,
                visitor_msg=msg.content[:80],
                response=response[:80],
            )

    async def _generate_response(
        self, chat: Comm100Chat, visitor_message: Comm100Message
    ) -> str:
        template_response = self._templates.match(visitor_message.content)
        if template_response:
            self._stats["template_responses"] += 1
            logger.debug("using_template", chat_id=chat.id)
            return template_response

        self._stats["ai_responses"] += 1
        logger.debug("using_claude", chat_id=chat.id)
        return await self._claude.generate_response_safe(
            conversation=chat.messages,
            visitor_name=chat.visitor_name,
        )

    async def run_loop(self, shutdown_event: asyncio.Event) -> None:
        interval = self._config.polling.interval_seconds
        logger.info("polling_loop_started", interval=interval)

        while not shutdown_event.is_set():
            await self.run_polling_cycle()
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=interval
                )
            except asyncio.TimeoutError:
                pass
