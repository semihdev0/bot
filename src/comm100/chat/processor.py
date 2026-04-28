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

GREETING = "Ferrari Casino'ya hoşgeldiniz! Size nasıl yardımcı olabilirim?"


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
        self._greeted_chats: set[str] = set()
        self._last_sent_per_chat: dict[str, str] = {}
        self._poll_count = 0

    async def run_polling_cycle(self) -> None:
        try:
            self._poll_count += 1

            # Accept any new chat notification
            accepted = await self._console.accept_new_chat()
            if accepted:
                logger.info("new_chat_accepted_in_cycle")
                await asyncio.sleep(2)

            # Get visible chat items
            chat_items = await self._console.get_chat_items()
            if not chat_items:
                return

            # Process each chat one by one
            for i, item in enumerate(chat_items):
                try:
                    # Get chat identifier from item text
                    chat_name = await self._get_item_text(item)

                    # Click this chat to make it active
                    await item.dispatch_event("click")
                    await asyncio.sleep(1.5)

                    # Read messages from the now-active chat
                    messages = await self._console.get_all_messages()
                    logger.info("chat_check", index=i, name=chat_name, msgs=len(messages))

                    await self._handle_chat(chat_name, messages)

                except asyncio.TimeoutError:
                    logger.warning("chat_click_timeout", index=i)
                except Exception as e:
                    logger.error("chat_process_error", index=i, error=str(e))
                    self._stats["errors"] += 1

            write_heartbeat(status="healthy", processed=self._stats["processed"])

        except Exception as e:
            logger.error("polling_cycle_error", error=str(e), exc_info=True)
            self._stats["errors"] += 1

    async def _get_item_text(self, item) -> str:
        try:
            text = (await item.inner_text()).strip()
            return text.split("\n")[0][:30]
        except Exception:
            return "unknown"

    async def _handle_chat(self, chat_name: str, messages: list[ChatMessage]) -> None:
        visitor_msgs = [m for m in messages if m.sender == "visitor" and m.content]

        # Nothing to respond to until visitor speaks
        if not visitor_msgs:
            return

        # Stable chat identifier derived from visitor's first message content.
        # Independent of unstable list-preview text or DOM order.
        chat_id = f"chat_{hash(visitor_msgs[0].content)}"

        last_visitor = visitor_msgs[-1]
        # Key advances only when a new visitor message arrives
        msg_key = f"{chat_id}_v{len(visitor_msgs)}_{hash(last_visitor.content)}"

        if self._state.has_responded(msg_key):
            return

        # Last DOM message is from agent → our reply already landed; wait for next visitor msg
        if messages and messages[-1].sender == "agent":
            self._state.mark_responded(msg_key)
            return

        # First reply in this chat: prepend greeting to AI/template response
        if chat_id not in self._greeted_chats:
            logger.info("first_reply_with_greeting", chat=chat_name, chat_id=chat_id)
            body = await self._generate_response(messages, last_visitor)
            response = f"{GREETING}\n\n{body}" if body and body != GREETING else GREETING
        else:
            logger.info("generating_response", chat=chat_name, msg=last_visitor.content[:60])
            response = await self._generate_response(messages, last_visitor)

        # Belt-and-suspenders: never send the same text twice in a row to the same chat
        if self._last_sent_per_chat.get(chat_id) == response:
            logger.warning("duplicate_send_suppressed", chat_id=chat_id)
            self._state.mark_responded(msg_key)
            return

        sent = await self._console.send_reply(response)

        if sent:
            self._state.mark_responded(msg_key)
            self._greeted_chats.add(chat_id)
            self._last_sent_per_chat[chat_id] = response
            self._stats["processed"] += 1
            logger.info(
                "message_responded",
                chat=chat_name,
                chat_id=chat_id,
                visitor_msg=last_visitor.content[:80],
                response=response[:80],
            )
        else:
            logger.error("message_send_failed", chat=chat_name)

    async def _generate_response(
        self, all_messages: list[ChatMessage], visitor_message: ChatMessage
    ) -> str:
        template_response = self._templates.match(visitor_message.content)
        if template_response:
            self._stats["template_responses"] += 1
            return template_response

        self._stats["ai_responses"] += 1

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
