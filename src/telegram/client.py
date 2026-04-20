"""Pyrogram client wrapper for the auto-poster."""

from __future__ import annotations

from pathlib import Path

from pyrogram import Client

from src.telegram.config.models import TelegramCredentials

SESSIONS_DIR = Path(__file__).resolve().parent.parent.parent / "sessions"


class TelegramClientManager:
    def __init__(self, config: TelegramCredentials):
        self._config = config
        self._client: Client | None = None

    async def start(self) -> Client:
        SESSIONS_DIR.mkdir(exist_ok=True)
        self._client = Client(
            name=str(SESSIONS_DIR / self._config.session_name),
            api_id=self._config.api_id,
            api_hash=self._config.api_hash,
        )
        await self._client.start()
        return self._client

    async def stop(self) -> None:
        if self._client:
            await self._client.stop()
            self._client = None

    @property
    def client(self) -> Client:
        if not self._client:
            raise RuntimeError("Client not started")
        return self._client
