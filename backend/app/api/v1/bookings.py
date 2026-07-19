"""Actuacion (booking) endpoints.

The heart of the marketplace: request a show at a venue for a date, confirm it,
run it, register attendance. Business rules baked in (David's calls):

  * 1h travel buffer  - the same artist cannot hold two overlapping actuaciones;
                        a 1h gap is required around each one.
  * 2h cancellation   - an actuacion cannot be cancelled inside 2h of its start.

company_id / artist_id / commission_pct are derived server-side from the chosen
venue and show, and the commission is snapshotted so later re-tiering never
rewrites past money.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentScope, DbSession, require_permission
from app.models.artist import Artist
from app.models.booking import Booking
from app.models.company import Company
from app.models.notification import ArtistNotification
from app.models.enums import (
    CANCELLATION_CUTOFF_HOURS,
    RISK_COMMISSION,
    TRAVEL_BUFFER_HOURS,
    BookingStatus,
)
from app.models.show import Show
from app.models.venue import Venue
from app.schemas.booking import (
    AttendanceIn,
    BookingCreate,
    BookingOut,
    BookingUpdate,
)

router = APIRouter(prefix="/bookings", tags=["bookings"])

_ACTIVE = (BookingStatus.PENDING, BookingStatus.CONFIRMED)


def _naive(dt: datetime) -> datetime:
    """Drop tzinfo so naive (SQLite) and aware datetimes compare cleanly."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_or_404(db: DbSession, booking_id: int) -> Booking:
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking


def _decorate(
    booking: Booking,
    venue: Venue | None,
    show: Show | None,
    company: Company | None = None,
) -> BookingOut:
    out = BookingOut.model_validate(booking)
    return out.model_copy(update={
        "venue_capacity": venue.capacity if venue else None,
        "venue_name": venue.name if venue else None,
        "show_name": show.show_name if show else None,
        "company_name": company.name if company else None,
    })


async def _check_travel_buffer(db: DbSession, artist_id: int, starts_at: datetime,
                               ends_at: datetime | None, exclude_id: int | None = None):
    """Reject if this artist already has an active actuacion within the 1h buffer."""
    new_start = _naive(starts_at) - timedelta(hours=TRAVEL_BUFFER_HOURS)
    new_end = _naive(ends_at or starts_at) + timedelta(hours=TRAVEL_BUFFER_HOURS)
    rows = (await db.execute(
        select(Booking).where(
            Booking.artist_id == artist_id,
            Booking.status.in_(_ACTIVE),
        )
    )).scalars().all()
    for b in rows:
        if exclude_id is not None and b.id == exclude_id:
            continue
        b_start = _naive(b.starts_at)
        b_end = _naive(b.ends_at or b.starts_at)
        if b_start < new_end and new_start < b_end:  # overlap with buffer
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El artista ya tiene una actuacion el "
                    f"{b_start:%Y-%m-%d %H:%M}. Se necesita al menos "
                    f"{TRAVEL_BUFFER_HOURS}h de margen entre shows."
                ),
            )


@router.post(
    "",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def create_booking(payload: BookingCreate, db: DbSession):
    show = await db.get(Show, payload.show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")
    venue = await db.get(Venue, payload.venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    company = await db.get(Company, venue.company_id) if venue.company_id else None
    commission_pct = (
        round(RISK_COMMISSION[company.risk_tier] * 100, 2) if company else None
    )

    await _check_travel_buffer(db, show.artist_id, payload.starts_at, payload.ends_at)

    # The artist decides how incoming actuaciones are handled: auto-confirmed, or
    # left pending for them to accept/reject (see Artist.auto_confirm_bookings).
    artist = await db.get(Artist, show.artist_id) if show.artist_id else None
    auto = bool(artist and artist.auto_confirm_bookings)

    booking = Booking(
        show_id=show.id,
        venue_id=venue.id,
        company_id=venue.company_id,
        artist_id=show.artist_id,
        booker_id=payload.booker_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        event_type=payload.event_type,
        agreed_price=payload.agreed_price,
        currency=payload.currency,
        commission_pct=commission_pct,
        notes=payload.notes,
        status=BookingStatus.CONFIRMED if auto else BookingStatus.PENDING,
        confirmed_at=_now() if auto else None,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return _decorate(booking, venue, show)


@router.get(
    "",
    response_model=list[BookingOut],
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def list_bookings(
    db: DbSession,
    company_id: int | None = None,
    group_id: int | None = None,
    venue_id: int | None = None,
    artist_id: int | None = None,
    status_filter: BookingStatus | None = Query(None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """Calendar / agenda feed. Filter by property, chain, venue, artist, status
    or a date window - the same endpoint powers every calendar view."""
    stmt = select(Booking)
    if group_id is not None:
        # all properties of the chain
        sub = select(Company.id).where(Company.group_id == group_id)
        stmt = stmt.where(Booking.company_id.in_(sub))
    if company_id is not None:
        stmt = stmt.where(Booking.company_id == company_id)
    if venue_id is not None:
        stmt = stmt.where(Booking.venue_id == venue_id)
    if artist_id is not None:
        stmt = stmt.where(Booking.artist_id == artist_id)
    if status_filter is not None:
        stmt = stmt.where(Booking.status == status_filter)
    if date_from is not None:
        stmt = stmt.where(Booking.starts_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Booking.starts_at <= date_to)
    stmt = stmt.order_by(Booking.starts_at)

    bookings = list((await db.execute(stmt)).scalars().all())
    # batch-load venue / show / company names for the cards
    vids = {b.venue_id for b in bookings if b.venue_id}
    sids = {b.show_id for b in bookings if b.show_id}
    cids = {b.company_id for b in bookings if b.company_id}
    venues = {v.id: v for v in (
        (await db.execute(select(Venue).where(Venue.id.in_(vids)))).scalars().all()
        if vids else []
    )}
    shows = {s.id: s for s in (
        (await db.execute(select(Show).where(Show.id.in_(sids)))).scalars().all()
        if sids else []
    )}
    companies = {c.id: c for c in (
        (await db.execute(select(Company).where(Company.id.in_(cids)))).scalars().all()
        if cids else []
    )}
    return [_decorate(b, venues.get(b.venue_id), shows.get(b.show_id), companies.get(b.company_id)) for b in bookings]


@router.get("/mine", response_model=list[BookingOut])
async def my_bookings(
    scope: CurrentScope,
    db: DbSession,
    status_filter: BookingStatus | None = Query(None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """My agenda, resolved from who I am: an artist sees their own actuaciones,
    a hotel manager their property's, a group director the whole chain."""
    stmt = select(Booking)
    if scope.is_artist:
        stmt = stmt.where(Booking.artist_id == scope.artist_id)
    elif scope.group_id is not None:
        sub = select(Company.id).where(Company.group_id == scope.group_id)
        stmt = stmt.where(Booking.company_id.in_(sub))
    elif scope.company_id is not None:
        stmt = stmt.where(Booking.company_id == scope.company_id)
    elif not scope.is_admin:
        return []  # authenticated but no linked profile
    if status_filter is not None:
        stmt = stmt.where(Booking.status == status_filter)
    if date_from is not None:
        stmt = stmt.where(Booking.starts_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Booking.starts_at <= date_to)
    stmt = stmt.order_by(Booking.starts_at)

    bookings = list((await db.execute(stmt)).scalars().all())
    vids = {b.venue_id for b in bookings if b.venue_id}
    sids = {b.show_id for b in bookings if b.show_id}
    cids = {b.company_id for b in bookings if b.company_id}
    venues = {v.id: v for v in (
        (await db.execute(select(Venue).where(Venue.id.in_(vids)))).scalars().all() if vids else []
    )}
    shows = {s.id: s for s in (
        (await db.execute(select(Show).where(Show.id.in_(sids)))).scalars().all() if sids else []
    )}
    companies = {c.id: c for c in (
        (await db.execute(select(Company).where(Company.id.in_(cids)))).scalars().all() if cids else []
    )}
    return [_decorate(b, venues.get(b.venue_id), shows.get(b.show_id), companies.get(b.company_id)) for b in bookings]


@router.get(
    "/{booking_id}",
    response_model=BookingOut,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def get_booking(booking_id: int, db: DbSession):
    booking = await _get_or_404(db, booking_id)
    venue = await db.get(Venue, booking.venue_id) if booking.venue_id else None
    show = await db.get(Show, booking.show_id) if booking.show_id else None
    return _decorate(booking, venue, show)


@router.patch(
    "/{booking_id}",
    response_model=BookingOut,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def update_booking(booking_id: int, payload: BookingUpdate, db: DbSession):
    booking = await _get_or_404(db, booking_id)
    if booking.status in (BookingStatus.CANCELLED, BookingStatus.COMPLETED):
        raise HTTPException(status_code=409, detail="No se puede editar una actuacion finalizada o cancelada")
    data = payload.model_dump(exclude_unset=True)
    # re-check the travel buffer if the schedule moved
    if "starts_at" in data or "ends_at" in data:
        new_start = data.get("starts_at", booking.starts_at)
        new_end = data.get("ends_at", booking.ends_at)
        if new_end is not None and new_end <= new_start:
            raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
        if booking.artist_id:
            await _check_travel_buffer(db, booking.artist_id, new_start, new_end, exclude_id=booking.id)
    # moving to another venue (drag on the Calendario Maestro): re-derive the property scope
    if data.get("venue_id") is not None and data["venue_id"] != booking.venue_id:
        new_venue = await db.get(Venue, data["venue_id"])
        if new_venue is None:
            raise HTTPException(status_code=404, detail="Venue not found")
        booking.company_id = new_venue.company_id
    for field, value in data.items():
        setattr(booking, field, value)
    await db.commit()
    await db.refresh(booking)
    venue = await db.get(Venue, booking.venue_id) if booking.venue_id else None
    show = await db.get(Show, booking.show_id) if booking.show_id else None
    return _decorate(booking, venue, show)


@router.post(
    "/{booking_id}/confirm",
    response_model=BookingOut,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def confirm_booking(booking_id: int, db: DbSession):
    booking = await _get_or_404(db, booking_id)
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(status_code=409, detail="Solo se confirma una actuacion pendiente")
    booking.status = BookingStatus.CONFIRMED
    booking.confirmed_at = _now()
    await db.commit()
    await db.refresh(booking)
    venue = await db.get(Venue, booking.venue_id) if booking.venue_id else None
    show = await db.get(Show, booking.show_id) if booking.show_id else None
    return _decorate(booking, venue, show)


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingOut,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def cancel_booking(booking_id: int, db: DbSession, reason: str | None = None):
    booking = await _get_or_404(db, booking_id)
    if booking.status in (BookingStatus.CANCELLED, BookingStatus.COMPLETED):
        raise HTTPException(status_code=409, detail="La actuacion ya esta finalizada o cancelada")
    # 2h cancellation cut-off
    if _naive(booking.starts_at) - _now() < timedelta(hours=CANCELLATION_CUTOFF_HOURS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede cancelar dentro de las {CANCELLATION_CUTOFF_HOURS}h "
                f"previas al inicio de la actuacion."
            ),
        )
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = _now()
    booking.cancellation_reason = reason
    await db.commit()
    await db.refresh(booking)
    venue = await db.get(Venue, booking.venue_id) if booking.venue_id else None
    show = await db.get(Show, booking.show_id) if booking.show_id else None
    return _decorate(booking, venue, show)


@router.post("/{booking_id}/artist-respond", response_model=BookingOut)
async def artist_respond(
    booking_id: int,
    scope: CurrentScope,
    db: DbSession,
    action: str = Query(..., pattern="^(accept|reject)$"),
):
    """The artist accepts or rejects one of THEIR OWN pending actuaciones.

    This is the manual-approval path (Artist.auto_confirm_bookings = False): a new
    actuacion arrives 'pendiente' and the artist decides. Rejecting a pending
    request is not the same as cancelling a confirmed show, so the 2h cut-off does
    not apply here."""
    if scope.artist_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo artistas.")
    booking = await _get_or_404(db, booking_id)
    if booking.artist_id != scope.artist_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(status_code=409, detail="Esta actuacion ya no esta pendiente.")
    if action == "accept":
        booking.status = BookingStatus.CONFIRMED
        booking.confirmed_at = _now()
    else:
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = _now()
        booking.cancellation_reason = "Rechazada por el artista"
    await db.commit()
    await db.refresh(booking)
    venue = await db.get(Venue, booking.venue_id) if booking.venue_id else None
    show = await db.get(Show, booking.show_id) if booking.show_id else None
    return _decorate(booking, venue, show)


@router.post(
    "/{booking_id}/attendance",
    response_model=BookingOut,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def register_attendance(booking_id: int, payload: AttendanceIn, db: DbSession):
    """Register the headcount at start/end. Marks the actuacion COMPLETED so its
    occupancy / retention / abandonment metrics roll into the analytics."""
    booking = await _get_or_404(db, booking_id)
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="No se registra asistencia de una actuacion cancelada")
    if payload.headcount_start is not None:
        booking.headcount_start = payload.headcount_start
    if payload.headcount_end is not None:
        booking.headcount_end = payload.headcount_end
    booking.status = BookingStatus.COMPLETED
    await db.commit()
    await db.refresh(booking)
    venue = await db.get(Venue, booking.venue_id) if booking.venue_id else None
    show = await db.get(Show, booking.show_id) if booking.show_id else None
    return _decorate(booking, venue, show)


@router.delete(
    "/{booking_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def delete_booking(booking_id: int, db: DbSession):
    booking = await _get_or_404(db, booking_id)
    await db.delete(booking)
    await db.commit()


class NotifyItem(BaseModel):
    booking_id: int
    kind: str = "new_booking"  # new_booking | reschedule


class NotifyIn(BaseModel):
    items: list[NotifyItem]


@router.post(
    "/notify",
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def notify_artists(payload: NotifyIn, db: DbSession):
    """"Guardar y notificar": create an in-app aviso for each affected artist.

    Called from the Calendario Maestro when the hotel finishes arranging the
    week. One notification per booking; the artist sees them in their bell
    inbox. WhatsApp/email is a later channel (David 2026-07-18).
    """
    notified = 0
    artists: set[int] = set()
    for item in payload.items:
        booking = await db.get(Booking, item.booking_id)
        if booking is None or not booking.artist_id:
            continue
        show = await db.get(Show, booking.show_id) if booking.show_id else None
        venue = await db.get(Venue, booking.venue_id) if booking.venue_id else None
        st = booking.starts_at
        when = _naive(st).strftime("%d/%m/%Y a las %H:%M") if st else "una fecha por confirmar"
        show_name = (show.show_name if show else None) or "tu actuación"
        venue_name = (venue.name if venue else None) or "el venue"
        if item.kind == "reschedule":
            title = f"Cambio de horario: {show_name}"
            body = f"Tu actuación en {venue_name} se movió a {when}."
        else:
            title = f"Nueva actuación: {show_name}"
            body = (
                f"Fuiste agendado en {venue_name} para el {when}. "
                "Queda pendiente de tu confirmación."
            )
        db.add(ArtistNotification(
            artist_id=booking.artist_id,
            booking_id=booking.id,
            kind=item.kind if item.kind in ("new_booking", "reschedule") else "new_booking",
            title=title,
            body=body,
            starts_at=st,
            is_read=False,
        ))
        notified += 1
        artists.add(booking.artist_id)
    await db.commit()
    return {"notified": notified, "artists": len(artists)}
