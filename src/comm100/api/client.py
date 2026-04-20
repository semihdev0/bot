"""Async client for Comm100 Live Chat REST API with OAuth authentication."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import aiohttp
import structlog

from src.comm100.api.models import Comm100Chat, Comm100Message
from src.comm100.config.models import Comm100ApiConfig, Comm100Credentials
from src.comm100.exceptions import (
    Comm100ApiError,
    Comm100AuthError,
    Comm100RateLimitError,
)
from src.utils.retry import retry

logger = structlog.get_logger()


class Comm100Client:
    """Async client for Comm100 Live Chat REST API using OAuth."""

    def __init__(
        self, credentials: Comm100Credentials, config: Comm100ApiConfig
    ) -> None:
        self._credentials = credentials
        self._base_url = f"{credentials.api_base_url}/api/v4/livechat"
        self._global_url = f"{credentials.api_base_url}/api/v4/global"
        self._token_url = f"{credentials.api_base_url}/oauth/token"
        self._site_id = credentials.site_id
        self._timeout = aiohttp.ClientTimeout(total=config.timeout_seconds)
        self._session: aiohttp.ClientSession | None = None
        self._access_token: str | None = None

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(
            timeout=self._timeout,
        )
        await self._authenticate()
        logger.info("comm100_client_started", base_url=self._base_url)

    async def _authenticate(self) -> None:
        payload = {
            "grant_type": "password",
            "email": self._credentials.email,
            "password": self._credentials.password,
            "siteId": self._site_id,
        }
        try:
            async with self._s.post(self._token_url, data=payload) as resp:
                if resp.status == 401 or resp.status == 400:
                    body = await resp.text()
                    raise Comm100AuthError(
                        f"OAuth failed ({resp.status}): {body}"
                    )
                if resp.status >= 400:
                    body = await resp.text()
                    raise Comm100ApiError(
                        f"OAuth error ({resp.status}): {body}"
                    )
                data = await resp.json()
                self._access_token = data.get("access_token")
                if not self._access_token:
                    raise Comm100AuthError(
                        f"No access_token in response: {data}"
                    )
                logger.info("comm100_authenticated", email=self._credentials.email)
        except aiohttp.ClientError as e:
            raise Comm100ApiError(f"OAuth connection error: {e}") from e

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "x-api-siteid": self._site_id,
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("comm100_client_closed")

    @property
    def _s(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise Comm100ApiError("Client session not started. Call start() first.")
        return self._session

    async def _handle_response(self, resp: aiohttp.ClientResponse) -> dict | list:
        if resp.status == 401:
            logger.warning("token_expired_reauthenticating")
            await self._authenticate()
            raise Comm100AuthError("Token expired, re-authenticated.")
        if resp.status == 429:
            raise Comm100RateLimitError("Rate limit exceeded.")
        if resp.status >= 400:
            body = await resp.text()
            raise Comm100ApiError(f"API error {resp.status}: {body}")
        if resp.status == 204:
            return {}
        return await resp.json()

    @retry(max_attempts=3, retryable=(aiohttp.ClientError, asyncio.TimeoutError, Comm100AuthError))
    async def get_active_chats(self) -> list[Comm100Chat]:
        async with self._s.get(
            f"{self._base_url}/chats", headers=self._headers()
        ) as resp:
            data = await self._handle_response(resp)

        chats = []
        items = data if isinstance(data, list) else data.get("data", data.get("chats", []))
        for item in items:
            chat = self._parse_chat(item)
            if chat.status in ("chatting", "waiting", "active"):
                chats.append(chat)
        logger.debug("active_chats_fetched", count=len(chats))
        return chats

    @retry(max_attempts=3, retryable=(aiohttp.ClientError, asyncio.TimeoutError, Comm100AuthError))
    async def get_chat_messages(
        self, chat_id: str, limit: int = 50
    ) -> list[Comm100Message]:
        async with self._s.get(
            f"{self._base_url}/chats/{chat_id}/messages",
            params={"pageSize": limit},
            headers=self._headers(),
        ) as resp:
            data = await self._handle_response(resp)

        items = data if isinstance(data, list) else data.get("data", data.get("messages", []))
        messages = []
        for item in items:
            messages.append(self._parse_message(chat_id, item))
        messages.sort(key=lambda m: m.timestamp)
        return messages

    @retry(max_attempts=3, retryable=(aiohttp.ClientError, asyncio.TimeoutError, Comm100AuthError))
    async def send_message(self, chat_id: str, content: str) -> None:
        payload = {
            "message": content,
            "type": "text",
        }
        async with self._s.post(
            f"{self._base_url}/chats/{chat_id}/messages",
            json=payload,
            headers=self._headers(),
        ) as resp:
            await self._handle_response(resp)
        logger.info("message_sent", chat_id=chat_id, length=len(content))

    @retry(max_attempts=3, retryable=(aiohttp.ClientError, asyncio.TimeoutError, Comm100AuthError))
    async def accept_chat(self, chat_id: str) -> None:
        async with self._s.post(
            f"{self._base_url}/chats/{chat_id}/accept",
            headers=self._headers(),
        ) as resp:
            await self._handle_response(resp)
        logger.info("chat_accepted", chat_id=chat_id)

    @retry(max_attempts=2, retryable=(aiohttp.ClientError, asyncio.TimeoutError))
    async def test_connection(self) -> bool:
        try:
            async with self._s.get(
                f"{self._global_url}/agents", headers=self._headers()
            ) as resp:
                await self._handle_response(resp)
            logger.info("comm100_connection_ok")
            return True
        except (Comm100AuthError, Comm100ApiError) as e:
            logger.error("comm100_connection_failed", error=str(e))
            return False

    def _parse_chat(self, data: dict) -> Comm100Chat:
        visitor = data.get("visitor", {})
        return Comm100Chat(
            id=str(data.get("id", data.get("chatId", ""))),
            visitor_id=str(visitor.get("id", data.get("visitorId", ""))),
            visitor_name=visitor.get("name", data.get("visitorName", "")),
            status=data.get("status", ""),
            department=str(data.get("departmentId", data.get("department", ""))),
            created_at=self._parse_datetime(data.get("startTime", data.get("createdAt"))),
        )

    def _parse_message(self, chat_id: str, data: dict) -> Comm100Message:
        sender_type = data.get("senderType", data.get("type", "visitor"))
        if sender_type not in ("visitor", "agent", "system"):
            sender_type = "visitor" if sender_type in ("visitor", "1") else "agent"
        return Comm100Message(
            id=str(data.get("id", data.get("messageId", ""))),
            chat_id=chat_id,
            sender_type=sender_type,
            sender_id=str(data.get("senderId", data.get("agentId", ""))),
            content=data.get("content", data.get("message", data.get("text", ""))),
            timestamp=self._parse_datetime(data.get("time", data.get("createdAt")))
            or datetime.now(tz=timezone.utc),
        )

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
