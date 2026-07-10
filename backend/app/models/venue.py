"""Venue model - a physical space inside a company where shows happen.

A hotel usually has several venues (Lobby Bar, Pool Bar, Beach Club, Teatro...),
each with its own capacity. Shows are scheduled at a venue, and attendance is
registered there (headcount at start and end) to compute occupancy / retention /
abandonment analytics - so decisions stop being made "por popularidad" by feel.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Venue(Base, TimestampMixin):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(120))            # Lobby Bar, Pool Bar...
    capacity: Mapped[int | None] = mapped_column(Integer)     # capacidad de personas
    ambiance_type: Mapped[str | None] = mapped_column(String(80))  # interior/exterior, lounge, escenario...
    usual_schedule: Mapped[str | None] = mapped_column(String(120))  # horario habitual
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Location so the artist can navigate with Waze / Google Maps.
    address: Mapped[str | None] = mapped_column(String(255))  # exact address of this venue
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    map_url: Mapped[str | None] = mapped_column(String(500))  # optional pasted maps link

    company: Mapped["Company"] = relationship(back_populates="venues")  # noqa: F821
