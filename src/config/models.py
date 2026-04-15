"""Pydantic models for all configuration schemas."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


# --- Settings ---

class ViewportConfig(BaseModel):
    width: int = 1920
    height: int = 1080


class BrowserConfig(BaseModel):
    headless: bool = True
    slow_mo: int = 100
    timeout: int = 30000
    viewport: ViewportConfig = ViewportConfig()


class BackofficeConfig(BaseModel):
    base_url: str
    login_path: str = "/login"
    bonus_list_path: str = "/bonus/pending"
    user_profile_path_template: str = "/users/{user_id}/profile"


class PollingConfig(BaseModel):
    interval_seconds: int = 60
    max_requests_per_cycle: int = 50
    pause_on_empty_seconds: int = 120


class SessionConfig(BaseModel):
    relogin_interval_minutes: int = 60
    max_login_retries: int = 5
    login_retry_delay_seconds: int = 30


class Settings(BaseModel):
    browser: BrowserConfig = BrowserConfig()
    backoffice: BackofficeConfig
    polling: PollingConfig = PollingConfig()
    session: SessionConfig = SessionConfig()


# --- Credentials (from .env) ---

class Credentials(BaseModel):
    url: str
    username: str
    password: str
    company_code: str


# --- Selectors ---

class SelectorEntry(BaseModel):
    strategy: Literal["css", "xpath", "text", "role"] = "css"
    value: str
    role: str | None = None  # only used when strategy == "role"


# --- Bonus Rules ---

class Condition(BaseModel):
    field: str
    operator: Literal[
        "==", "!=", ">", ">=", "<", "<=",
        "in", "not_in", "contains", "between",
        "is_empty", "is_not_empty",
    ]
    value: Any = None


class TierEntry(BaseModel):
    min: Decimal
    max: Decimal
    bonus: Decimal


class BonusCalculation(BaseModel):
    method: Literal["percentage", "fixed", "tiered"]
    base_field: str | None = None
    percentage: Decimal | None = None
    fixed_amount: Decimal | None = None
    tiers: list[TierEntry] | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    turnover: int | None = None


class Rule(BaseModel):
    name: str
    conditions: list[Condition]
    action: Literal["approve", "reject"]
    bonus_calculation: BonusCalculation | None = None
    reject_message_key: str | None = None


class BonusTypeConfig(BaseModel):
    display_name: str = ""
    default_action: Literal["approve", "reject"] = "reject"
    default_reject_message_key: str = "genel_uygun_degil"
    rules: list[Rule] = Field(default_factory=list)


class BonusRulesConfig(BaseModel):
    bonus_types: dict[str, BonusTypeConfig] = Field(default_factory=dict)


# --- Messages ---

class MessagesConfig(BaseModel):
    rejection_messages: dict[str, str] = Field(default_factory=dict)
