"""Seasonal / period pricing for an artist.

Lets an artist charge a different price during a named period (e.g. "Navidad",
"Semana Santa"). When a booking falls inside a period, its price overrides the
artist's base_price.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ArtistSeasonalRate(Base, TimestampMixin):
    __tablename__ = "artist_seasonal_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)

    label: Mapped[str] = mapped_column(String(120))   # e.g. "Navidad"
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Numeric(12, 2))  # MXN price during this period

    artist: Mapped["Artist"] = relationship(back_populates="seasonal_rates")  # noqa: F821
