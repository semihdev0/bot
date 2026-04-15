"""Edge case tests for error handling and data parsing robustness."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.config.models import (
    BonusCalculation,
    BonusRulesConfig,
    BonusTypeConfig,
    Condition,
    Rule,
)
from src.engine.models import (
    BonusHistory,
    BonusHistoryEntry,
    BonusRequest,
    Decision,
    DepositEntry,
    DepositHistory,
    UserProfile,
    WithdrawalEntry,
    WithdrawalHistory,
)
from src.engine.rule_engine import evaluate, _to_decimal, _evaluate_condition
from src.pages.user_profile_page import UserProfilePage
from src.pages.bonus_list_page import BonusListPage


# ══════════════════════════════════════════════════════════════════
# 1. Decimal Parsing Edge Cases (Turkish number format)
# ══════════════════════════════════════════════════════════════════


class TestDecimalParsing:
    """Test _parse_decimal with various Turkish number formats."""

    parse = staticmethod(UserProfilePage._parse_decimal)

    def test_simple_integer(self):
        assert self.parse("100 ₺") == Decimal("100")

    def test_thousands_separator(self):
        """1.000 = 1000 (dot = thousands separator)."""
        assert self.parse("1.000 ₺") == Decimal("1000")

    def test_multiple_thousands(self):
        """1.000.000 = 1000000 (all dots are thousands separators)."""
        assert self.parse("1.000.000 ₺") == Decimal("1000000")

    def test_large_number_three_groups(self):
        """13.915.000 = 13915000."""
        assert self.parse("13.915.000") == Decimal("13915000")

    def test_comma_decimal(self):
        """2.500,50 = 2500.50 (comma = decimal)."""
        assert self.parse("2.500,50 ₺") == Decimal("2500.50")

    def test_comma_only(self):
        """100,50 = 100.50."""
        assert self.parse("100,50") == Decimal("100.50")

    def test_real_decimal_with_dot(self):
        """3.50 → 3.50 (not thousands - only 2 digits after dot)."""
        assert self.parse("3.50") == Decimal("3.50")

    def test_plus_prefix(self):
        assert self.parse("+1.000 ₺") == Decimal("1000")

    def test_minus_prefix(self):
        assert self.parse("-500 ₺") == Decimal("-500")

    def test_negative_thousands(self):
        assert self.parse("-1.000 ₺") == Decimal("-1000")

    def test_empty_string(self):
        assert self.parse("") == Decimal("0")

    def test_dash(self):
        assert self.parse("-") == Decimal("0")

    def test_tl_suffix(self):
        assert self.parse("250 TL") == Decimal("250")

    def test_no_space_currency(self):
        assert self.parse("3.000₺") == Decimal("3000")

    def test_garbage_input(self):
        """Invalid input should return 0, not crash."""
        assert self.parse("abc xyz") == Decimal("0")

    def test_zero(self):
        assert self.parse("0 ₺") == Decimal("0")


# ══════════════════════════════════════════════════════════════════
# 2. Deposit/Withdrawal/Bonus Model Edge Cases
# ══════════════════════════════════════════════════════════════════


class TestDepositHistory:
    """Edge cases for DepositHistory collection methods."""

    def test_last_successful_prefers_dated_entries(self):
        """Should return the dated entry, not the None-dated one."""
        now = datetime.now()
        history = DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("500"), is_successful=True, date=None,
            ),
            DepositEntry(
                amount=Decimal("200"), is_successful=True,
                date=now - timedelta(hours=1),
            ),
        ])
        last = history.last_successful
        assert last is not None
        assert last.amount == Decimal("200")
        assert last.date is not None

    def test_last_successful_fallback_to_undated(self):
        """If no dated entries, fall back to first undated one."""
        history = DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("300"), is_successful=True, date=None,
            ),
        ])
        last = history.last_successful
        assert last is not None
        assert last.amount == Decimal("300")

    def test_last_successful_empty(self):
        history = DepositHistory(entries=[])
        assert history.last_successful is None

    def test_last_successful_only_failed(self):
        """Only failed deposits → None."""
        history = DepositHistory(entries=[
            DepositEntry(amount=Decimal("100"), is_successful=False),
        ])
        assert history.last_successful is None

    def test_hours_ago_none_date(self):
        """DepositEntry with no date returns 99999 hours."""
        entry = DepositEntry(amount=Decimal("100"), date=None)
        assert entry.hours_ago == 99999

    def test_successful_last_hours_excludes_old(self):
        now = datetime.now()
        history = DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("100"), is_successful=True,
                date=now - timedelta(hours=2),
            ),
            DepositEntry(
                amount=Decimal("200"), is_successful=True,
                date=now - timedelta(hours=30),
            ),
        ])
        recent = history.get_successful_last_hours(24)
        assert len(recent) == 1
        assert recent[0].amount == Decimal("100")

    def test_sum_successful_last_days(self):
        now = datetime.now()
        history = DepositHistory(entries=[
            DepositEntry(
                amount=Decimal("100"), is_successful=True,
                date=now - timedelta(days=1),
            ),
            DepositEntry(
                amount=Decimal("200"), is_successful=True,
                date=now - timedelta(days=3),
            ),
            DepositEntry(
                amount=Decimal("500"), is_successful=True,
                date=now - timedelta(days=10),
            ),
        ])
        total = history.sum_successful_last_days(7)
        assert total == Decimal("300")  # 100 + 200

    def test_crypto_detection(self):
        entry = DepositEntry(
            amount=Decimal("100"), method="Kripto Bitcoin", is_successful=True,
        )
        assert entry.is_crypto is True

        entry2 = DepositEntry(
            amount=Decimal("100"), method="Havale", is_successful=True,
        )
        assert entry2.is_crypto is False


class TestBonusHistory:
    """Edge cases for BonusHistory model."""

    def test_is_approved_variants(self):
        """All Turkish variants of 'approved' statuses should match."""
        for status in ("Aktif", "aktif", "Kullanıldı", "kullanıldı", "kullanildi"):
            entry = BonusHistoryEntry(
                bonus_name="Test", status=status, amount=Decimal("100"),
            )
            assert entry.is_approved is True, f"'{status}' should be approved"

    def test_not_approved_statuses(self):
        """Expired and cancelled should NOT count as approved."""
        for status in ("Süresi Doldu", "İptal Edildi", "iptal edildi", "Reddedildi"):
            entry = BonusHistoryEntry(
                bonus_name="Test", status=status, amount=Decimal("100"),
            )
            assert entry.is_approved is False, f"'{status}' should not be approved"

    def test_count_approved_case_insensitive(self):
        history = BonusHistory(entries=[
            BonusHistoryEntry(
                bonus_name="%300 HOŞGELDİN BONUSU", status="Aktif",
                amount=Decimal("50"),
            ),
            BonusHistoryEntry(
                bonus_name="%300 Hoşgeldin Bonusu", status="Kullanıldı",
                amount=Decimal("100"),
            ),
            BonusHistoryEntry(
                bonus_name="%300 HOŞGELDİN BONUSU", status="Süresi Doldu",
                amount=Decimal("75"),
            ),
        ])
        count = history.count_approved("HOŞGELDİN")
        assert count == 2  # Expired one doesn't count

    def test_has_approved_after_with_none_date(self):
        """Should return False when after_date is None."""
        history = BonusHistory(entries=[
            BonusHistoryEntry(
                bonus_name="Test", status="Aktif",
                date=datetime.now(), amount=Decimal("100"),
            ),
        ])
        assert history.has_approved_after("Test", None) is False


class TestWithdrawalHistory:
    """Edge cases for WithdrawalHistory."""

    def test_sum_excludes_none_dates(self):
        history = WithdrawalHistory(entries=[
            WithdrawalEntry(
                amount=Decimal("100"), is_successful=True, date=None,
            ),
            WithdrawalEntry(
                amount=Decimal("200"), is_successful=True,
                date=datetime.now() - timedelta(days=1),
            ),
        ])
        total = history.sum_successful_last_days(7)
        assert total == Decimal("200")  # None-dated excluded


# ══════════════════════════════════════════════════════════════════
# 3. Rule Engine Edge Cases
# ══════════════════════════════════════════════════════════════════


class TestRuleEngineEdgeCases:
    """Edge cases in rule evaluation."""

    def _profile(self, **kwargs):
        defaults = {
            "user_id": "test", "durum": "Aktif", "bakiye": Decimal("10"),
            "son_yatirim_tutari": Decimal("100"),
            "son_yatirim_tarihi": datetime.now(),
        }
        defaults.update(kwargs)
        return UserProfile(**defaults)

    def test_to_decimal_with_none(self):
        """_to_decimal(None) should return 0, not crash."""
        assert _to_decimal(None) == Decimal("0")

    def test_to_decimal_with_invalid_string(self):
        assert _to_decimal("abc") == Decimal("0")

    def test_to_decimal_with_int(self):
        assert _to_decimal(5) == Decimal("5")

    def test_to_decimal_with_float(self):
        assert _to_decimal(3.14) == Decimal("3.14")

    def test_to_decimal_with_bool(self):
        """bool is subclass of int, should convert."""
        assert _to_decimal(True) == Decimal("1")
        assert _to_decimal(False) == Decimal("0")

    def test_between_with_valid_list(self):
        profile = self._profile(bakiye=Decimal("50"))
        cond = Condition(field="bakiye", operator="between", value=[10, 100])
        assert _evaluate_condition(profile, cond) is True

    def test_between_with_out_of_range(self):
        profile = self._profile(bakiye=Decimal("200"))
        cond = Condition(field="bakiye", operator="between", value=[10, 100])
        assert _evaluate_condition(profile, cond) is False

    def test_between_with_invalid_list(self):
        """between with single-element list should raise ValueError."""
        profile = self._profile(bakiye=Decimal("50"))
        cond = Condition(field="bakiye", operator="between", value=[10])
        with pytest.raises(ValueError, match="between"):
            _evaluate_condition(profile, cond)

    def test_between_with_non_list(self):
        profile = self._profile(bakiye=Decimal("50"))
        cond = Condition(field="bakiye", operator="between", value=10)
        with pytest.raises(ValueError, match="between"):
            _evaluate_condition(profile, cond)

    def test_unknown_field_raises(self):
        """Unknown profile field should raise ValueError."""
        profile = self._profile()
        cond = Condition(field="nonexistent_field", operator="==", value=True)
        with pytest.raises(ValueError, match="Unknown profile field"):
            _evaluate_condition(profile, cond)

    def test_rule_with_unknown_field_skipped_gracefully(self):
        """Rule with unknown field should be skipped, not crash the engine."""
        profile = self._profile()
        request = BonusRequest(
            request_id="T1", user_id="test", bonus_type="test_bonus",
        )
        rules_config = BonusRulesConfig(bonus_types={
            "test_bonus": BonusTypeConfig(
                display_name="Test",
                default_action="reject",
                default_reject_message_key="genel_uygun_degil",
                rules=[
                    Rule(
                        name="Broken rule",
                        conditions=[
                            Condition(
                                field="nonexistent_field",
                                operator="==",
                                value=True,
                            ),
                        ],
                        action="approve",
                    ),
                ],
            ),
        })
        messages = {"genel_uygun_degil": "Genel ret."}
        decision = evaluate(profile, request, rules_config, messages)

        # Should fall through to default action (reject), not crash
        assert decision.action == "reject"
        assert decision.matched_rule_name == "default"


# ══════════════════════════════════════════════════════════════════
# 4. Decision Model Edge Cases
# ══════════════════════════════════════════════════════════════════


class TestDecision:
    """Edge cases for the Decision model."""

    def test_decision_with_none_amount(self):
        """Decision with None amount should not crash."""
        d = Decision(
            action="approve", bonus_amount=None, matched_rule_name="test",
        )
        assert d.bonus_amount is None

    def test_decision_with_zero_amount(self):
        d = Decision(
            action="approve", bonus_amount=Decimal("0"),
            matched_rule_name="direct_approve",
        )
        assert d.bonus_amount == Decimal("0")

    def test_reject_decision_no_message(self):
        d = Decision(action="reject", matched_rule_name="test")
        assert d.reject_message is None


# ══════════════════════════════════════════════════════════════════
# 5. Bonus Type Normalization Edge Cases
# ══════════════════════════════════════════════════════════════════


class TestBonusNormalization:
    """Edge cases for _normalize_bonus_type."""

    normalize = staticmethod(BonusListPage._normalize_bonus_type)

    def test_multiple_percent_patterns(self):
        """Multiple %N patterns should all be stripped."""
        result = self.normalize("İLK KAYBINIZA ÖZEL %100 NAKİT İADE BONUSU")
        assert result == "ilk_kaybiniza_ozel_nakit_iade_bonusu"

    def test_leading_percent(self):
        assert self.normalize("%15 KRİPTO YATIRIM BONUSU") == "kripto_yatirim_bonusu"

    def test_no_percent(self):
        assert self.normalize("ÇEVRİMSİZ 2X YAP 5X ÇEK") == "cevrimsiz_2x_yap_5x_cek"

    def test_extra_whitespace(self):
        assert self.normalize("  %25  ANLIK  KAYIP  BONUSU  ") == "anlik_kayip_bonusu"

    def test_empty_string(self):
        assert self.normalize("") == ""

    def test_only_percent(self):
        assert self.normalize("%100") == ""

    def test_turkish_chars(self):
        """All Turkish special chars should be normalized."""
        result = self.normalize("ÇĞİÖŞÜ çğıöşü")
        assert result == "cgiosu_cgiosu"


# ══════════════════════════════════════════════════════════════════
# 6. UserProfile Computed Fields Edge Cases
# ══════════════════════════════════════════════════════════════════


class TestUserProfileEdgeCases:
    """Edge cases for UserProfile computed fields."""

    def test_no_deposit_history(self):
        """Profile with empty deposit history."""
        profile = UserProfile(user_id="test", durum="Aktif")
        assert profile.basarili_yatirim_var is False
        assert profile.son_24_saat_yatirim_var is False
        assert profile.son_5_saat_yatirim_var is False
        assert profile.kripto_yatirim_var is False
        assert profile.son_kripto_yatirim_tutari == Decimal("0")
        assert profile.son_7_gun_yatirim_toplami == Decimal("0")
        assert profile.son_7_gun_net_kayip == Decimal("0")
        assert profile.hosgeldin_onay_sayisi == 0

    def test_none_dates_computed_fields(self):
        """Profile with None dates should return large defaults."""
        profile = UserProfile(user_id="test", durum="Aktif")
        assert profile.kayit_gunu_farki == 9999
        assert profile.son_yatirim_gunu_farki == 9999
        assert profile.son_yatirim_saat_farki == 99999

    def test_aktif_bonus_var_edge_cases(self):
        """Various aktif_bonus values."""
        assert UserProfile(user_id="t", aktif_bonus="").aktif_bonus_var is False
        assert UserProfile(user_id="t", aktif_bonus="-").aktif_bonus_var is False
        assert UserProfile(user_id="t", aktif_bonus=" ").aktif_bonus_var is False
        assert UserProfile(user_id="t", aktif_bonus="Bonus X").aktif_bonus_var is True

    def test_hesap_aktif_case_insensitive(self):
        assert UserProfile(user_id="t", durum="Aktif").hesap_aktif is True
        assert UserProfile(user_id="t", durum="aktif").hesap_aktif is True
        assert UserProfile(user_id="t", durum="AKTİF").hesap_aktif is True  # Turkish İ normalized
        assert UserProfile(user_id="t", durum="active").hesap_aktif is True
        assert UserProfile(user_id="t", durum="Pasif").hesap_aktif is False

    def test_net_kayip_calculation(self):
        """Net loss = deposits - withdrawals (positive = user lost money)."""
        now = datetime.now()
        profile = UserProfile(
            user_id="test",
            durum="Aktif",
            deposits=DepositHistory(entries=[
                DepositEntry(
                    amount=Decimal("1000"), is_successful=True,
                    date=now - timedelta(days=2),
                ),
            ]),
            withdrawals=WithdrawalHistory(entries=[
                WithdrawalEntry(
                    amount=Decimal("300"), is_successful=True,
                    date=now - timedelta(days=1),
                ),
            ]),
        )
        assert profile.son_7_gun_net_kayip == Decimal("700")

    def test_net_kayip_negative_means_profit(self):
        """Negative net loss means user made profit."""
        now = datetime.now()
        profile = UserProfile(
            user_id="test",
            durum="Aktif",
            deposits=DepositHistory(entries=[
                DepositEntry(
                    amount=Decimal("100"), is_successful=True,
                    date=now - timedelta(days=1),
                ),
            ]),
            withdrawals=WithdrawalHistory(entries=[
                WithdrawalEntry(
                    amount=Decimal("500"), is_successful=True,
                    date=now - timedelta(days=1),
                ),
            ]),
        )
        assert profile.son_7_gun_net_kayip == Decimal("-400")
