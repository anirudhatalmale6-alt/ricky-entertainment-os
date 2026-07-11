"""In-app chat between a contratante (hotel) and an artist.

"Un chat como estamos haciendo nosotros" - a direct thread so the two sides can
talk. A conversation is between one artist and one company and can be anchored to
a specific solicitud (request) or actuacion (booking) for context, or be a plain
direct chat. Messages carry which side sent them and a read timestamp so the UI
can show unread badges.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"), index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    # Optional context - the chat can hang off a request or a booking.
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_requests.id", ondelete="SET NULL"), index=True
    )
    booking_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), index=True
    )
    subject: Mapped[str | None] = mapped_column(String(200))

    artist: Mapped["Artist | None"] = relationship()  # noqa: F821
    company: Mapped["Company | None"] = relationship()  # noqa: F821
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    # Which side wrote it: "artist" or "company".
    sender_role: Mapped[str] = mapped_column(String(20), index=True)
    # The actual user, once artist/contratante logins are wired (nullable in dev).
    sender_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
