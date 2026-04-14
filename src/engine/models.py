"""Data models for the decision engine - Betronix specific."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, computed_field


class UserProfile(BaseModel):
    """Data extracted from a Betronix user profile page.

    Maps to the 4 info cards on the profile:
    - Temel Bilgiler (basic info)
    - Hesap Bilgileri (account info)
    - Yatırım Bilgileri (deposit info)
    - Finansal Bilgiler (financial info)
    """

    user_id: str
    username: str = ""

    # --- Finansal Bilgiler ---
    bakiye: Decimal = Decimal("0")
    bonus_bakiye: Decimal = Decimal("0")
    toplam_yatirim: Decimal = Decimal("0")
    toplam_cekim: Decimal = Decimal("0")
    kar_zarar: Decimal = Decimal("0")

    # --- Yatırım Bilgileri ---
    ilk_yatirim_tarihi: datetime | None = None
    son_yatirim_tarihi: datetime | None = None
    son_yatirim_tutari: Decimal = Decimal("0")
    yatirim_sayisi: int = 0
    cekim_sayisi: int = 0
    son_kullanilan_bonus: str = ""

    # --- Hesap Bilgileri ---
    durum: str = ""  # Aktif, Pasif, vb.
    kayit_tarihi: datetime | None = None
    son_giris: datetime | None = None

    # --- Aktif Bonus ---
    aktif_bonus: str = ""  # Aktif bonus adı (varsa)

    @computed_field
    @property
    def kayit_gunu_farki(self) -> int:
        """Days since registration."""
        if self.kayit_tarihi is None:
            return 9999
        delta = datetime.now() - self.kayit_tarihi
        return delta.days

    @computed_field
    @property
    def son_yatirim_gunu_farki(self) -> int:
        """Days since last deposit."""
        if self.son_yatirim_tarihi is None:
            return 9999
        delta = datetime.now() - self.son_yatirim_tarihi
        return delta.days

    @computed_field
    @property
    def hesap_aktif(self) -> bool:
        """Whether the account is active."""
        return self.durum.lower() in ("aktif", "active")

    @computed_field
    @property
    def aktif_bonus_var(self) -> bool:
        """Whether the user has an active bonus."""
        return bool(self.aktif_bonus and self.aktif_bonus.strip() not in ("", "-"))


class BonusRequest(BaseModel):
    """A single bonus request from the Betronix pending list."""

    request_id: str
    user_id: str
    username: str = ""
    bonus_type: str
    requested_amount: Decimal | None = None
    turnover: str = ""  # e.g. "3x"
    status: str = "pending"


class Decision(BaseModel):
    """The result of evaluating rules against a user profile."""

    action: Literal["approve", "reject"]
    bonus_amount: Decimal | None = None
    bonus_turnover: int | None = None  # Custom turnover multiplier
    reject_message: str | None = None
    matched_rule_name: str = ""
    confidence: Literal["rule_matched", "default_action"] = "rule_matched"
