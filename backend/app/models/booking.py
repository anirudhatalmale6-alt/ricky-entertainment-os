"""Actuacion (booking) model - a SHOW booked at a VENUE on a date/time.

This is where the whole marketplace comes together: a hotel (contratante) books
a show (the product) at one of its venues for a specific fecha/hora. Each
actuacion feeds:

  * the calendar dashboard (per venue, per property and per chain),
  * the attendance analytics (headcount at start and end -> ocupacion /
    retencion / abandono, so programming stops being decided "por popularidad"),
  * and the consolidated group dashboard (gasto y numero de actuaciones).

FKs to show / venue / company / artist use SET NULL so a finished actuacion
stays in the history even if a show or venue is later removed. company_id and
artist_id are denormalised from venue/show so a booking can always be scoped to
a property (and its chain) and to an artist calendar without extra joins.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import BookingStatus


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Folio de la ORDEN DE ACTUACIÓN: OA-2026-00147 (David, 06/10). Es el número
    # con el que el hotel y su contador siguen esta actuación hasta la factura
    # global que la cubre. Se asigna al crearla y NO se vuelve a tocar: ni al
    # reprogramarla, ni al cambiarle el precio. Ver services/folios.
    folio: Mapped[str | None] = mapped_column(String(24), unique=True, index=True)
    # CFDI que ya cubre esta actuación. Es el candado contra facturar (y pagar)
    # dos veces lo mismo: el cierre de quincena sólo toma las que lo tienen NULL.
    cfdi_id: Mapped[int | None] = mapped_column(Integer, index=True)

    # What is playing, where, and for whom.
    show_id: Mapped[int | None] = mapped_column(
        ForeignKey("shows.id", ondelete="SET NULL"), index=True
    )
    venue_id: Mapped[int | None] = mapped_column(
        ForeignKey("venues.id", ondelete="SET NULL"), index=True
    )
    # Denormalised for scoping / dashboards (survive show & venue deletion).
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    artist_id: Mapped[int | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"), index=True
    )
    # Who created it on the company side.
    booker_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookers.id", ondelete="SET NULL")
    )

    # When it happens.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[BookingStatus] = mapped_column(
        SQLEnum(BookingStatus, values_callable=lambda e: [m.value for m in e]),
        default=BookingStatus.PENDING,
        index=True,
    )

    # Which price tier applied (hotel / corporate / wedding / private /
    # restaurant / festival) and the amount agreed - snapshotted at booking time.
    event_type: Mapped[str | None] = mapped_column(String(40))
    agreed_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    # Platform commission % charged to the company, snapshotted from its risk
    # tier at the moment of booking (so later re-tiering does not rewrite money).
    commission_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))

    # Attendance - registered on the night, drives the analytics.
    headcount_start: Mapped[int | None] = mapped_column(Integer)  # aforo al iniciar
    headcount_end: Mapped[int | None] = mapped_column(Integer)    # aforo al terminar

    # Life-cycle timestamps.
    # notified_at: when the hotel finished arranging the week and pressed
    # "Guardar y notificar". Until then the booking is a DRAFT the hotel is still
    # moving around on the Calendario Maestro — invisible to the artist and not
    # auto-confirmed. NULL = draft (borrador), not yet sent to the artist.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(255))
    cancelled_by: Mapped[str | None] = mapped_column(String(16))  # artist | hotel | admin

    notes: Mapped[str | None] = mapped_column(Text)

    # --- Contaduría reconciliation (Master console) --------------------
    # invoice_paid: la factura emitida al cliente fue cobrada (ingreso).
    # payout_paid:  el recibo/pago al talento fue liquidado (egreso).
    invoice_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    payout_paid: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Actuación no completada (David, 06/10) ------------------------
    # El hotel la marca desde la misma ventana de calificar. No es una
    # cancelación: la actuación estaba confirmada y llegó el día. Por eso tiene
    # sus propios campos y no reusa cancellation_reason, que responde a otra
    # pregunta y saldría mezclado en los reportes.
    #
    # Al marcarla, el estado pasa a NO_SHOW y con eso SALE de la facturación:
    # el cierre de quincena sólo toma las que están en COMPLETED.
    incidencia_motivo: Mapped[str | None] = mapped_column(String(32))
    incidencia_nota: Mapped[str | None] = mapped_column(Text)
    incidencia_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incidencia_por: Mapped[int | None] = mapped_column(Integer)

    # --- Pase de acceso (David, 06/10) ---------------------------------
    # Token del QR que lleva a la página pública del pase. NO es el folio: el
    # folio es correlativo y quien tenga uno adivinaría los demás sumando uno.
    pase_token: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)
    # Token para que el proveedor acepte o rechace DESDE EL CORREO, sin entrar.
    # Es otro distinto del pase a proposito: el pase lo ve el personal de
    # seguridad al escanear, y poder abrir una puerta no puede ser lo mismo que
    # poder comprometer una fecha y un importe (David, 08/10).
    respuesta_token: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)
    # Cuándo confirmó seguridad que el grupo llegó, y quién lo dijo. El nombre lo
    # teclea el de la caseta: no tiene cuenta en SHOWMA, y pedirle una para
    # apuntar que alguien llegó es la forma más rápida de que no lo apunte nadie.
    llegada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    llegada_por: Mapped[str | None] = mapped_column(String(120))

    show: Mapped["Show | None"] = relationship()      # noqa: F821
    venue: Mapped["Venue | None"] = relationship()    # noqa: F821
    company: Mapped["Company | None"] = relationship()  # noqa: F821
    artist: Mapped["Artist | None"] = relationship()  # noqa: F821
    booker: Mapped["Booker | None"] = relationship()  # noqa: F821
