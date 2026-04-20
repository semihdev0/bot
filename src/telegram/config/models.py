"""Pydantic models for telegram poster configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TelegramCredentials(BaseModel):
    api_id: int
    api_hash: str
    phone_number: str
    session_name: str = "poster_account"


class ScheduleEntry(BaseModel):
    time: str
    message: str
    image: str


class PostingConfig(BaseModel):
    delay_between_channels_seconds: int = 3
    retry_on_failure: int = 3
    retry_delay_seconds: int = 30
    timezone: str = "Europe/Istanbul"


class TelegramPosterConfig(BaseModel):
    telegram: TelegramCredentials
    channels: list[str] = Field(..., min_length=1)
    schedule: dict[str, list[ScheduleEntry]]
    posting: PostingConfig = PostingConfig()
