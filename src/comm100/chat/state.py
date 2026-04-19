"""Chat state tracker to avoid duplicate responses."""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from src.comm100.api.models import Comm100Message

logger = structlog.get_logger()

STATE_FILE = Path("comm100_chat_state.json")
MAX_ENTRIES = 50_000


class ChatStateTracker:
    """Tracks processed chats and messages to avoid duplicates."""

    def __init__(self) -> None:
        self._responded_message_ids: set[str] = set()
        self._active_chat_ids: set[str] = set()
        self._load_state()

    def has_responded(self, message_id: str) -> bool:
        return message_id in self._responded_message_ids

    def mark_responded(self, message_id: str) -> None:
        self._responded_message_ids.add(message_id)
        self._save_state()

    def add_active_chat(self, chat_id: str) -> None:
        self._active_chat_ids.add(chat_id)

    def remove_active_chat(self, chat_id: str) -> None:
        self._active_chat_ids.discard(chat_id)

    def is_active_chat(self, chat_id: str) -> bool:
        return chat_id in self._active_chat_ids

    def get_unresponded_visitor_messages(
        self, messages: list[Comm100Message]
    ) -> list[Comm100Message]:
        return [
            msg
            for msg in messages
            if msg.sender_type == "visitor"
            and msg.content
            and msg.content.strip()
            and not self.has_responded(msg.id)
        ]

    def _save_state(self) -> None:
        try:
            self._prune_if_needed()
            data = {
                "responded_message_ids": list(self._responded_message_ids),
                "active_chat_ids": list(self._active_chat_ids),
            }
            STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("state_save_failed", error=str(e))

    def _load_state(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            self._responded_message_ids = set(data.get("responded_message_ids", []))
            self._active_chat_ids = set(data.get("active_chat_ids", []))
            logger.info(
                "state_loaded",
                responded=len(self._responded_message_ids),
                active=len(self._active_chat_ids),
            )
        except Exception as e:
            logger.error("state_load_failed", error=str(e))
            self._responded_message_ids = set()
            self._active_chat_ids = set()

    def _prune_if_needed(self) -> None:
        if len(self._responded_message_ids) > MAX_ENTRIES:
            excess = len(self._responded_message_ids) - MAX_ENTRIES
            ids_list = list(self._responded_message_ids)
            self._responded_message_ids = set(ids_list[excess:])
            logger.info("state_pruned", removed=excess)
