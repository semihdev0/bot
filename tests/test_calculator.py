"""Unit tests for bonus amount calculation."""

from decimal import Decimal

from src.config.models import BonusCalculation, TierEntry
from src.engine.calculator import calculate_bonus
from src.engine.models import UserProfile


def _make_profile(**kwargs) -> UserProfile:
    defaults = {
        "user_id": "U001",
        "son_yatirim_tutari": Decimal("200"),
        "bakiye": Decimal("50"),
    }
    defaults.update(kwargs)
    return UserProfile(**defaults)


def test_percentage_calculation():
    profile = _make_profile(son_yatirim_tutari=Decimal("200"))
    calc = BonusCalculation(
        method="percentage",
        base_field="son_yatirim_tutari",
        percentage=Decimal("50"),
    )
    result = calculate_bonus(profile, calc)
    assert result == Decimal("100")


def test_percentage_with_min():
    profile = _make_profile(son_yatirim_tutari=Decimal("10"))
    calc = BonusCalculation(
        method="percentage",
        base_field="son_yatirim_tutari",
        percentage=Decimal("50"),
        min_amount=Decimal("20"),
    )
    result = calculate_bonus(profile, calc)
    assert result == Decimal("20")  # clamped to min


def test_percentage_with_max():
    profile = _make_profile(son_yatirim_tutari=Decimal("1000"))
    calc = BonusCalculation(
        method="percentage",
        base_field="son_yatirim_tutari",
        percentage=Decimal("100"),
        max_amount=Decimal("500"),
    )
    result = calculate_bonus(profile, calc)
    assert result == Decimal("500")  # clamped to max


def test_fixed_calculation():
    profile = _make_profile()
    calc = BonusCalculation(method="fixed", fixed_amount=Decimal("75"))
    result = calculate_bonus(profile, calc)
    assert result == Decimal("75")


def test_tiered_calculation():
    profile = _make_profile(son_yatirim_tutari=Decimal("250"))
    calc = BonusCalculation(
        method="tiered",
        base_field="son_yatirim_tutari",
        tiers=[
            TierEntry(min=Decimal("0"), max=Decimal("99"), bonus=Decimal("10")),
            TierEntry(min=Decimal("100"), max=Decimal("299"), bonus=Decimal("50")),
            TierEntry(min=Decimal("300"), max=Decimal("999"), bonus=Decimal("100")),
        ],
    )
    result = calculate_bonus(profile, calc)
    assert result == Decimal("50")


def test_tiered_no_match():
    profile = _make_profile(son_yatirim_tutari=Decimal("5000"))
    calc = BonusCalculation(
        method="tiered",
        base_field="son_yatirim_tutari",
        tiers=[
            TierEntry(min=Decimal("0"), max=Decimal("100"), bonus=Decimal("10")),
        ],
    )
    result = calculate_bonus(profile, calc)
    assert result == Decimal("0")


def test_none_calculation():
    profile = _make_profile()
    result = calculate_bonus(profile, None)
    assert result == Decimal("0")
