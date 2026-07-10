"""Company model - hotels, restaurants and venues that book entertainment."""
from __future__ import annotations

from sqlalchemy import Enum as SQLEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import RiskTier


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    company_type: Mapped[str] = mapped_column(String(40), default="hotel")  # hotel, restaurant, venue

    # Payment-behaviour risk tier -> drives the commission charged to the company.
    # Everybody starts at A; it can be renegotiated at sign-up or earned over time.
    risk_tier: Mapped[RiskTier] = mapped_column(
        SQLEnum(RiskTier, values_callable=lambda e: [m.value for m in e]),
        default=RiskTier.A,
    )
    # Payment terms agreed at sign-up (days). Used before the 3-month behaviour
    # window has enough history to auto-classify the tier.
    agreed_payment_days: Mapped[int | None] = mapped_column(Integer)

    # Fiscal (Mexico)
    tax_id: Mapped[str | None] = mapped_column(String(20))   # RFC
    legal_name: Mapped[str | None] = mapped_column(String(255))

    # Location
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80), default="Mexico")

    # Contact
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40))

    bookers: Mapped[list["Booker"]] = relationship(  # noqa: F821
        back_populates="company"
    )
