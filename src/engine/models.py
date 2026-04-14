"""Data models for the decision engine."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, computed_field


class UserProfile(BaseModel):
    """Data extracted from the user's profile page."""

    user_id: str
    username: str = ""
    bakiye: Decimal = Decimal("0")
    son_yatirim_tutari: Decimal = Decimal("0")
    son_yatirim_tarihi: datetime | None = None
    toplam_yatirim: Decimal = Decimal("0")
    toplam_cekim: Decimal = Decimal("0")
    kayit_tarihi: datetime | None = None

    @computed_field
    @property
    def kayit_gunu_farki(self) -> int:
        """Days since registration."""
        if self.kayit_tarihi is None:
            return 9999
        delta = datetime.now() - self.kayit_tarihi
        return delta.days


class BonusRequest(BaseModel):
    """A single bonus request from the pending list."""

    request_id: str
    user_id: str
    username: str = ""
    bonus_type: str
    requested_amount: Decimal | None = None
    status: str = "pending"


class Decision(BaseModel):
    """The result of evaluating rules against a user profile."""

    action: Literal["approve", "reject"]
    bonus_amount: Decimal | None = None
    reject_message: str | None = None
    matched_rule_name: str = ""
    confidence: Literal["rule_matched", "default_action"] = "rule_matched"
