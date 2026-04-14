"""Tests for config loading and validation."""

from src.config.models import (
    BonusCalculation,
    BonusRulesConfig,
    BonusTypeConfig,
    Condition,
    MessagesConfig,
    Rule,
    SelectorEntry,
    Settings,
)
from src.config.selectors import SelectorRegistry


def test_settings_defaults():
    """Settings should have sensible defaults."""
    settings = Settings(
        backoffice={"base_url": "https://example.com"}
    )
    assert settings.browser.headless is True
    assert settings.browser.slow_mo == 100
    assert settings.polling.interval_seconds == 60
    assert settings.session.relogin_interval_minutes == 60


def test_selector_entry_css():
    entry = SelectorEntry(strategy="css", value="input#name")
    assert entry.strategy == "css"
    assert entry.value == "input#name"


def test_selector_entry_text():
    entry = SelectorEntry(strategy="text", value="Giriş Yap")
    assert entry.strategy == "text"


def test_selector_registry_get():
    data = {
        "login_page": {
            "username_input": {"strategy": "css", "value": "#username"},
        }
    }
    registry = SelectorRegistry(data)
    entry = registry.get("login_page", "username_input")
    assert entry.value == "#username"


def test_selector_registry_get_nested():
    data = {
        "bonus_list_page": {
            "row_columns": {
                "user_id": {"strategy": "css", "value": "td:nth-child(2)"},
            }
        }
    }
    registry = SelectorRegistry(data)
    entry = registry.get_nested("bonus_list_page", "row_columns", "user_id")
    assert entry.value == "td:nth-child(2)"


def test_condition_model():
    cond = Condition(field="bakiye", operator=">=", value=100)
    assert cond.field == "bakiye"
    assert cond.operator == ">="


def test_bonus_rules_config():
    config = BonusRulesConfig(
        bonus_types={
            "test_bonus": BonusTypeConfig(
                display_name="Test",
                default_action="reject",
                rules=[
                    Rule(
                        name="Test rule",
                        conditions=[
                            Condition(field="bakiye", operator=">", value=0)
                        ],
                        action="approve",
                        bonus_calculation=BonusCalculation(
                            method="fixed", fixed_amount=50
                        ),
                    )
                ],
            )
        }
    )
    assert "test_bonus" in config.bonus_types
    assert len(config.bonus_types["test_bonus"].rules) == 1


def test_messages_config():
    config = MessagesConfig(
        rejection_messages={
            "test_key": "Test rejection message",
        }
    )
    assert config.rejection_messages["test_key"] == "Test rejection message"
