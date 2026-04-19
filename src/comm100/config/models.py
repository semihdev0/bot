"""Pydantic models for Comm100 chatbot configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Comm100ApiConfig(BaseModel):
    region: int = 1
    timeout_seconds: int = 30
    max_retries: int = 3


class Comm100PollingConfig(BaseModel):
    interval_seconds: int = 5
    max_chats_per_cycle: int = 20
    message_fetch_limit: int = 50


class ClaudeConfig(BaseModel):
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 500
    temperature: float = 0.7
    max_context_messages: int = 10


class Comm100SessionConfig(BaseModel):
    health_interval_seconds: int = 60


class Comm100Settings(BaseModel):
    api: Comm100ApiConfig = Comm100ApiConfig()
    polling: Comm100PollingConfig = Comm100PollingConfig()
    claude: ClaudeConfig = ClaudeConfig()
    session: Comm100SessionConfig = Comm100SessionConfig()


class Comm100Credentials(BaseModel):
    email: str
    api_key: str
    site_id: str
    region: int = 1


class AnthropicCredentials(BaseModel):
    api_key: str


class TemplateEntry(BaseModel):
    keywords: list[str]
    match_mode: Literal["any", "all"] = "any"
    response: str
    priority: int = 50


class TemplatesConfig(BaseModel):
    templates: dict[str, TemplateEntry] = Field(default_factory=dict)


class PersonaConfig(BaseModel):
    name: str = "Destek"
    role: str = "Canli destek temsilcisi"


class SystemPromptConfig(BaseModel):
    persona: PersonaConfig = PersonaConfig()
    system_prompt: str = ""
    knowledge_base: str = ""
