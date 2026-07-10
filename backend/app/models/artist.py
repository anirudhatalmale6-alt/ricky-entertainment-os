"""Artist model - the product of the marketplace."""
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
    # An artist may (optionally) have a login account.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)

    # --- Step 1: who they are ------------------------------------------
    stage_name: Mapped[str] = mapped_column(String(255), index=True)   # Nombre artistico
    first_name: Mapped[str | None] = mapped_column(String(120))        # Nombre(s)
    last_name: Mapped[str | None] = mapped_column(String(120))         # Apellidos
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    artist_type: Mapped[str | None] = mapped_column(String(80))        # Solista / agrupacion
    category: Mapped[str] = mapped_column(String(80), index=True)      # main category
    genres: Mapped[list] = mapped_column(JSON, default=list)           # Categorias (varias): Jazz, Lounge...
    bio: Mapped[str | None] = mapped_column(Text)                      # Biografia corta
    years_experience: Mapped[str | None] = mapped_column(String(40))  # "10+ anos"
    languages_spoken: Mapped[list] = mapped_column(JSON, default=list)
    show_languages: Mapped[list] = mapped_column(JSON, default=list)  # Idiomas del espectaculo

    # Contact
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255))

    # --- Step 2: the show + technical rider ----------------------------
    show_name: Mapped[str | None] = mapped_column(String(255))        # Nombre del espectaculo
    show_description: Mapped[str | None] = mapped_column(Text)
    members: Mapped[int] = mapped_column(Integer, default=1)          # Integrantes
    duration_minutes: Mapped[int | None] = mapped_column(Integer)     # Duracion del show
    setup_minutes: Mapped[int | None] = mapped_column(Integer)        # Tiempo de montaje
    teardown_minutes: Mapped[int | None] = mapped_column(Integer)     # Tiempo de desmontaje
    space_required: Mapped[str | None] = mapped_column(String(120))   # Espacio requerido (3x3)
    power_required: Mapped[str | None] = mapped_column(String(120))   # Consumo electrico
    equipment_included: Mapped[list] = mapped_column(JSON, default=list)  # lo que el artista trae
    equipment_required: Mapped[str | None] = mapped_column(Text)          # lo que necesita del venue
    dressing_room: Mapped[str | None] = mapped_column(String(255))    # Camerino requerido
    requirements: Mapped[str | None] = mapped_column(Text)            # requerimientos generales

    # Media
    video_url: Mapped[str | None] = mapped_column(String(500))       # YouTube / Vimeo
    audio_url: Mapped[str | None] = mapped_column(String(500))       # Spotify / Apple / SoundCloud
    social_links: Mapped[dict] = mapped_column(JSON, default=dict)   # {instagram, facebook, youtube, tiktok}

    # --- Step 3: availability ------------------------------------------
    base_city: Mapped[str | None] = mapped_column(String(120))       # Ciudad base
    work_radius_km: Mapped[int | None] = mapped_column(Integer)      # Radio de trabajo
    states_worked: Mapped[list] = mapped_column(JSON, default=list)  # Estados donde trabaja
    available_to_travel: Mapped[bool] = mapped_column(Boolean, default=False)
    own_vehicle: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_passport: Mapped[bool] = mapped_column(Boolean, default=False)
    usa_visa: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Pricing (MXN) - base fields; full pricing overhaul pending -----
    base_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    special_event_surcharge_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    payout_speed: Mapped[PayoutSpeed] = mapped_column(
        SQLEnum(PayoutSpeed, values_callable=lambda e: [m.value for m in e]),
        default=PayoutSpeed.MENSUAL,
    )

    # --- Marketplace flags ---------------------------------------------
    offers_audition: Mapped[bool] = mapped_column(Boolean, default=False)       # ofrece audicion
    allow_subcontracting: Mapped[bool] = mapped_column(Boolean, default=False)  # deja que Partners lo contacten
    # Artist who upgraded to provider - branded "Partner" so they feel part of it.
    is_partner: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Step 4: fiscal + banking (Mexico) -----------------------------
    rfc: Mapped[str | None] = mapped_column(String(20))
    cfdi_use: Mapped[str | None] = mapped_column(String(20))         # Uso CFDI (G03...)
    tax_regime: Mapped[str | None] = mapped_column(String(120))      # Regimen fiscal
    legal_name: Mapped[str | None] = mapped_column(String(255))     # Razon social
    fiscal_postal_code: Mapped[str | None] = mapped_column(String(10))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_account: Mapped[str | None] = mapped_column(String(40))
    bank_account_holder: Mapped[str | None] = mapped_column(String(255))
    bank_clabe: Mapped[str | None] = mapped_column(String(20))
    preferred_currency: Mapped[str] = mapped_column(String(8), default="MXN")

    # Location
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))          # Estado
    country: Mapped[str] = mapped_column(String(80), default="Mexico")
    postal_code: Mapped[str | None] = mapped_column(String(10))

    # Status / verification
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rating: Mapped[float | None] = mapped_column(Numeric(3, 2))  # 0.00 - 5.00

    user: Mapped["User | None"] = relationship(back_populates="artist_profile")  # noqa: F821
    seasonal_rates: Mapped[list["ArtistSeasonalRate"]] = relationship(  # noqa: F821
        back_populates="artist", cascade="all, delete-orphan"
    )
    images: Mapped[list["ArtistImage"]] = relationship(  # noqa: F821
        back_populates="artist", cascade="all, delete-orphan"
    )
    documents: Mapped[list["ArtistDocument"]] = relationship(  # noqa: F821
        back_populates="artist", cascade="all, delete-orphan"
    )
