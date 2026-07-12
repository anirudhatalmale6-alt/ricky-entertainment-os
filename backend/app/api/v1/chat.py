"""Chat endpoints: direct conversations between a hotel and an artist.

Writes are guarded with booking.manage and reads with report.view for now; once
the artist/contratante logins are wired, the sender identity and the "which side
am I" will come from the session instead of the payload/query.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentScope, DbSession, require_permission
from app.models.artist import Artist
from app.models.company import Company
from app.models.conversation import Conversation, Message
from app.schemas.chat import (
    ConversationCreate,
    ConversationOut,
    MessageCreate,
    MessageOut,
)

router = APIRouter(prefix="/conversations", tags=["chat"])


async def _get_conversation_or_404(db: DbSession, conversation_id: int) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


async def _decorate(db: DbSession, conv: Conversation) -> ConversationOut:
    out = ConversationOut.model_validate(conv)
    artist_name = None
    if conv.artist_id:
        a = await db.get(Artist, conv.artist_id)
        artist_name = a.stage_name if a else None
    company_name = None
    if conv.company_id:
        c = await db.get(Company, conv.company_id)
        company_name = c.name if c else None

    msgs = list(
        (await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
        )).scalars().all()
    )
    last = msgs[-1] if msgs else None
    return out.model_copy(update={
        "artist_name": artist_name,
        "company_name": company_name,
        "message_count": len(msgs),
        "last_message": last.body if last else None,
        "last_message_at": last.created_at if last else None,
        "unread_for_artist": sum(1 for m in msgs if m.sender_role == "company" and m.read_at is None),
        "unread_for_company": sum(1 for m in msgs if m.sender_role == "artist" and m.read_at is None),
    })


@router.post(
    "",
    response_model=ConversationOut,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def start_conversation(payload: ConversationCreate, db: DbSession):
    """Open a chat between an artist and a hotel - idempotent per
    (artist, company, request): re-opening returns the existing thread."""
    if await db.get(Artist, payload.artist_id) is None:
        raise HTTPException(status_code=404, detail="Artist not found")
    if await db.get(Company, payload.company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")

    existing = (
        await db.execute(
            select(Conversation).where(
                Conversation.artist_id == payload.artist_id,
                Conversation.company_id == payload.company_id,
                Conversation.request_id == payload.request_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return await _decorate(db, existing)

    conv = Conversation(**payload.model_dump())
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return await _decorate(db, conv)


@router.get(
    "",
    response_model=list[ConversationOut],
    dependencies=[Depends(require_permission("report.view"))],
)
async def list_conversations(
    db: DbSession,
    artist_id: int | None = None,
    company_id: int | None = None,
    request_id: int | None = None,
    booking_id: int | None = None,
):
    q = select(Conversation)
    if artist_id is not None:
        q = q.where(Conversation.artist_id == artist_id)
    if company_id is not None:
        q = q.where(Conversation.company_id == company_id)
    if request_id is not None:
        q = q.where(Conversation.request_id == request_id)
    if booking_id is not None:
        q = q.where(Conversation.booking_id == booking_id)
    convs = list((await db.execute(q.order_by(Conversation.created_at.desc()))).scalars().all())
    # freshest activity first
    out = [await _decorate(db, c) for c in convs]
    out.sort(key=lambda o: o.last_message_at or o.created_at, reverse=True)
    return out


@router.get("/mine", response_model=list[ConversationOut])
async def my_conversations(scope: CurrentScope, db: DbSession):
    """My chat inbox, resolved from who I am: an artist sees their own threads,
    a hotel manager their property's, a group director the whole chain."""
    q = select(Conversation)
    if scope.is_artist:
        q = q.where(Conversation.artist_id == scope.artist_id)
    elif scope.group_id is not None:
        sub = select(Company.id).where(Company.group_id == scope.group_id)
        q = q.where(Conversation.company_id.in_(sub))
    elif scope.company_id is not None:
        q = q.where(Conversation.company_id == scope.company_id)
    elif not scope.is_admin:
        return []  # authenticated but no linked profile -> nothing of "mine"
    convs = list((await db.execute(q.order_by(Conversation.created_at.desc()))).scalars().all())
    out = [await _decorate(db, c) for c in convs]
    out.sort(key=lambda o: o.last_message_at or o.created_at, reverse=True)
    return out


async def _assert_participant(db: DbSession, scope, conv: Conversation) -> None:
    """A conversation is private to its two sides: the artist and the hotel (a
    group director covers every hotel in the chain). Admin/finance can see all."""
    if scope.is_admin:
        return
    if scope.artist_id is not None and conv.artist_id == scope.artist_id:
        return
    if scope.company_id is not None and conv.company_id == scope.company_id:
        return
    if scope.group_id is not None and conv.company_id is not None:
        comp = await db.get(Company, conv.company_id)
        if comp and comp.group_id == scope.group_id:
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta conversacion")


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: int, scope: CurrentScope, db: DbSession):
    conv = await _get_conversation_or_404(db, conversation_id)
    await _assert_participant(db, scope, conv)
    return await _decorate(db, conv)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(conversation_id: int, scope: CurrentScope, db: DbSession):
    conv = await _get_conversation_or_404(db, conversation_id)
    await _assert_participant(db, scope, conv)
    rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
        )
    ).scalars().all()
    return list(rows)


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(conversation_id: int, payload: MessageCreate, scope: CurrentScope, db: DbSession):
    conv = await _get_conversation_or_404(db, conversation_id)
    await _assert_participant(db, scope, conv)
    msg = Message(conversation_id=conversation_id, **payload.model_dump())
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


@router.post("/{conversation_id}/read", response_model=ConversationOut)
async def mark_read(
    conversation_id: int,
    scope: CurrentScope,
    db: DbSession,
    role: str = Query(..., pattern="^(artist|company)$"),
):
    """Mark the other side's messages as read for the given viewer role."""
    conv = await _get_conversation_or_404(db, conversation_id)
    await _assert_participant(db, scope, conv)
    other = "company" if role == "artist" else "artist"
    now = datetime.now(timezone.utc)
    unread = (
        await db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.sender_role == other,
                Message.read_at.is_(None),
            )
        )
    ).scalars().all()
    for m in unread:
        m.read_at = now
    await db.commit()
    return await _decorate(db, conv)
