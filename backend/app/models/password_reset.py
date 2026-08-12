"""Password reset tokens.

El enlace que recibe el usuario por correo lleva un token largo y aleatorio; en
la base sólo se guarda su SHA-256, igual que una contraseña. Así, aunque alguien
lea la tabla, no puede reconstruir ningún enlace válido. Cada token vale una vez
y caduca; al usarlo se invalidan todos los demás del mismo usuario.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class PasswordResetToken(Base, TimestampMixin):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # De dónde salió: "self" (lo pidió el usuario) o "admin" (se lo generó MASTER).
    requested_by: Mapped[str] = mapped_column(String(16), default="self")

    user: Mapped["User"] = relationship()  # noqa: F821
