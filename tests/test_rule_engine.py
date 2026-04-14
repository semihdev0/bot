"""Unit tests for the rule engine with Betronix-specific models."""

from datetime import datetime, timedelta
from decimal import Decimal

from src.config.models import (
    BonusCalculation,
    BonusRulesConfig,
    BonusTypeConfig,
    Condition,
    Rule,
)
from src.engine.models import BonusRequest, UserProfile
from src.engine.rule_engine import evaluate


def _make_profile(**kwargs) -> UserProfile:
    defaults = {
        "user_id": "testuser",
        "username": "Test User",
        "bakiye": Decimal("50"),
        "bonus_bakiye": Decimal("0"),
        "son_yatirim_tutari": Decimal("200"),
        "toplam_yatirim": Decimal("500"),
        "toplam_cekim": Decimal("100"),
        "kar_zarar": Decimal("-100"),
        "yatirim_sayisi": 5,
        "cekim_sayisi": 1,
        "durum": "Aktif",
        "kayit_tarihi": datetime.now() - timedelta(days=3),
        "son_yatirim_tarihi": datetime.now() - timedelta(days=1),
        "son_kullanilan_bonus": "",
        "aktif_bonus": "",
    }
    defaults.update(kwargs)
    return UserProfile(**defaults)


def _make_request(**kwargs) -> BonusRequest:
    defaults = {
        "request_id": "BR001",
        "user_id": "testuser",
        "bonus_type": "kripto_yatirim_bonusu",
    }
    defaults.update(kwargs)
    return BonusRequest(**defaults)


def _make_rules_config() -> BonusRulesConfig:
    return BonusRulesConfig(
        bonus_types={
            "kripto_yatirim_bonusu": BonusTypeConfig(
                display_name="%15 Kripto Yatırım",
                default_action="reject",
                default_reject_message_key="genel_uygun_degil",
                rules=[
                    Rule(
                        name="Kripto yatırım aktif kullanıcı",
                        conditions=[
                            Condition(field="hesap_aktif", operator="==", value=True),
                            Condition(field="son_yatirim_tutari", operator=">=", value=100),
                            Condition(field="aktif_bonus_var", operator="==", value=False),
                        ],
                        action="approve",
                        bonus_calculation=BonusCalculation(
                            method="percentage",
                            base_field="son_yatirim_tutari",
                            percentage=Decimal("15"),
                            min_amount=Decimal("15"),
                            max_amount=Decimal("1000"),
                        ),
                    ),
                    Rule(
                        name="Aktif bonus var",
                        conditions=[
                            Condition(field="aktif_bonus_var", operator="==", value=True),
                        ],
                        action="reject",
                        reject_message_key="aktif_bonus_mevcut",
                    ),
                ],
            ),
            "hosgeldin_bonusu": BonusTypeConfig(
                display_name="Hoşgeldin",
                default_action="reject",
                default_reject_message_key="genel_uygun_degil",
                rules=[
                    Rule(
                        name="Yeni kullanıcı yeterli yatırım",
                        conditions=[
                            Condition(field="kayit_gunu_farki", operator="<=", value=7),
                            Condition(field="son_yatirim_tutari", operator=">=", value=100),
                            Condition(field="bakiye", operator=">", value=0),
                            Condition(field="aktif_bonus_var", operator="==", value=False),
                        ],
                        action="approve",
                        bonus_calculation=BonusCalculation(
                            method="percentage",
                            base_field="son_yatirim_tutari",
                            percentage=Decimal("100"),
                            min_amount=Decimal("10"),
                            max_amount=Decimal("500"),
                        ),
                    ),
                ],
            ),
        }
    )


MESSAGES = {
    "genel_uygun_degil": "Uygun değil.",
    "aktif_bonus_mevcut": "Aktif bonus mevcut.",
}


def test_approve_kripto_bonus():
    """Active user with sufficient deposit and no active bonus -> approve."""
    profile = _make_profile(
        son_yatirim_tutari=Decimal("200"),
        durum="Aktif",
        aktif_bonus="",
    )
    request = _make_request()
    rules = _make_rules_config()

    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "approve"
    assert decision.bonus_amount == Decimal("30")  # 200 * 15%
    assert decision.matched_rule_name == "Kripto yatırım aktif kullanıcı"


def test_reject_aktif_bonus():
    """User with active bonus should be rejected."""
    profile = _make_profile(aktif_bonus="%25 ANLIK KAYIP BONUSU")
    request = _make_request()
    rules = _make_rules_config()

    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.reject_message == "Aktif bonus mevcut."


def test_approve_hosgeldin_bonus():
    """New user with sufficient deposit -> approve welcome bonus."""
    profile = _make_profile(
        son_yatirim_tutari=Decimal("300"),
        bakiye=Decimal("100"),
        kayit_tarihi=datetime.now() - timedelta(days=2),
        aktif_bonus="",
    )
    request = _make_request(bonus_type="hosgeldin_bonusu")
    rules = _make_rules_config()

    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "approve"
    assert decision.bonus_amount == Decimal("300")  # 300 * 100%


def test_reject_old_account_hosgeldin():
    """Old account should be rejected for welcome bonus (falls to default)."""
    profile = _make_profile(
        kayit_tarihi=datetime.now() - timedelta(days=30),
        aktif_bonus="",
    )
    request = _make_request(bonus_type="hosgeldin_bonusu")
    rules = _make_rules_config()

    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.confidence == "default_action"


def test_unknown_bonus_type_rejected():
    """Unknown bonus type should be rejected."""
    profile = _make_profile()
    request = _make_request(bonus_type="nonexistent_bonus")
    rules = _make_rules_config()

    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"


def test_approve_bonus_amount_capped():
    """Bonus amount should be capped at max_amount (1000 for kripto)."""
    profile = _make_profile(
        son_yatirim_tutari=Decimal("10000"),
        durum="Aktif",
        aktif_bonus="",
    )
    request = _make_request()
    rules = _make_rules_config()

    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "approve"
    assert decision.bonus_amount == Decimal("1000")  # capped at max


def test_computed_fields():
    """Test that computed profile fields work correctly."""
    profile = _make_profile(
        durum="Aktif",
        aktif_bonus="%25 ANLIK KAYIP BONUSU",
        kayit_tarihi=datetime.now() - timedelta(days=5),
        son_yatirim_tarihi=datetime.now() - timedelta(days=2),
    )
    assert profile.hesap_aktif is True
    assert profile.aktif_bonus_var is True
    assert profile.kayit_gunu_farki == 5
    assert profile.son_yatirim_gunu_farki == 2


def test_inactive_account():
    """Inactive account computed field."""
    profile = _make_profile(durum="Pasif")
    assert profile.hesap_aktif is False
