"""Monthly entertainment budget per property ("perfil de presupuesto").

Each property boss loads, month by month, the budget they set aside for
entertainment plus the occupancy they ran that month. Together with the
property profile (rooms + average daily rate) this lets Market Intelligence
work out how much of the room revenue actually goes into entertainment, and
benchmark that against the rest of the market.

One row per (company, year, month).
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class PropertyBudget(Base, TimestampMixin):
    __tablename__ = "property_budgets"
    __table_args__ = (
        UniqueConstraint("company_id", "year", "month", name="uq_budget_company_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )

    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer)  # 1-12

    # Gasto mensual destinado a entretenimiento.
    entertainment_budget: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    # % de ocupacion del mes (0-100) - drives the room-revenue estimate.
    occupancy_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    notes: Mapped[str | None] = mapped_column(Text)

    company: Mapped["Company"] = relationship(back_populates="budgets")  # noqa: F821
