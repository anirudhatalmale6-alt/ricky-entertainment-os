"""ArtistNotification - an in-app aviso for an artist about a booking.

When the hotel finishes arranging the Calendario Maestro and hits
"Guardar y notificar", one of these is created per affected actuación. The
artist sees them in their bell inbox next time they log in. WhatsApp/email
delivery is a later channel (David 2026-07-18).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ArtistNotification(Base, TimestampMixin):
    __tablename__ = "artist_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), index=True
    )
    booking_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL")
    )
    # new_booking (nueva actuación pendiente) | confirmed (actuación confirmada)
    # | reschedule (cambio de fecha/horario)
    kind: Mapped[str] = mapped_column(String(20), default="new_booking", index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
