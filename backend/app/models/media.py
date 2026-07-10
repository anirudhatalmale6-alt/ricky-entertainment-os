"""Media and documents.

- ShowImage: gallery / profile photos that belong to a SHOW (max 5 per show).
- ArtistDocument: legal & fiscal documents that belong to the PROFILE (INE,
  constancia SAT, comprobante bancario, contrato...). These are the person's/
  provider's documents, shared across all their shows.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ShowImage(Base, TimestampMixin):
    __tablename__ = "show_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    is_profile: Mapped[bool] = mapped_column(Boolean, default=False)  # foto de perfil vs galeria
    caption: Mapped[str | None] = mapped_column(String(255))

    show: Mapped["Show"] = relationship(back_populates="images")  # noqa: F821


class ArtistDocument(Base, TimestampMixin):
    __tablename__ = "artist_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    # doc_type: identificacion, comprobante_domicilio, constancia_sat, contrato,
    # rider_tecnico, rider_hospitalidad, press_kit, comprobante_bancario, otro
    doc_type: Mapped[str] = mapped_column(String(60))
    url: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str | None] = mapped_column(String(255))

    artist: Mapped["Artist"] = relationship(back_populates="documents")  # noqa: F821
