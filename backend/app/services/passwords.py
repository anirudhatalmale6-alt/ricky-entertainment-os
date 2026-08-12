"""Recuperación y cambio de contraseña.

Vive aparte de los endpoints porque lo usan dos caminos: el usuario que pide
"olvidé mi contraseña" desde el login, y MASTER cuando le restablece la clave a
alguien desde el panel de usuarios.
"""
from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.config import settings
from app.models.password_reset import PasswordResetToken
from app.models.user import User

# Sin caracteres que se confunden al dictarla por teléfono (O/0, l/1, I).
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def temp_password(length: int = 10) -> str:
    """Contraseña temporal legible que cumple las reglas del registro
    (8+, una mayúscula, un número, un carácter especial)."""
    body = "".join(secrets.choice(_ALPHABET) for _ in range(length - 3))
    return (
        secrets.choice(string.ascii_uppercase)
        + body
        + secrets.choice("23456789")
        + secrets.choice("!@#$%&*")
    )


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    if not domain:
        return "***"
    visible = name[:2] if len(name) > 3 else name[:1]
    return f"{visible}{'*' * max(3, len(name) - len(visible))}@{domain}"


async def issue_token(db, user: User, *, requested_by: str = "self") -> tuple[str, datetime]:
    """Crea un token nuevo e invalida los anteriores del mismo usuario.
    Devuelve (token en claro, caducidad). El claro no se guarda en ningún lado."""
    now = datetime.now(timezone.utc)
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw = secrets.token_urlsafe(32)
    expires = now + timedelta(minutes=settings.RESET_TOKEN_MINUTES)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=expires,
            requested_by=requested_by,
        )
    )
    await db.commit()
    return raw, expires


def reset_link(raw: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/?reset={raw}"


async def resolve_token(db, raw: str) -> tuple[PasswordResetToken | None, User | None, str | None]:
    """(token, usuario, motivo del rechazo). Motivo en español, para la pantalla."""
    row = (
        await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(raw or ""))
        )
    ).scalar_one_or_none()
    if row is None:
        return None, None, "El enlace no es válido."
    if row.used_at is not None:
        return row, None, "Este enlace ya se usó. Pide uno nuevo."
    expires = row.expires_at
    if expires.tzinfo is None:                       # SQLite devuelve naive
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return row, None, "El enlace caducó. Pide uno nuevo."
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        return row, None, "La cuenta ya no está activa."
    return row, user, None


async def apply_new_password(db, token: PasswordResetToken, user: User, password: str) -> None:
    user.hashed_password = security_hash(password)
    token.used_at = datetime.now(timezone.utc)
    # Cualquier otro enlace pendiente del mismo usuario queda inservible.
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.id != token.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(timezone.utc))
    )
    await db.commit()


def security_hash(password: str) -> str:
    from app.core import security

    return security.hash_password(password)


def check_strength(password: str) -> str | None:
    """Mismas reglas que muestra el registro. Devuelve el error o None."""
    pw = password or ""
    if len(pw) < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    if not any(c.isupper() for c in pw):
        return "La contraseña debe incluir al menos una letra mayúscula."
    if not any(c.isdigit() for c in pw):
        return "La contraseña debe incluir al menos un número."
    if all(c.isalnum() for c in pw):
        return "La contraseña debe incluir al menos un carácter especial."
    return None
