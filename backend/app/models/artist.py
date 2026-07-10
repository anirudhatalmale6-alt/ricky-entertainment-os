"""Artist model - the product of the marketplace."""
from __future__ import annotations

from sqlalchemy import Boolean, Enum as SQLEnum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import PayoutSpeed


class Artist(Base, TimestampMixin):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    # An artist may (optionally) have a login account.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)

    stage_name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)  # musica en vivo, dj, show, etc.
    bio: Mapped[str | None] = mapped_column(Text)

    # Act details captured in the profile "alta"
    members: Mapped[int] = mapped_column(Integer, default=1)          # Integrantes
    duration_minutes: Mapped[int | None] = mapped_column(Integer)     # Duracion del show
    requirements: Mapped[str | None] = mapped_column(Text)            # Requerimientos (escenario, sonido, etc.)

    # Pricing (MXN)
    base_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    # % extra applied for special events (weddings, etc.)
    special_event_surcharge_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)

    # How the artist wants to get paid (drives their commission).
    payout_speed: Mapped[PayoutSpeed] = mapped_column(
        SQLEnum(PayoutSpeed, values_callable=lambda e: [m.value for m in e]),
        default=PayoutSpeed.MENSUAL,
    )

    # Marketplace flags
    offers_audition: Mapped[bool] = mapped_column(Boolean, default=False)       # ofrece audicion
    allow_subcontracting: Mapped[bool] = mapped_column(Boolean, default=False)  # deja que Partners lo contacten
    # Artist who upgraded to provider - branded "Partner" so they feel part of it.
    is_partner: Mapped[bool] = mapped_column(Boolean, default=False)

    # Location
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80), default="Mexico")

    # Status / verification
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    rating: Mapped[float | None] = mapped_column(Numeric(3, 2))  # 0.00 - 5.00

    user: Mapped["User | None"] = relationship(back_populates="artist_profile")  # noqa: F821
    seasonal_rates: Mapped[list["ArtistSeasonalRate"]] = relationship(  # noqa: F821
        back_populates="artist", cascade="all, delete-orphan"
    )
