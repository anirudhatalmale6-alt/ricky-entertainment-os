"""Artist media and documents.

Gallery images / press kit / legal & fiscal documents an artist uploads
during registration (steps 2 and 4 of the sign-up flow).
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ArtistImage(Base, TimestampMixin):
    __tablename__ = "artist_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    is_profile: Mapped[bool] = mapped_column(Boolean, default=False)  # foto de perfil vs galeria
    caption: Mapped[str | None] = mapped_column(String(255))

    artist: Mapped["Artist"] = relationship(back_populates="images")  # noqa: F821


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
