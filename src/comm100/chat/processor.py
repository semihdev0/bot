"""Main chat processing orchestrator using Playwright browser automation."""

from __future__ import annotations

import asyncio

import structlog

from src.comm100.ai.claude_client import ClaudeClient
from src.comm100.chat.state import ChatStateTracker
from src.comm100.chat.template_matcher import TemplateMatcher
from src.comm100.config.models import Comm100Settings
from src.comm100.pages.agent_console import AgentConsolePage, ChatMessage
from src.monitoring.health import write_heartbeat

logger = structlog.get_logger()


class ChatProcessor:
    """Orchestrates Comm100 chat processing via browser automation."""

    def __init__(
        self,
        console: AgentConsolePage,
        claude_client: ClaudeClient,
        template_matcher: TemplateMatcher,
        state: ChatStateTracker,
        config: Comm100Settings,
    ) -> None:
        self._console = console
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
        self._last_seen_count = 0

    async def run_polling_cycle(self) -> None:
        try:
            self._poll_count = getattr(self, "_poll_count", 0) + 1
            logger.info("polling", cycle=self._poll_count)

            accepted = await self._console.accept_new_chat()
            if accepted:
                logger.info("new_chat_accepted_in_cycle")

            chat_items = await self._console.get_chat_items()
            logger.info("poll_result", chat_count=len(chat_items))

            if not chat_items:
                if self._poll_count <= 3 or self._poll_count % 12 == 0:
                    await self._console.take_debug_screenshot()
                return

            for i, item in enumerate(chat_items[:self._config.polling.max_chats_per_cycle]):
                try:
                    await asyncio.wait_for(
                        item.evaluate("el => el.click()"), timeout=5
                    )
                    await asyncio.sleep(1)
                    await self._process_current_chat()
                except asyncio.TimeoutError:
                    logger.warning("chat_click_timeout", index=i)
                except Exception as e:
                    logger.error("chat_process_error", index=i, error=str(e))
                    self._stats["errors"] += 1

            write_heartbeat(
                status="healthy",
                processed=self._stats["processed"],
            )

        except Exception as e:
            logger.error("polling_cycle_error", error=str(e), exc_info=True)
            self._stats["errors"] += 1

    async def _process_current_chat(self) -> None:
        GREETING = "Ferrari Casino'ya hoşgeldiniz! Size nasıl yardımcı olabilirim?"

        messages = await self._console.get_all_messages()
        logger.info("chat_messages", count=len(messages))

        # No messages at all → send greeting
        if not messages:
            greeting_key = f"greeting_{id(self._console)}"
            if not self._state.has_responded(greeting_key):
                logger.info("sending_greeting")
                await self._console.send_reply(GREETING)
                self._state.mark_responded(greeting_key)
                self._stats["processed"] += 1
            return

        visitor_msgs = [m for m in messages if m.sender == "visitor" and m.content]
        agent_msgs = [m for m in messages if m.sender == "agent"]

        # Has messages but no visitor messages → send greeting if no agent msg yet
        if not visitor_msgs:
            if not agent_msgs:
                greeting_key = f"greeting_{len(messages)}"
                if not self._state.has_responded(greeting_key):
                    logger.info("sending_greeting_no_visitor_msgs")
                    await self._console.send_reply(GREETING)
                    self._state.mark_responded(greeting_key)
                    self._stats["processed"] += 1
            return

        last_visitor_msg = visitor_msgs[-1]
        msg_key = f"{hash(last_visitor_msg.content)}_{len(messages)}"

        if self._state.has_responded(msg_key):
            return

        last_msg_is_agent = messages[-1].sender == "agent"
        if last_msg_is_agent:
            return

        logger.info("generating_response", msg=last_visitor_msg.content[:60])
        response = await self._generate_response(messages, last_visitor_msg)
        await self._console.send_reply(response)

        self._state.mark_responded(msg_key)
        self._stats["processed"] += 1

        logger.info(
            "message_responded",
            visitor_msg=last_visitor_msg.content[:80],
            response=response[:80],
        )

    async def _generate_response(
        self, all_messages: list[ChatMessage], visitor_message: ChatMessage
    ) -> str:
        template_response = self._templates.match(visitor_message.content)
        if template_response:
            self._stats["template_responses"] += 1
            logger.debug("using_template")
            return template_response

        self._stats["ai_responses"] += 1
        logger.debug("using_claude")

        from src.comm100.api.models import Comm100Message
        from datetime import datetime, timezone

        conversation = []
        for msg in all_messages:
            conversation.append(
                Comm100Message(
                    id=str(hash(msg.content)),
                    chat_id="current",
                    sender_type="visitor" if msg.sender == "visitor" else "agent",
                    content=msg.content,
                    timestamp=datetime.now(tz=timezone.utc),
                )
            )

        return await self._claude.generate_response_safe(
            conversation=conversation,
            visitor_name="",
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
