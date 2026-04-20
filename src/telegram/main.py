"""Entry point for the Telegram Channel Auto-Poster.

Run: python -m src.telegram.main
"""

from __future__ import annotations

import asyncio
import signal

import structlog

from src.monitoring.logger import setup_logging
from src.telegram.client import TelegramClientManager
from src.telegram.config.loader import load_telegram_config
from src.telegram.poster import ChannelPoster
from src.telegram.scheduler import PostScheduler

logger = structlog.get_logger()


async def main() -> None:
    setup_logging()
    logger.info("telegram_poster_starting")

    config = load_telegram_config()
    logger.info(
        "config_loaded",
        channels=len(config.channels),
        scheduled_days=list(config.schedule.keys()),
    )

    client_manager = TelegramClientManager(config.telegram)
    await client_manager.start()
    logger.info("telegram_client_connected")

    poster = ChannelPoster(client_manager, config)
    scheduler = PostScheduler(config, poster)
    scheduler.setup_jobs()
    scheduler.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("telegram_poster_running")
    await stop_event.wait()

    logger.info("telegram_poster_shutting_down")
    scheduler.shutdown()
    await client_manager.stop()
    logger.info("telegram_poster_stopped")


if __name__ == "__main__":
    asyncio.run(main())
