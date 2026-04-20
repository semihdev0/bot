"""Load telegram poster config from YAML and environment variables."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.telegram.config.models import TelegramCredentials, TelegramPosterConfig

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config"


def load_telegram_config() -> TelegramPosterConfig:
    load_dotenv()

    path = CONFIG_DIR / "telegram_poster.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    data["telegram"] = TelegramCredentials(
        api_id=int(os.environ["TELEGRAM_API_ID"]),
        api_hash=os.environ["TELEGRAM_API_HASH"],
        phone_number=os.environ["TELEGRAM_PHONE"],
        session_name=data.get("session_name", "poster_account"),
    )

    return TelegramPosterConfig(**data)
