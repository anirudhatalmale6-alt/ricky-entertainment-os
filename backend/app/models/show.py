"""Show model - a single sellable product (act) offered by an artist/profile.

One profile (Artist) can offer MANY shows, each completely independent: its own
category, rider, media, prices and seasonal calendar. Example: "David
Producciones" can list 15 different shows under one profile. In the marketplace a
hotel searches and books a SHOW (the real product), so each show is its own card.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Show(Base, TimestampMixin):
    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), index=True
    )

    # What the show is
    show_name: Mapped[str] = mapped_column(String(255), index=True)   # Nombre del espectaculo
    category: Mapped[str] = mapped_column(String(80), index=True)     # Musica / Shows / Fotografia y Video / Produccion
    subcategory: Mapped[str | None] = mapped_column(String(80), index=True)  # Solista / DJ / Danza...
    genres: Mapped[list] = mapped_column(JSON, default=list)          # Jazz, Lounge...
    description: Mapped[str | None] = mapped_column(Text)
    show_languages: Mapped[list] = mapped_column(JSON, default=list)  # Idiomas del espectaculo

    # The technical rider
    members: Mapped[int] = mapped_column(Integer, default=1)          # Integrantes
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    setup_minutes: Mapped[int | None] = mapped_column(Integer)
    teardown_minutes: Mapped[int | None] = mapped_column(Integer)
    space_required: Mapped[str | None] = mapped_column(String(120))
    power_required: Mapped[str | None] = mapped_column(String(120))
    equipment_included: Mapped[list] = mapped_column(JSON, default=list)
    equipment_required: Mapped[str | None] = mapped_column(Text)
    dressing_room: Mapped[str | None] = mapped_column(String(255))
    requirements: Mapped[str | None] = mapped_column(Text)

    # Media
    video_url: Mapped[str | None] = mapped_column(String(500))
    audio_url: Mapped[str | None] = mapped_column(String(500))

    # Tarifas base - one price per event type (MXN, all optional)
    base_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_hotel: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_corporate: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_wedding: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_private: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_restaurant: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_festival: Mapped[float | None] = mapped_column(Numeric(12, 2))
    # Add-ons. NULL = "a acordar" for the optional ones.
    extra_hour_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    transport_from_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    lodging_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    meals_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    per_diem_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    special_event_surcharge_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)

    offers_audition: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rating: Mapped[float | None] = mapped_column(Numeric(3, 2))

    artist: Mapped["Artist"] = relationship(back_populates="shows")  # noqa: F821
    images: Mapped[list["ShowImage"]] = relationship(  # noqa: F821
        back_populates="show", cascade="all, delete-orphan"
    )
    seasonal_rates: Mapped[list["ShowSeasonalRate"]] = relationship(  # noqa: F821
        back_populates="show", cascade="all, delete-orphan"
    )
