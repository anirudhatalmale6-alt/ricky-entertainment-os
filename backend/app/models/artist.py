"""Artist model - the PROFILE (person or provider) behind the shows.

A profile is created once and holds identity, contact, availability, payout
preference and fiscal/banking data. The sellable products (acts) live in the
`shows` catalogue: one profile -> many shows (see app.models.show.Show).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import PayoutSpeed


class Artist(Base, TimestampMixin):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    # A profile may (optionally) have a login account.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)

    # --- Who they are --------------------------------------------------
    stage_name: Mapped[str] = mapped_column(String(255), index=True)   # Nombre artistico / proveedor
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    artist_type: Mapped[str | None] = mapped_column(String(80))        # Solista / agrupacion / productora
    bio: Mapped[str | None] = mapped_column(Text)
    profile_image_url: Mapped[str | None] = mapped_column(String(500))   # avatar que ven los hoteles
    years_experience: Mapped[str | None] = mapped_column(String(40))
    languages_spoken: Mapped[list] = mapped_column(JSON, default=list)
    social_links: Mapped[dict] = mapped_column(JSON, default=dict)     # {instagram, facebook, youtube, tiktok}

    # Contact
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255))

    # --- Availability --------------------------------------------------
    base_city: Mapped[str | None] = mapped_column(String(120))
    work_radius_km: Mapped[int | None] = mapped_column(Integer)
    states_worked: Mapped[list] = mapped_column(JSON, default=list)
    available_to_travel: Mapped[bool] = mapped_column(Boolean, default=False)
    own_vehicle: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_passport: Mapped[bool] = mapped_column(Boolean, default=False)
    usa_visa: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Payout preference (plan de liquidacion) - see enums.PayoutSpeed
    payout_speed: Mapped[PayoutSpeed] = mapped_column(
        SQLEnum(PayoutSpeed, values_callable=lambda e: [m.value for m in e]),
        default=PayoutSpeed.MENSUAL,
    )

    # --- Marketplace flags (profile level) -----------------------------
    allow_subcontracting: Mapped[bool] = mapped_column(Boolean, default=False)  # deja que Partners lo contacten
    # Cómo se aprueban las actuaciones que le llegan: True = se confirman solas,
    # False = quedan "pendientes" hasta que el artista las acepta/rechaza.
    auto_confirm_bookings: Mapped[bool] = mapped_column(Boolean, default=False)
    # Artist who upgraded to provider - branded "Partner" so they feel part of it.
    # Partner is a paid subscription ($499/mes) that adds visibility + a
    # "Partner Verificado" badge and unlocks subcontracting between acts.
    is_partner: Mapped[bool] = mapped_column(Boolean, default=False)
    partner_monthly_fee: Mapped[float | None] = mapped_column(Numeric(10, 2))
    calendar_sync: Mapped[str | None] = mapped_column(String(20))       # google / outlook / none

    # Registration consents.
    accepted_terms: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_privacy: Mapped[bool] = mapped_column(Boolean, default=False)
    authorized_data_use: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Fiscal + banking (Mexico) -------------------------------------
    rfc: Mapped[str | None] = mapped_column(String(20))
    cfdi_use: Mapped[str | None] = mapped_column(String(20))
    tax_regime: Mapped[str | None] = mapped_column(String(120))
    legal_name: Mapped[str | None] = mapped_column(String(255))
    fiscal_postal_code: Mapped[str | None] = mapped_column(String(10))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_account: Mapped[str | None] = mapped_column(String(40))
    bank_account_holder: Mapped[str | None] = mapped_column(String(255))
    bank_clabe: Mapped[str | None] = mapped_column(String(20))
    preferred_currency: Mapped[str] = mapped_column(String(8), default="MXN")

    # Location
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80), default="Mexico")
    postal_code: Mapped[str | None] = mapped_column(String(10))

    # Status / verification
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rating: Mapped[float | None] = mapped_column(Numeric(3, 2))

    user: Mapped["User | None"] = relationship(back_populates="artist_profile")  # noqa: F821
    shows: Mapped[list["Show"]] = relationship(  # noqa: F821
        back_populates="artist", cascade="all, delete-orphan"
    )
    documents: Mapped[list["ArtistDocument"]] = relationship(  # noqa: F821
        back_populates="artist", cascade="all, delete-orphan"
    )
