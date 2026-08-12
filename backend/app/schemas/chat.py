"""Chat schemas: conversations + messages between hotel and artist."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SenderRole = Literal["artist", "company"]


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artist_id: int
    company_id: int
    request_id: int | None = None
    booking_id: int | None = None
    subject: str | None = None


MAX_CHAT_IMAGES = 5


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender_role: SenderRole
    # Puede ir vacío si el mensaje son sólo fotos (lo valida el model_validator).
    body: str = ""
    images: list[str] = Field(default=[], max_length=MAX_CHAT_IMAGES)
    sender_user_id: int | None = None

    @model_validator(mode="after")
    def _needs_content(self):
        self.body = (self.body or "").strip()
        if not self.body and not self.images:
            raise ValueError("El mensaje no puede ir vacío: escribe algo o adjunta una foto.")
        return self


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    sender_role: str
    sender_user_id: int | None = None
    body: str
    images: list[str] = []
    read_at: datetime | None = None

    @field_validator("images", mode="before")
    @classmethod
    def _none_is_empty(cls, v):
        # Los mensajes anteriores a esta función tienen la columna en NULL.
        return v or []
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
