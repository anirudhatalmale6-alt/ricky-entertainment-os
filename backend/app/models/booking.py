"""Actuacion (booking) model - a SHOW booked at a VENUE on a date/time.

This is where the whole marketplace comes together: a hotel (contratante) books
a show (the product) at one of its venues for a specific fecha/hora. Each
actuacion feeds:

  * the calendar dashboard (per venue, per property and per chain),
  * the attendance analytics (headcount at start and end -> ocupacion /
    retencion / abandono, so programming stops being decided "por popularidad"),
  * and the consolidated group dashboard (gasto y numero de actuaciones).

FKs to show / venue / company / artist use SET NULL so a finished actuacion
stays in the history even if a show or venue is later removed. company_id and
artist_id are denormalised from venue/show so a booking can always be scoped to
a property (and its chain) and to an artist calendar without extra joins.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import BookingStatus


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)

    # What is playing, where, and for whom.
    show_id: Mapped[int | None] = mapped_column(
        ForeignKey("shows.id", ondelete="SET NULL"), index=True
    )
    venue_id: Mapped[int | None] = mapped_column(
        ForeignKey("venues.id", ondelete="SET NULL"), index=True
    )
    # Denormalised for scoping / dashboards (survive show & venue deletion).
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    artist_id: Mapped[int | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"), index=True
    )
    # Who created it on the company side.
    booker_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookers.id", ondelete="SET NULL")
    )

    # When it happens.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[BookingStatus] = mapped_column(
        SQLEnum(BookingStatus, values_callable=lambda e: [m.value for m in e]),
        default=BookingStatus.PENDING,
        index=True,
    )

    # Which price tier applied (hotel / corporate / wedding / private /
    # restaurant / festival) and the amount agreed - snapshotted at booking time.
    event_type: Mapped[str | None] = mapped_column(String(40))
    agreed_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    # Platform commission % charged to the company, snapshotted from its risk
    # tier at the moment of booking (so later re-tiering does not rewrite money).
    commission_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))

    # Attendance - registered on the night, drives the analytics.
    headcount_start: Mapped[int | None] = mapped_column(Integer)  # aforo al iniciar
    headcount_end: Mapped[int | None] = mapped_column(Integer)    # aforo al terminar

    # Life-cycle timestamps.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(255))

    notes: Mapped[str | None] = mapped_column(Text)

    show: Mapped["Show | None"] = relationship()      # noqa: F821
    venue: Mapped["Venue | None"] = relationship()    # noqa: F821
    company: Mapped["Company | None"] = relationship()  # noqa: F821
    artist: Mapped["Artist | None"] = relationship()  # noqa: F821
    booker: Mapped["Booker | None"] = relationship()  # noqa: F821
