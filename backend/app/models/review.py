"""Reseña de un hotel sobre una actuación que realmente contrató.

David quería "comentarios y puntuación como Amazon o Uber" (2026-08-14). La
diferencia con Amazon es deliberada y es lo único que hace que esto valga: aquí
no puede opinar cualquiera. Una reseña nace SIEMPRE de una actuación concreta,
ya ocurrida, y sólo la puede escribir el hotel que la contrató. Una por
actuación (booking_id es único).

Si dejáramos comentar libremente, en tres meses la calificación no valdría nada
y el hotel volvería a fiarse de una recomendación de WhatsApp. Atado a la
actuación, en cambio, es la única calificación del mercado que no se puede
inventar — ni para bien ni para mal.

Por eso booking_id NO es nullable y no tiene ondelete SET NULL: una reseña sin
su actuación detrás sería exactamente lo que estamos evitando.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("booking_id", name="uq_review_booking"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    # Denormalizados desde la actuación para poder listar y promediar sin joins.
    artist_id: Mapped[int | None] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), index=True
    )
    show_id: Mapped[int | None] = mapped_column(ForeignKey("shows.id", ondelete="SET NULL"))
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )

    rating: Mapped[int] = mapped_column(Integer)          # 1 a 5
    comment: Mapped[str | None] = mapped_column(Text)
    # Quién firma, del lado del hotel: "Gerente de Entretenimiento", etc.
    author_name: Mapped[str | None] = mapped_column(String(160))
    author_position: Mapped[str | None] = mapped_column(String(120))
