"""Core posting logic - sends message+image to all configured channels."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from pyrogram.errors import ChannelPrivate, ChatWriteForbidden, FloodWait

from src.telegram.client import TelegramClientManager
from src.telegram.config.models import ScheduleEntry, TelegramPosterConfig

logger = structlog.get_logger()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ChannelPoster:
    def __init__(
        self, client_manager: TelegramClientManager, config: TelegramPosterConfig
    ):
        self._client_manager = client_manager
        self._config = config

    async def post_to_all_channels(self, entry: ScheduleEntry) -> None:
        image_path = PROJECT_ROOT / entry.image
        if not image_path.exists():
            logger.error("image_not_found", path=str(image_path))
            return

        logger.info("posting_started", channels=len(self._config.channels))

        for channel in self._config.channels:
            await self._post_with_retry(channel, entry.message, image_path)
            await asyncio.sleep(self._config.posting.delay_between_channels_seconds)

        logger.info("posting_completed")

    async def _post_with_retry(
        self, channel: str, message: str, image_path: Path
    ) -> None:
        for attempt in range(1, self._config.posting.retry_on_failure + 1):
            try:
                await self._client_manager.client.send_photo(
                    chat_id=channel,
                    photo=str(image_path),
                    caption=message,
                )
                logger.info("post_sent", channel=channel)
                return
            except FloodWait as e:
                logger.warning("flood_wait", seconds=e.value, channel=channel)
                await asyncio.sleep(e.value + 5)
            except (ChannelPrivate, ChatWriteForbidden) as e:
                logger.error("channel_access_error", channel=channel, error=str(e))
                return
            except Exception as e:
                if attempt < self._config.posting.retry_on_failure:
                    logger.warning(
                        "post_retry",
                        channel=channel,
                        attempt=attempt,
                        error=str(e),
                    )
                    await asyncio.sleep(self._config.posting.retry_delay_seconds)
                else:
                    logger.error(
                        "post_failed",
                        channel=channel,
                        attempts=attempt,
                        error=str(e),
                    )
