"""Reads Comm100 YAML config files and merges with environment variables."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from src.comm100.config.models import (
    AnthropicCredentials,
    Comm100Credentials,
    Comm100Settings,
    SystemPromptConfig,
    TemplateEntry,
    TemplatesConfig,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config"


def _load_yaml(filename: str) -> dict:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_comm100_credentials() -> Comm100Credentials:
    load_dotenv()
    return Comm100Credentials(
        email=os.environ["COMM100_EMAIL"],
        password=os.environ["COMM100_PASSWORD"],
        site_id=os.environ["COMM100_SITE_ID"],
    )


def load_anthropic_credentials() -> AnthropicCredentials:
    load_dotenv()
    return AnthropicCredentials(api_key=os.environ["ANTHROPIC_API_KEY"])


def load_comm100_settings() -> Comm100Settings:
    data = _load_yaml("comm100_settings.yaml")
    return Comm100Settings(**data)


def load_templates() -> TemplatesConfig:
    data = _load_yaml("comm100_templates.yaml")
    templates = {}
    for key, val in data.items():
        if isinstance(val, dict) and "keywords" in val:
            templates[key] = TemplateEntry(**val)
    return TemplatesConfig(templates=templates)


def load_system_prompt() -> SystemPromptConfig:
    data = _load_yaml("comm100_system_prompt.yaml")
    return SystemPromptConfig(**data)


class Comm100AppConfig:
    """Aggregates all Comm100 configuration into a single object."""

    def __init__(self) -> None:
        self.credentials = load_comm100_credentials()
        self.anthropic_credentials = load_anthropic_credentials()
        self.settings = load_comm100_settings()
        self.templates = load_templates()
        self.system_prompt = load_system_prompt()


def load_comm100_config() -> Comm100AppConfig:
    """Load and validate all Comm100 configuration. Fails fast on errors."""
    try:
        return Comm100AppConfig()
    except (ValidationError, FileNotFoundError, KeyError) as e:
        raise SystemExit(f"Comm100 configuration error: {e}") from e
