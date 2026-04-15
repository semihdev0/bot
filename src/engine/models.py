"""Data models for the decision engine - Betronix specific."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, computed_field


# --- History Entry Models ---


class DepositEntry(BaseModel):
    """A single deposit record from the Yatırımlar tab."""

    amount: Decimal = Decimal("0")
    status: str = ""  # "başarılı", "tamamlandı", etc.
    method: str = ""  # "kripto", "havale", "papara", etc.
    date: datetime | None = None
    is_successful: bool = False  # Green row = True

    @computed_field
    @property
    def hours_ago(self) -> int:
        """Hours since this deposit."""
        if self.date is None:
            return 99999
        delta = datetime.now() - self.date
        return int(delta.total_seconds() / 3600)

    @computed_field
    @property
    def days_ago(self) -> int:
        """Days since this deposit."""
        if self.date is None:
            return 9999
        return (datetime.now() - self.date).days

    @computed_field
    @property
    def is_crypto(self) -> bool:
        """Whether this deposit was made via crypto."""
        return "kripto" in self.method.lower()


class WithdrawalEntry(BaseModel):
    """A single withdrawal record from the Çekimler tab."""

    amount: Decimal = Decimal("0")
    status: str = ""
    date: datetime | None = None
    is_successful: bool = False


class BonusHistoryEntry(BaseModel):
    """A single bonus record from the Bonuslar tab."""

    bonus_name: str = ""
    amount: Decimal = Decimal("0")
    status: str = ""  # "Aktif", "Kullanıldı", "İptal Edildi", "Süresi Doldu"
    date: datetime | None = None

    @computed_field
    @property
    def is_approved(self) -> bool:
        """Whether this bonus was actually approved (Aktif or Kullanıldı)."""
        return self.status.lower() in ("aktif", "aktif", "kullanıldı", "kullanildi")


# --- History Collection Models ---


class DepositHistory(BaseModel):
    """Collection of deposit entries with query methods."""

    entries: list[DepositEntry] = []

    def get_successful(self) -> list[DepositEntry]:
        """Get all successful (green) deposits."""
        return [e for e in self.entries if e.is_successful]

    def get_successful_last_hours(self, hours: int) -> list[DepositEntry]:
        """Get successful deposits within the last N hours."""
        return [e for e in self.get_successful() if e.hours_ago <= hours]

    def get_successful_last_days(self, days: int) -> list[DepositEntry]:
        """Get successful deposits within the last N days."""
        return [e for e in self.get_successful() if e.days_ago <= days]

    def get_crypto_deposits(self) -> list[DepositEntry]:
        """Get successful crypto deposits."""
        return [e for e in self.get_successful() if e.is_crypto]

    def sum_successful_last_days(self, days: int) -> Decimal:
        """Sum of successful deposits in the last N days."""
        return sum(
            (e.amount for e in self.get_successful_last_days(days)),
            Decimal("0"),
        )

    @property
    def has_any_successful(self) -> bool:
        return len(self.get_successful()) > 0

    @property
    def last_successful(self) -> DepositEntry | None:
        """Most recent successful deposit."""
        successful = self.get_successful()
        if not successful:
            return None
        return min(successful, key=lambda e: e.hours_ago)


class WithdrawalHistory(BaseModel):
    """Collection of withdrawal entries with query methods."""

    entries: list[WithdrawalEntry] = []

    def get_successful(self) -> list[WithdrawalEntry]:
        return [e for e in self.entries if e.is_successful]

    def sum_successful_last_days(self, days: int) -> Decimal:
        cutoff = datetime.now() - timedelta(days=days)
        return sum(
            (
                e.amount
                for e in self.get_successful()
                if e.date is not None and e.date >= cutoff
            ),
            Decimal("0"),
        )


class BonusHistory(BaseModel):
    """Collection of bonus history entries with query methods."""

    entries: list[BonusHistoryEntry] = []

    def count_approved(self, bonus_name_contains: str) -> int:
        """Count approved bonuses matching a name pattern."""
        pattern = bonus_name_contains.lower()
        return sum(
            1
            for e in self.entries
            if e.is_approved and pattern in e.bonus_name.lower()
        )

    def has_approved_after(
        self, bonus_name_contains: str, after_date: datetime | None
    ) -> bool:
        """Check if a bonus was approved after a given date."""
        if after_date is None:
            return False
        pattern = bonus_name_contains.lower()
        return any(
            e
            for e in self.entries
            if e.is_approved
            and pattern in e.bonus_name.lower()
            and e.date is not None
            and e.date >= after_date
        )


# --- Main Profile Model ---


class UserProfile(BaseModel):
    """Data extracted from a Betronix user profile page.

    Maps to the 4 info cards on the profile:
    - Temel Bilgiler (basic info)
    - Hesap Bilgileri (account info)
    - Yatırım Bilgileri (deposit info)
    - Finansal Bilgiler (financial info)

    Plus extracted history from tabs:
    - Yatırımlar (deposits)
    - Çekimler (withdrawals)
    - Bonuslar (bonus history)
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

    # --- History Data (extracted from tabs) ---
    deposits: DepositHistory = DepositHistory()
    withdrawals: WithdrawalHistory = WithdrawalHistory()
    bonus_history: BonusHistory = BonusHistory()

    # --- Computed Fields ---

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
    def son_yatirim_saat_farki(self) -> int:
        """Hours since last deposit."""
        if self.son_yatirim_tarihi is None:
            return 99999
        delta = datetime.now() - self.son_yatirim_tarihi
        return int(delta.total_seconds() / 3600)

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

    # --- Deposit-derived fields ---

    @computed_field
    @property
    def basarili_yatirim_var(self) -> bool:
        """Whether the user has any successful deposit."""
        return self.deposits.has_any_successful

    @computed_field
    @property
    def son_24_saat_yatirim_var(self) -> bool:
        """Whether there's a successful deposit in the last 24 hours."""
        return len(self.deposits.get_successful_last_hours(24)) > 0

    @computed_field
    @property
    def son_5_saat_yatirim_var(self) -> bool:
        """Whether there's a successful deposit in the last 5 hours."""
        return len(self.deposits.get_successful_last_hours(5)) > 0

    @computed_field
    @property
    def kripto_yatirim_var(self) -> bool:
        """Whether the user has a successful crypto deposit."""
        return len(self.deposits.get_crypto_deposits()) > 0

    @computed_field
    @property
    def son_kripto_yatirim_tutari(self) -> Decimal:
        """Amount of the most recent crypto deposit."""
        crypto = self.deposits.get_crypto_deposits()
        if not crypto:
            return Decimal("0")
        return min(crypto, key=lambda e: e.hours_ago).amount

    @computed_field
    @property
    def son_7_gun_yatirim_toplami(self) -> Decimal:
        """Total successful deposits in the last 7 days."""
        return self.deposits.sum_successful_last_days(7)

    @computed_field
    @property
    def son_7_gun_cekim_toplami(self) -> Decimal:
        """Total successful withdrawals in the last 7 days."""
        return self.withdrawals.sum_successful_last_days(7)

    @computed_field
    @property
    def son_7_gun_net_kayip(self) -> Decimal:
        """Net loss in last 7 days (deposits - withdrawals). Positive = loss."""
        return self.son_7_gun_yatirim_toplami - self.son_7_gun_cekim_toplami

    @computed_field
    @property
    def hosgeldin_onay_sayisi(self) -> int:
        """Count of approved Hoşgeldin bonuses."""
        return self.bonus_history.count_approved("HOŞGELDİN")

    @computed_field
    @property
    def son_yatirimdan_sonra_ilk_kayip_var(self) -> bool:
        """Whether %100 İlk Kayıp bonus was approved after the last deposit."""
        return self.bonus_history.has_approved_after(
            "İLK KAYBINIZA ÖZEL", self.son_yatirim_tarihi
        )


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
    bonus_turnover: int | None = None
    reject_message: str | None = None
    matched_rule_name: str = ""
    confidence: Literal["rule_matched", "default_action"] = "rule_matched"
