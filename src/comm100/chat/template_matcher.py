"""Keyword-based template matching for common questions."""

from __future__ import annotations

import structlog

from src.comm100.config.models import TemplatesConfig
from src.engine.models import _tr_lower

logger = structlog.get_logger()


class TemplateMatcher:
    """Matches visitor messages against keyword-based templates."""

    def __init__(self, templates: TemplatesConfig) -> None:
        self._templates = sorted(
            templates.templates.items(),
            key=lambda t: t[1].priority,
            reverse=True,
        )

    def match(self, message: str) -> str | None:
        if not message or not message.strip():
            return None

        normalized = _tr_lower(message)

        for name, template in self._templates:
            keywords_lower = [_tr_lower(kw) for kw in template.keywords]

            if template.match_mode == "any":
                matched = any(kw in normalized for kw in keywords_lower)
            else:
                matched = all(kw in normalized for kw in keywords_lower)

            if matched:
                logger.debug("template_matched", template=name, message=message[:50])
                return template.response

        return None
