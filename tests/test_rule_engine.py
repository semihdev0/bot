"""Unit tests for the rule engine."""

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
        "user_id": "U001",
        "username": "testuser",
        "bakiye": Decimal("50"),
        "son_yatirim_tutari": Decimal("200"),
        "toplam_yatirim": Decimal("500"),
        "toplam_cekim": Decimal("100"),
        "kayit_tarihi": datetime.now() - timedelta(days=3),
    }
    defaults.update(kwargs)
    return UserProfile(**defaults)


def _make_request(**kwargs) -> BonusRequest:
    defaults = {
        "request_id": "BR001",
        "user_id": "U001",
        "bonus_type": "hosgeldin_bonusu",
    }
    defaults.update(kwargs)
    return BonusRequest(**defaults)


def _make_rules_config() -> BonusRulesConfig:
    return BonusRulesConfig(
        bonus_types={
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
                    Rule(
                        name="Yatırım yetersiz",
                        conditions=[
                            Condition(field="son_yatirim_tutari", operator="<", value=100),
                        ],
                        action="reject",
                        reject_message_key="yatirim_yetersiz",
                    ),
                ],
            ),
        }
    )


MESSAGES = {
    "genel_uygun_degil": "Uygun değil.",
    "yatirim_yetersiz": "Yatırım yetersiz.",
}


def test_approve_new_user_with_deposit():
    """New user with sufficient deposit should be approved."""
    profile = _make_profile(
        son_yatirim_tutari=Decimal("200"),
        bakiye=Decimal("50"),
        kayit_tarihi=datetime.now() - timedelta(days=3),
    )
    request = _make_request()
    rules = _make_rules_config()

    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "approve"
    assert decision.bonus_amount == Decimal("200")
    assert decision.matched_rule_name == "Yeni kullanıcı yeterli yatırım"


def test_reject_small_deposit():
    """User with small deposit should be rejected."""
    profile = _make_profile(son_yatirim_tutari=Decimal("50"))
    request = _make_request()
    rules = _make_rules_config()

    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "reject"
    assert decision.reject_message == "Yatırım yetersiz."
    assert decision.matched_rule_name == "Yatırım yetersiz"


def test_reject_old_account_default():
    """Old account with sufficient deposit but doesn't match first rule
    and doesn't match second rule either -> falls to default."""
    profile = _make_profile(
        son_yatirim_tutari=Decimal("200"),
        bakiye=Decimal("50"),
        kayit_tarihi=datetime.now() - timedelta(days=30),
    )
    request = _make_request()
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
    """Bonus amount should be capped at max_amount."""
    profile = _make_profile(
        son_yatirim_tutari=Decimal("1000"),
        bakiye=Decimal("50"),
        kayit_tarihi=datetime.now() - timedelta(days=1),
    )
    request = _make_request()
    rules = _make_rules_config()

    decision = evaluate(profile, request, rules, MESSAGES)

    assert decision.action == "approve"
    assert decision.bonus_amount == Decimal("500")  # capped at max
