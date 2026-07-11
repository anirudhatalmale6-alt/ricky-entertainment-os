"""Chat schemas: conversations + messages between hotel and artist."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SenderRole = Literal["artist", "company"]


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artist_id: int
    company_id: int
    request_id: int | None = None
    booking_id: int | None = None
    subject: str | None = None


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender_role: SenderRole
    body: str = Field(min_length=1)
    sender_user_id: int | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    sender_role: str
    sender_user_id: int | None = None
    body: str
    read_at: datetime | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    artist_id: int | None = None
    company_id: int | None = None
    request_id: int | None = None
    booking_id: int | None = None
    subject: str | None = None
    created_at: datetime
    # filled by the endpoint
    artist_name: str | None = None
    company_name: str | None = None
    message_count: int = 0
    last_message: str | None = None
    last_message_at: datetime | None = None
    unread_for_artist: int = 0   # mensajes de la empresa sin leer
    unread_for_company: int = 0  # mensajes del artista sin leer
