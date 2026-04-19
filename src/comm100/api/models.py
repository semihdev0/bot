"""Pydantic models for Comm100 API request/response types."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Comm100Visitor(BaseModel):
    id: str
    name: str = ""
    email: str = ""
    custom_fields: dict[str, str] = Field(default_factory=dict)


class Comm100Message(BaseModel):
    id: str
    chat_id: str
    sender_type: Literal["visitor", "agent", "system"]
    sender_id: str = ""
    content: str = ""
    timestamp: datetime


class Comm100Chat(BaseModel):
    id: str
    visitor_id: str = ""
    visitor_name: str = ""
    status: str = ""
    department: str = ""
    messages: list[Comm100Message] = Field(default_factory=list)
    created_at: datetime | None = None
