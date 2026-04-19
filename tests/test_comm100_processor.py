"""Tests for Comm100 chat processor."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.comm100.api.models import Comm100Chat, Comm100Message
from src.comm100.chat.processor import ChatProcessor
from src.comm100.chat.state import ChatStateTracker
from src.comm100.chat.template_matcher import TemplateMatcher
from src.comm100.config.models import (
    ClaudeConfig,
    Comm100PollingConfig,
    Comm100SessionConfig,
    Comm100Settings,
    Comm100ApiConfig,
    TemplateEntry,
    TemplatesConfig,
)


def _make_message(
    msg_id: str,
    chat_id: str = "chat1",
    sender_type: str = "visitor",
    content: str = "test",
) -> Comm100Message:
    return Comm100Message(
        id=msg_id,
        chat_id=chat_id,
        sender_type=sender_type,
        content=content,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_chat(chat_id: str = "chat1", status: str = "chatting") -> Comm100Chat:
    return Comm100Chat(
        id=chat_id,
        visitor_id="v1",
        visitor_name="Test User",
        status=status,
    )


@pytest.fixture
def config() -> Comm100Settings:
    return Comm100Settings(
        api=Comm100ApiConfig(),
        polling=Comm100PollingConfig(interval_seconds=1),
        claude=ClaudeConfig(),
        session=Comm100SessionConfig(),
    )


@pytest.fixture
def template_matcher() -> TemplateMatcher:
    templates = TemplatesConfig(
        templates={
            "greeting": TemplateEntry(
                keywords=["merhaba"],
                match_mode="any",
                response="Hosgeldiniz!",
                priority=100,
            )
        }
    )
    return TemplateMatcher(templates)


@pytest.fixture
def state() -> ChatStateTracker:
    s = ChatStateTracker.__new__(ChatStateTracker)
    s._responded_message_ids = set()
    s._active_chat_ids = set()
    return s


@pytest.fixture
def api_client() -> AsyncMock:
    client = AsyncMock()
    client.get_active_chats = AsyncMock(return_value=[])
    client.get_chat_messages = AsyncMock(return_value=[])
    client.send_message = AsyncMock()
    client.accept_chat = AsyncMock()
    return client


@pytest.fixture
def claude_client() -> AsyncMock:
    client = AsyncMock()
    client.generate_response_safe = AsyncMock(return_value="AI yaniti.")
    return client


@pytest.fixture
def processor(
    api_client, claude_client, template_matcher, state, config
) -> ChatProcessor:
    return ChatProcessor(api_client, claude_client, template_matcher, state, config)


class TestChatProcessor:
    @pytest.mark.asyncio
    async def test_empty_chat_list(self, processor, api_client):
        await processor.run_polling_cycle()
        api_client.get_active_chats.assert_awaited_once()
        api_client.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_template_match_takes_priority(self, processor, api_client, claude_client):
        chat = _make_chat()
        msg = _make_message("m1", content="merhaba")

        api_client.get_active_chats.return_value = [chat]
        api_client.get_chat_messages.return_value = [msg]

        await processor.run_polling_cycle()

        api_client.send_message.assert_awaited_once_with("chat1", "Hosgeldiniz!")
        claude_client.generate_response_safe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claude_fallback(self, processor, api_client, claude_client):
        chat = _make_chat()
        msg = _make_message("m1", content="nasil yardimci olabilirsiniz")

        api_client.get_active_chats.return_value = [chat]
        api_client.get_chat_messages.return_value = [msg]

        await processor.run_polling_cycle()

        claude_client.generate_response_safe.assert_awaited_once()
        api_client.send_message.assert_awaited_once_with("chat1", "AI yaniti.")

    @pytest.mark.asyncio
    async def test_skip_already_responded(self, processor, api_client, state):
        chat = _make_chat()
        msg = _make_message("m1", content="merhaba")
        state.mark_responded("m1")

        api_client.get_active_chats.return_value = [chat]
        api_client.get_chat_messages.return_value = [msg]

        await processor.run_polling_cycle()

        api_client.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skip_agent_messages(self, processor, api_client):
        chat = _make_chat()
        msg = _make_message("m1", sender_type="agent", content="agent mesaji")

        api_client.get_active_chats.return_value = [chat]
        api_client.get_chat_messages.return_value = [msg]

        await processor.run_polling_cycle()

        api_client.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_accepts_new_chat(self, processor, api_client):
        chat = _make_chat()
        api_client.get_active_chats.return_value = [chat]
        api_client.get_chat_messages.return_value = []

        await processor.run_polling_cycle()

        api_client.accept_chat.assert_awaited_once_with("chat1")

    @pytest.mark.asyncio
    async def test_does_not_reaccept_active_chat(self, processor, api_client, state):
        chat = _make_chat()
        state.add_active_chat("chat1")

        api_client.get_active_chats.return_value = [chat]
        api_client.get_chat_messages.return_value = []

        await processor.run_polling_cycle()

        api_client.accept_chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_unresponded_messages(self, processor, api_client, claude_client):
        chat = _make_chat()
        m1 = _make_message("m1", content="ilk mesaj")
        m2 = _make_message("m2", content="ikinci mesaj")

        api_client.get_active_chats.return_value = [chat]
        api_client.get_chat_messages.return_value = [m1, m2]

        await processor.run_polling_cycle()

        assert api_client.send_message.await_count == 2
