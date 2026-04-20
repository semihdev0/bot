"""APScheduler configuration for Telegram poster."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.telegram.config.models import TelegramPosterConfig
from src.telegram.poster import ChannelPoster

logger = structlog.get_logger()

DAY_TO_DOW = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}


class PostScheduler:
    def __init__(self, config: TelegramPosterConfig, poster: ChannelPoster):
        self._scheduler = AsyncIOScheduler(timezone=config.posting.timezone)
        self._config = config
        self._poster = poster

    def setup_jobs(self) -> None:
        for day_name, entries in self._config.schedule.items():
            dow = DAY_TO_DOW.get(day_name)
            if not dow:
                logger.warning("unknown_day_skipped", day=day_name)
                continue

            for i, entry in enumerate(entries):
                hour, minute = entry.time.split(":")
                job_id = f"{day_name}_{i}_{entry.time}"

                self._scheduler.add_job(
                    self._poster.post_to_all_channels,
                    CronTrigger(
                        day_of_week=dow,
                        hour=int(hour),
                        minute=int(minute),
                    ),
                    args=[entry],
                    id=job_id,
                    replace_existing=True,
                )
                logger.info("job_scheduled", job_id=job_id, day=day_name, time=entry.time)

    def start(self) -> None:
        self._scheduler.start()
        logger.info("scheduler_started", job_count=len(self._scheduler.get_jobs()))

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
