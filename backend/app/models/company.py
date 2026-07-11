"""Company model - hotels, restaurants and venues that book entertainment.

A company (contratante) is created once with its fiscal + contact data and a
payment-behaviour risk tier. It owns a catalogue of VENUES (Lobby Bar, Pool Bar,
Beach Club, Teatro...), each with a capacity - the shows happen at a venue and
attendance is measured there.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Enum as SQLEnum, ForeignKey, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import RiskTier


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)         # Nombre comercial
    company_type: Mapped[str] = mapped_column(String(40), default="hotel")  # hotel, restaurant, salon, bar, cadena
    logo_url: Mapped[str | None] = mapped_column(String(500))
    # Optional parent chain/group - NULL for an independent property.
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("property_groups.id", ondelete="SET NULL"), index=True
    )

    # Fiscal (Mexico)
    tax_id: Mapped[str | None] = mapped_column(String(20))             # RFC
    legal_name: Mapped[str | None] = mapped_column(String(255))        # Razon social
    cfdi_use: Mapped[str | None] = mapped_column(String(20))
    tax_regime: Mapped[str | None] = mapped_column(String(120))

    # Contact
    contact_person: Mapped[str | None] = mapped_column(String(255))    # responsable de entretenimiento
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp: Mapped[str | None] = mapped_column(String(40))
    website: Mapped[str | None] = mapped_column(String(255))
    social_links: Mapped[dict] = mapped_column(JSON, default=dict)

    # Location
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80), default="Mexico")
    postal_code: Mapped[str | None] = mapped_column(String(10))

    # Property profile - feeds Market Intelligence benchmarking.
    # Room revenue proxy = rooms * avg_daily_rate * occupancy% (occupancy comes
    # from the monthly budget row). star_rating drives the 5* / 4* comparatives.
    rooms: Mapped[int | None] = mapped_column(Integer)                 # numero de habitaciones
    avg_daily_rate: Mapped[float | None] = mapped_column(Numeric(12, 2))  # tarifa promedio (ADR)
    star_rating: Mapped[int | None] = mapped_column(Integer)           # categoria 1-5 estrellas
    # Whether this property pays for the premium Market Intelligence add-on.
    # The market comparative (benchmarking) is the "Partners" paid feature.
    is_partner: Mapped[bool] = mapped_column(Boolean, default=False)

    # Commercial conditions
    # Payment-behaviour risk tier -> drives the commission charged to the company.
    # Everybody starts at A; it can be renegotiated at sign-up or earned over time.
    risk_tier: Mapped[RiskTier] = mapped_column(
        SQLEnum(RiskTier, values_callable=lambda e: [m.value for m in e]),
        default=RiskTier.A,
    )
    # Payment terms agreed at sign-up (days). Used before the 3-month behaviour
    # window has enough history to auto-classify the tier.
    agreed_payment_days: Mapped[int | None] = mapped_column(Integer)

    group: Mapped["PropertyGroup | None"] = relationship(  # noqa: F821
        back_populates="properties"
    )
    bookers: Mapped[list["Booker"]] = relationship(  # noqa: F821
        back_populates="company"
    )
    venues: Mapped[list["Venue"]] = relationship(  # noqa: F821
        back_populates="company", cascade="all, delete-orphan"
    )
    budgets: Mapped[list["PropertyBudget"]] = relationship(  # noqa: F821
        back_populates="company", cascade="all, delete-orphan"
    )
