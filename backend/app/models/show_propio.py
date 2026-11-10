"""Shows propios de un hotel (David, 10/11).

Un hotel que trae a SHOWMA a un proveedor con el que ya trabajaba no paga fee
por él. Pero la exención NO va en el proveedor: muchos tienen varios shows y el
hotel sólo le contrataba uno, y eximir al proveedor regalaría todos los demás.
Así que va en el par HOTEL + SHOW:

  - el hotel invita a un SHOW concreto (InvitacionShow);
  - al registrar ese show, o al asignar uno que el proveedor ya tenía, queda un
    ShowPropio para ese hotel: automático y permanente (decisiones de David);
  - cualquier otro show del proveedor, o ese mismo show con otro hotel, paga fee
    normal. Un show nuevo no hereda nada.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ShowPropio(Base, TimestampMixin):
    __tablename__ = "shows_propios"
    __table_args__ = (UniqueConstraint("company_id", "show_id", name="ux_show_propio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"), index=True)
    artist_id: Mapped[int | None] = mapped_column(ForeignKey("artists.id", ondelete="SET NULL"))
    # invitacion (registró el show desde la invitación) | asignado (ya existía y
    # lo eligió) | previo (proveedor invitado antes de esto; lo marcó el hotel)
    origen: Mapped[str] = mapped_column(String(16), default="invitacion")
    invitacion_id: Mapped[int | None] = mapped_column(Integer)
    creado_por_user_id: Mapped[int | None] = mapped_column(Integer)


class InvitacionShow(Base, TimestampMixin):
    __tablename__ = "invitaciones_show"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Va en la liga: aleatorio, para que nadie pruebe números y se adjudique
    # shows propios de otro hotel.
    token: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    show_nombre: Mapped[str] = mapped_column(String(160))
    contacto: Mapped[str | None] = mapped_column(String(160))
    creado_por_user_id: Mapped[int | None] = mapped_column(Integer)
    # Se llena al usarse. Una invitación sirve para UN show.
    usada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    show_id: Mapped[int | None] = mapped_column(Integer)
    artist_id: Mapped[int | None] = mapped_column(Integer)
