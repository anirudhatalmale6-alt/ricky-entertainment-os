"""Venue model - a physical space inside a company where shows happen.

A hotel usually has several venues (Lobby Bar, Pool Bar, Beach Club, Teatro...),
each with its own capacity. Shows are scheduled at a venue, and attendance is
registered there (headcount at start and end) to compute occupancy / retention /
abandonment analytics - so decisions stop being made "por popularidad" by feel.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Venue(Base, TimestampMixin):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(120))            # Lobby Bar, Pool Bar...
    capacity: Mapped[int | None] = mapped_column(Integer)     # capacidad de personas
    ambiance_type: Mapped[str | None] = mapped_column(String(80))  # interior/exterior, lounge, escenario...
    usual_schedule: Mapped[str | None] = mapped_column(String(120))  # horario habitual
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Qué se espera del entretenimiento EN ESTA SALA: AMBIENTE, SOCIAL o
    # ESTELAR. Es el ejemplo con el que David lo pidió (2026-09-07): en el mismo
    # hotel de lujo, el lobby quiere un pianista de ambiente y el salón de shows
    # quiere energía. Un desplegable rellena de golpe las cuatro respuestas del
    # bloque de experiencia, para no pedirle cinco preguntas por sala a quien
    # tiene quince. Lo medido: el mood mueve la nota del mismo show hasta 56
    # puntos entre una sala y otra.
    mood: Mapped[str | None] = mapped_column(String(16))
    # Retoques a mano sobre lo que trae el mood, para la sala rara. Lo que esté
    # aquí manda sobre el mood. Ver app/services/afinidad.py.
    afinidad: Mapped[dict | None] = mapped_column(JSON)

    # Location so the artist can navigate with Waze / Google Maps.
    address: Mapped[str | None] = mapped_column(String(255))  # exact address of this venue
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    map_url: Mapped[str | None] = mapped_column(String(500))  # optional pasted maps link

    company: Mapped["Company"] = relationship(back_populates="venues")  # noqa: F821
