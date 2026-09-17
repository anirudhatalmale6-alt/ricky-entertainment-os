"""CFDI emitido — la factura electrónica timbrada de una actuación.

Cuando una actuación se marca como realizada, SHOWMA timbra un CFDI 4.0 a nombre
del músico (con su RFC/CSD) vía Facturama. Aquí guardamos la referencia al
comprobante: su Id en Facturama y el folio fiscal (UUID) del SAT, además de los
importes para poder mostrarlos en la pantalla de Facturación sin volver a llamar
a Facturama. El PDF/XML se descargan bajo demanda usando `facturama_id`.

Un timbrado que falle también se registra (status="error" + motivo) para que el
administrador vea qué actuaciones quedaron sin facturar y por qué.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Cfdi(Base, TimestampMixin):
    __tablename__ = "cfdis"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Un CFDI de periodo cubre VARIAS actuaciones; el enlace vive en
    # Booking.cfdi_id. `booking_id` sólo lo usan los CFDI de una sola actuación
    # (los que se emitían antes de la facturación por quincena).
    booking_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), index=True
    )
    # Quincena facturada: "2026-08-Q1". None en los CFDI de una sola actuación.
    period: Mapped[str | None] = mapped_column(String(16), index=True)
    artist_id: Mapped[int | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"), index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL")
    )

    # none/stamped/cancelled/error
    status: Mapped[str] = mapped_column(String(20), default="stamped", index=True)
    facturama_id: Mapped[str | None] = mapped_column(String(64))   # Id interno de Facturama
    uuid: Mapped[str | None] = mapped_column(String(48), index=True)  # folio fiscal SAT
    serie: Mapped[str | None] = mapped_column(String(25))
    folio: Mapped[str | None] = mapped_column(String(40))

    issuer_rfc: Mapped[str | None] = mapped_column(String(20))     # RFC del músico
    receiver_rfc: Mapped[str | None] = mapped_column(String(20))   # RFC del hotel

    subtotal: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total: Mapped[float | None] = mapped_column(Numeric(12, 2))

    stamped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    # De dónde salió esta factura (David, 2026-09-18):
    #   showma  = la timbramos nosotros por el proveedor
    #   propia  = la subió el proveedor (la emitió él o su contador)
    #   tercero = la subió por cuenta de un tercero que factura por él
    # Las que ya existen son todas "showma": es lo único que había.
    origen: Mapped[str] = mapped_column(String(12), default="showma")
    # Sólo para las SUBIDAS: el PDF y el XML tal como llegaron. Las que timbramos
    # nosotros no los guardan, se bajan de Facturama con facturama_id.
    pdf_url: Mapped[str | None] = mapped_column(String(500))
    xml_url: Mapped[str | None] = mapped_column(String(500))
    uploaded_by: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)               # motivo si falló

    booking: Mapped["Booking | None"] = relationship()   # noqa: F821
    artist: Mapped["Artist | None"] = relationship()     # noqa: F821
