"""Builds Claude system prompts and conversation context."""

from __future__ import annotations

from src.comm100.api.models import Comm100Message
from src.comm100.config.models import SystemPromptConfig


class PromptBuilder:
    """Builds Claude system prompts and converts Comm100 messages to Claude format."""

    def __init__(self, config: SystemPromptConfig) -> None:
        self._config = config

    def build_system_prompt(self, visitor_name: str = "") -> str:
        parts = []

        if self._config.persona.name:
            parts.append(
                f"Sen {self._config.persona.name} - {self._config.persona.role}."
            )

        if self._config.system_prompt:
            parts.append(self._config.system_prompt)

        if self._config.knowledge_base:
            parts.append(self._config.knowledge_base)

        if visitor_name:
            parts.append(
                f"Musterinin adi: {visitor_name}. Mumkunse ismiyle hitap et."
            )

        return "\n\n".join(parts)

    def build_messages(
        self,
        conversation: list[Comm100Message],
        max_messages: int = 10,
    ) -> list[dict[str, str]]:
        recent = conversation[-max_messages:]
        messages = []

        for msg in recent:
            if msg.sender_type == "system":
                continue
            role = "user" if msg.sender_type == "visitor" else "assistant"
            if msg.content and msg.content.strip():
                messages.append({"role": role, "content": msg.content})

        return messages
