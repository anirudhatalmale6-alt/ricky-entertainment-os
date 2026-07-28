"""SupportMessage - un mensaje de AYUDA que un usuario manda a MASTER.

Cualquier usuario autenticado (artista u hotel) puede pedir ayuda o reportar
una corrección desde el botón "Ayuda". El administrador los ve y atiende en el
panel MASTER (Ayuda / Soporte). David MASTER REVISION 3, 2026-07-28.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SupportMessage(Base, TimestampMixin):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    from_name: Mapped[str | None] = mapped_column(String(255))
    from_email: Mapped[str | None] = mapped_column(String(255))
    from_role: Mapped[str | None] = mapped_column(String(40))   # artist / hotel / admin
    subject: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    # open -> resolved
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
