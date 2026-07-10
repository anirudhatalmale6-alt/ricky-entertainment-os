"""Seasonal / period pricing for a SHOW.

Each show runs its own annual calendar "like hotel rooms or flights": the artist
defines their OWN periods (Navidad, Halloween, San Valentin, 4 de Julio...) with a
free date range and a percentage adjustment over the show's base price. Periods
and percentages are fully open - Navidad can be +300% while low season is -10%.

Effective price when a booking date falls inside a period:
    base_price * (1 + adjustment_pct/100)
An optional absolute `price` override wins over the percentage when set.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ShowSeasonalRate(Base, TimestampMixin):
    __tablename__ = "show_seasonal_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"), index=True)

    label: Mapped[str] = mapped_column(String(120))   # free text: "Navidad", "Halloween"...
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    # % over base price. Positive raises (Navidad +300), negative lowers (baja -10).
    adjustment_pct: Mapped[float] = mapped_column(Numeric(7, 2), default=0)
    # Optional absolute price override - if set, wins over adjustment_pct.
    price: Mapped[float | None] = mapped_column(Numeric(12, 2))

    show: Mapped["Show"] = relationship(back_populates="seasonal_rates")  # noqa: F821
