"""Tests for Comm100 template matcher."""

from __future__ import annotations

import pytest

from src.comm100.chat.template_matcher import TemplateMatcher
from src.comm100.config.models import TemplateEntry, TemplatesConfig


def _make_templates(**kwargs: dict) -> TemplatesConfig:
    templates = {}
    for name, data in kwargs.items():
        templates[name] = TemplateEntry(**data)
    return TemplatesConfig(templates=templates)


@pytest.fixture
def matcher() -> TemplateMatcher:
    config = _make_templates(
        greeting={
            "keywords": ["merhaba", "selam"],
            "match_mode": "any",
            "response": "Hosgeldiniz!",
            "priority": 100,
        },
        bonus={
            "keywords": ["bonus", "promosyon"],
            "match_mode": "any",
            "response": "Bonus bilgisi.",
            "priority": 80,
        },
        specific={
            "keywords": ["kripto", "bonus"],
            "match_mode": "all",
            "response": "Kripto bonus bilgisi.",
            "priority": 90,
        },
    )
    return TemplateMatcher(config)


class TestTemplateMatcher:
    def test_any_mode_single_keyword(self, matcher: TemplateMatcher):
        result = matcher.match("merhaba nasilsiniz")
        assert result == "Hosgeldiniz!"

    def test_any_mode_second_keyword(self, matcher: TemplateMatcher):
        result = matcher.match("selam!")
        assert result == "Hosgeldiniz!"

    def test_no_match(self, matcher: TemplateMatcher):
        result = matcher.match("hava nasil bugun")
        assert result is None

    def test_empty_message(self, matcher: TemplateMatcher):
        assert matcher.match("") is None
        assert matcher.match("   ") is None
        assert matcher.match(None) is None  # type: ignore[arg-type]

    def test_priority_ordering(self, matcher: TemplateMatcher):
        result = matcher.match("merhaba bonus istiyorum")
        assert result == "Hosgeldiniz!"

    def test_all_mode_both_keywords(self, matcher: TemplateMatcher):
        result = matcher.match("kripto bonus nedir")
        assert result == "Kripto bonus bilgisi."

    def test_all_mode_partial_no_match(self, matcher: TemplateMatcher):
        result = matcher.match("kripto yatirim")
        assert result is None

    def test_case_insensitive(self, matcher: TemplateMatcher):
        result = matcher.match("MERHABA")
        assert result == "Hosgeldiniz!"

    def test_turkish_chars(self):
        config = _make_templates(
            turkish={
                "keywords": ["cekim"],
                "match_mode": "any",
                "response": "Cekim bilgisi.",
                "priority": 50,
            },
        )
        m = TemplateMatcher(config)
        assert m.match("cekim yapmak istiyorum") == "Cekim bilgisi."

    def test_empty_templates(self):
        m = TemplateMatcher(TemplatesConfig())
        assert m.match("merhaba") is None
