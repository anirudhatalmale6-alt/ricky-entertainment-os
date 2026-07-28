"""Ayuda / Soporte: mensajes que cualquier usuario manda a MASTER.

POST  /support        -> un usuario autenticado pide ayuda o reporta algo.
GET   /support        -> el administrador (MASTER) lista los mensajes.
PATCH /support/{id}   -> el administrador marca resuelto / abierto.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentScope, CurrentUser, DbSession
from app.models.support import SupportMessage

router = APIRouter(prefix="/support", tags=["support"])


class SupportIn(BaseModel):
    subject: str | None = Field(default=None, max_length=255)
    body: str = Field(min_length=3, max_length=4000)


class SupportStatusIn(BaseModel):
    status: str = Field(pattern="^(open|resolved)$")


def _role_label(scope) -> str:
    if scope.is_admin:
        return "admin"
    if scope.artist_id is not None:
        return "artist"
    return "hotel"


def _out(m: SupportMessage) -> dict:
    return {
        "id": m.id,
        "from_name": m.from_name,
        "from_email": m.from_email,
        "from_role": m.from_role,
        "subject": m.subject,
        "body": m.body,
        "status": m.status,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_support(payload: SupportIn, user: CurrentUser, scope: CurrentScope, db: DbSession):
    """Manda un mensaje de ayuda/corrección a MASTER."""
    msg = SupportMessage(
        user_id=user.id,
        from_name=user.full_name,
        from_email=user.email,
        from_role=_role_label(scope),
        subject=(payload.subject or None),
        body=payload.body.strip(),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return _out(msg)


@router.get("")
async def list_support(scope: CurrentScope, db: DbSession, status_filter: str | None = None):
    """Lista de mensajes de ayuda (solo MASTER)."""
    if not scope.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo MASTER puede ver los mensajes de ayuda.")
    q = select(SupportMessage).order_by(SupportMessage.created_at.desc())
    if status_filter in ("open", "resolved"):
        q = q.where(SupportMessage.status == status_filter)
    rows = (await db.execute(q)).scalars().all()
    return {"total": len(rows), "items": [_out(m) for m in rows]}


@router.patch("/{msg_id}")
async def update_support(msg_id: int, payload: SupportStatusIn, scope: CurrentScope, db: DbSession):
    if not scope.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo MASTER puede atender los mensajes.")
    msg = await db.get(SupportMessage, msg_id)
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado.")
    msg.status = payload.status
    await db.commit()
    await db.refresh(msg)
    return _out(msg)
