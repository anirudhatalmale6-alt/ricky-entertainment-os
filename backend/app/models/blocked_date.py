"""Artist availability blocks.

An artist can mark individual days as unavailable (vacaciones, enfermedad,
compromisos personales) so hotels don't request them for those dates. This is a
simple per-day flag on the artist's own calendar; it does NOT touch bookings.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ArtistBlockedDate(Base, TimestampMixin):
    __tablename__ = "artist_blocked_dates"
    # One block per artist per day (re-blocking just updates the reason).
    __table_args__ = (
        UniqueConstraint("artist_id", "blocked_on", name="uq_artist_blocked_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), index=True
    )
    blocked_on: Mapped[date] = mapped_column(Date, index=True)
    reason: Mapped[str | None] = mapped_column(String(120))

    artist: Mapped["Artist"] = relationship()  # noqa: F821
