"""Rule engine - evaluates declarative YAML rules against user profile data."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from src.config.models import BonusRulesConfig, Condition, Rule
from src.engine.calculator import calculate_bonus
from src.engine.models import BonusRequest, Decision, UserProfile

logger = structlog.get_logger()


def _get_field_value(profile: UserProfile, field: str) -> Any:
    """Extract a field value from the user profile by name."""
    if hasattr(profile, field):
        return getattr(profile, field)
    raise ValueError(f"Unknown profile field: {field}")


def _to_decimal(value: Any) -> Decimal:
    """Safely convert a value to Decimal for comparison.

    Returns Decimal("0") for unconvertible values, but logs a warning
    so silent data corruption is detectable.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal("1") if value else Decimal("0")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        logger.warning("decimal_conversion_failed", value=repr(value))
        return Decimal("0")


def _evaluate_condition(profile: UserProfile, condition: Condition) -> bool:
    """Evaluate a single condition against the user profile."""
    field_value = _get_field_value(profile, condition.field)
    op = condition.operator
    target = condition.value

    if op == "is_empty":
        return field_value is None or field_value == "" or field_value == 0
    if op == "is_not_empty":
        return field_value is not None and field_value != "" and field_value != 0

    if op in ("==", "!="):
        if op == "==":
            return field_value == target
        return field_value != target

    if op in (">", ">=", "<", "<="):
        fv = _to_decimal(field_value)
        tv = _to_decimal(target)
        if op == ">":
            return fv > tv
        if op == ">=":
            return fv >= tv
        if op == "<":
            return fv < tv
        return fv <= tv

    if op == "in":
        return field_value in target

    if op == "not_in":
        return field_value not in target

    if op == "contains":
        return str(target) in str(field_value)

    if op == "between":
        if not isinstance(target, (list, tuple)) or len(target) < 2:
            raise ValueError(
                f"'between' operator requires [low, high] list, got: {target}"
            )
        fv = _to_decimal(field_value)
        low = _to_decimal(target[0])
        high = _to_decimal(target[1])
        return low <= fv <= high

    raise ValueError(f"Unknown operator: {op}")


def _evaluate_rule(profile: UserProfile, rule: Rule) -> bool:
    """Evaluate all conditions of a rule (AND logic)."""
    return all(
        _evaluate_condition(profile, cond) for cond in rule.conditions
    )


def evaluate(
    profile: UserProfile,
    request: BonusRequest,
    rules_config: BonusRulesConfig,
    messages: dict[str, str],
) -> Decision:
    """Evaluate rules for a bonus request and return a decision.

    Rules are evaluated top-to-bottom. First matching rule wins.
    If no rule matches, the default_action is used.
    """
    bonus_type_key = request.bonus_type
    type_config = rules_config.bonus_types.get(bonus_type_key)

    if type_config is None:
        type_config = rules_config.bonus_types.get("_unknown")
        if type_config is None:
            return Decision(
                action="reject",
                reject_message="Bu bonus türü tanınmadı.",
                matched_rule_name="no_config",
                confidence="default_action",
            )

    for rule in type_config.rules:
        try:
            if _evaluate_rule(profile, rule):
                logger.info(
                    "rule_matched",
                    rule=rule.name,
                    user=profile.user_id,
                    bonus_type=bonus_type_key,
                    action=rule.action,
                )

                if rule.action == "approve":
                    amount = calculate_bonus(profile, rule.bonus_calculation)
                    turnover = (
                        rule.bonus_calculation.turnover
                        if rule.bonus_calculation is not None
                        else None
                    )
                    return Decision(
                        action="approve",
                        bonus_amount=amount,
                        bonus_turnover=turnover,
                        matched_rule_name=rule.name,
                    )
                else:
                    msg_key = rule.reject_message_key or type_config.default_reject_message_key
                    return Decision(
                        action="reject",
                        reject_message=messages.get(
                            msg_key, "Bonus talebiniz reddedilmiştir."
                        ),
                        matched_rule_name=rule.name,
                    )
        except Exception as e:
            logger.error(
                "rule_evaluation_error",
                rule=rule.name,
                error=str(e),
            )
            continue

    # No rule matched - use default action
    logger.info(
        "no_rule_matched",
        user=profile.user_id,
        bonus_type=bonus_type_key,
        default_action=type_config.default_action,
    )

    if type_config.default_action == "approve":
        return Decision(
            action="approve",
            bonus_amount=Decimal("0"),
            matched_rule_name="default",
            confidence="default_action",
        )

    msg_key = type_config.default_reject_message_key
    return Decision(
        action="reject",
        reject_message=messages.get(
            msg_key, "Bonus talebiniz reddedilmiştir."
        ),
        matched_rule_name="default",
        confidence="default_action",
    )
