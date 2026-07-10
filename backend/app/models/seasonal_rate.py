"""Seasonal / period pricing for an artist.

The artist runs an annual calendar "like hotel rooms or flights": they define
their OWN periods (Navidad, Halloween, San Valentin, 4 de Julio, verano...) with
a free date range and a percentage adjustment over their base price. Periods and
percentages are fully open - Navidad can be +300% while a low season can be -10%.

When a booking date falls inside a period, the effective price is:
    base_price * (1 + adjustment_pct/100)
An optional absolute `price` override wins over the percentage when set.
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

    label: Mapped[str] = mapped_column(String(120))   # free text: "Navidad", "Halloween"...
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    # % over base price. Positive raises (Navidad +300), negative lowers (temporada baja -10).
    adjustment_pct: Mapped[float] = mapped_column(Numeric(7, 2), default=0)
    # Optional absolute price override - if set, wins over adjustment_pct.
    price: Mapped[float | None] = mapped_column(Numeric(12, 2))

    artist: Mapped["Artist"] = relationship(back_populates="seasonal_rates")  # noqa: F821
