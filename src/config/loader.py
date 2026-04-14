"""Reads YAML config files and merges with environment variables."""

from __future__ import annotations

from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from src.config.models import (
    BonusRulesConfig,
    Credentials,
    MessagesConfig,
    Settings,
)
from src.config.selectors import SelectorRegistry

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _load_yaml(filename: str) -> dict:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_credentials() -> Credentials:
    """Load credentials from .env file."""
    load_dotenv()
    import os

    return Credentials(
        url=os.environ["BACKOFFICE_URL"],
        username=os.environ["BACKOFFICE_USERNAME"],
        password=os.environ["BACKOFFICE_PASSWORD"],
        company_code=os.environ["BACKOFFICE_COMPANY_CODE"],
    )


def load_settings() -> Settings:
    data = _load_yaml("settings.yaml")
    return Settings(**data)


def load_selectors() -> SelectorRegistry:
    data = _load_yaml("selectors.yaml")
    return SelectorRegistry(data)


def load_bonus_rules() -> BonusRulesConfig:
    data = _load_yaml("bonus_rules.yaml")
    return BonusRulesConfig(**data)


def load_messages() -> MessagesConfig:
    data = _load_yaml("messages.yaml")
    return MessagesConfig(**data)


class AppConfig:
    """Aggregates all configuration into a single object."""

    def __init__(self) -> None:
        self.credentials = load_credentials()
        self.settings = load_settings()
        self.selectors = load_selectors()
        self.bonus_rules = load_bonus_rules()
        self.messages = load_messages()

    def get_rejection_message(self, key: str) -> str:
        return self.messages.rejection_messages.get(
            key, "Bonus talebiniz reddedilmiştir."
        )


def load_all_config() -> AppConfig:
    """Load and validate all configuration. Fails fast on errors."""
    try:
        return AppConfig()
    except (ValidationError, FileNotFoundError, KeyError) as e:
        raise SystemExit(f"Configuration error: {e}") from e
