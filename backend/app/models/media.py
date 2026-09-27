"""Media and documents.

- ShowImage: gallery / profile photos that belong to a SHOW (max 5 per show).
- ArtistDocument: legal & fiscal documents that belong to the PROFILE (INE,
  constancia SAT, comprobante bancario, contrato...). These are the person's/
  provider's documents, shared across all their shows.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String
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

    # --- Expediente para cadenas hoteleras (David, 26/09) ---------------------
    # Las dos fechas las DECLARA el proveedor; SHOWMA no abre el documento ni lo
    # coteja con el SAT. Por eso se llaman "declarado": el día que se lea el QR
    # del PDF habrá una fecha leída al lado y se verá cuál es cuál.
    #
    # Son dos y no una porque no todos los documentos caducan igual. La póliza
    # trae impreso hasta cuándo vale; un recibo de luz no vence nunca, lo que
    # pasa es que a los 3 meses ya no lo aceptan. Preguntarle a alguien "¿cuándo
    # vence tu recibo de luz?" no tiene respuesta.
    vence_el: Mapped[date | None] = mapped_column(Date)      # lo dice el documento
    emitido_el: Mapped[date | None] = mapped_column(Date)    # para los de antigüedad
    # "Declaro que este documento es auténtico y está vigente." Es lo que hace
    # que el descargo del contrato se sostenga: no es sólo que SHOWMA no
    # responda, es que hay alguien que sí respondió y quedó registrado.
    declarado: Mapped[bool] = mapped_column(Boolean, default=False)
    # Los "si aplica" del checklist que el proveedor marca como que no le tocan.
    no_aplica: Mapped[bool] = mapped_column(Boolean, default=False)
    nota: Mapped[str | None] = mapped_column(String(255))    # aseguradora, nº de póliza…

    artist: Mapped["Artist"] = relationship(back_populates="documents")  # noqa: F821
