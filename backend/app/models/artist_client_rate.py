"""ArtistClientRate — tarifa especial de un artista para un cliente concreto.

Un músico puede fijar un precio especial (o un % de descuento) para un hotel
(company) o para una cadena entera (group), sin tocar su precio público. Cuando
ese cliente lo contrata, se aplica la tarifa especial. Así puede dar un descuento
por volumen/temporada a una cadena sin cambiar su show para todos los demás.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ArtistClientRate(Base, TimestampMixin):
    __tablename__ = "artist_client_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), index=True
    )
    # El destino es un hotel (company_id) O una cadena (group_id). Uno de los dos.
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("property_groups.id", ondelete="CASCADE"), index=True
    )
    # La tarifa es un precio fijo O un porcentaje de descuento sobre el precio público.
    special_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    discount_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
