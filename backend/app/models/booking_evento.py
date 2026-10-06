"""La bitácora de una orden de actuación: qué le pasó, cuándo y quién lo hizo.

David, 06/10: "¿dónde podríamos integrar un historial de la actuación, para ver
hora de llegada, cambios…? ¿Suena muy loco/complejo?". No lo es, y la mitad ya
existía: la orden ya guarda cuándo se creó, cuándo se avisó al proveedor, cuándo
aceptó, cuándo llegó, cuándo se calificó y cuándo se canceló. Lo que no había
era un sitio donde se vieran juntas, ni nada que apuntara los CAMBIOS.

Esta tabla es SÓLO PARA AÑADIR. No se edita y no se borra: una bitácora que se
puede corregir no sirve para lo único que sirve una bitácora, que es poder
decirle a un hotel o a un proveedor "esto pasó, a esta hora, y lo hizo esta
persona". Por eso tampoco tiene updated_at.

Un apunte deliberado: se guarda el NOMBRE del actor además de su id. El id es la
referencia buena, pero las cuentas se dan de baja y cambian de nombre, y dentro
de dos años "lo cambió el usuario 47" no le explica nada a nadie.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BookingEvento(Base):
    __tablename__ = "booking_eventos"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    # Qué pasó. Códigos estables (ver services/historial.TIPOS): la pantalla
    # pinta el icono y el color a partir de esto, no del texto.
    tipo: Mapped[str] = mapped_column(String(32), index=True)
    # La frase que se lee en la línea de tiempo, ya redactada.
    texto: Mapped[str] = mapped_column(String(300))
    # El detalle largo cuando lo hay: el motivo de una cancelación, la nota de
    # una incidencia, el "de 20:00 a 21:30" de un cambio de horario.
    detalle: Mapped[str | None] = mapped_column(Text)

    actor_id: Mapped[int | None] = mapped_column(Integer)
    actor_nombre: Mapped[str | None] = mapped_column(String(160))
    # hotel | proveedor | seguridad | showma | sistema
    actor_rol: Mapped[str | None] = mapped_column(String(20))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
