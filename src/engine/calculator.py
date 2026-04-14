"""Bonus amount calculation methods."""

from __future__ import annotations

from decimal import Decimal

from src.config.models import BonusCalculation
from src.engine.models import UserProfile


def _clamp(value: Decimal, calc: BonusCalculation) -> Decimal:
    """Clamp a value between min and max amounts if configured."""
    if calc.min_amount is not None and value < calc.min_amount:
        value = calc.min_amount
    if calc.max_amount is not None and value > calc.max_amount:
        value = calc.max_amount
    return value


def _calc_percentage(profile: UserProfile, calc: BonusCalculation) -> Decimal:
    if calc.base_field is None or calc.percentage is None:
        raise ValueError("percentage method requires base_field and percentage")
    base_value = getattr(profile, calc.base_field, Decimal("0"))
    raw = Decimal(str(base_value)) * calc.percentage / Decimal("100")
    return _clamp(raw, calc)


def _calc_fixed(calc: BonusCalculation) -> Decimal:
    if calc.fixed_amount is None:
        raise ValueError("fixed method requires fixed_amount")
    return calc.fixed_amount


def _calc_tiered(profile: UserProfile, calc: BonusCalculation) -> Decimal:
    if calc.base_field is None or calc.tiers is None:
        raise ValueError("tiered method requires base_field and tiers")
    base_value = Decimal(str(getattr(profile, calc.base_field, Decimal("0"))))
    for tier in calc.tiers:
        if tier.min <= base_value <= tier.max:
            return tier.bonus
    return Decimal("0")


def calculate_bonus(
    profile: UserProfile, calc: BonusCalculation | None
) -> Decimal:
    """Calculate the bonus amount based on the configured method."""
    if calc is None:
        return Decimal("0")

    if calc.method == "percentage":
        return _calc_percentage(profile, calc)
    elif calc.method == "fixed":
        return _calc_fixed(calc)
    elif calc.method == "tiered":
        return _calc_tiered(profile, calc)
    else:
        raise ValueError(f"Unknown calculation method: {calc.method}")
