"""Requests board endpoints ("solicitudes" + "propuestas").

Freelancer-style flow: a contratante publishes a ProductRequest, artists browse
the open ones and answer with a RequestProposal, and the hotel accepts one.

Write actions are guarded with booking.manage and browse/read with report.view
for now; once the artist- and contratante-side logins are wired, the artist_id /
company_id will come from the session instead of the payload.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession, require_permission
from app.models.artist import Artist
from app.models.company import Company
from app.models.enums import ProposalStatus, RequestStatus
from app.models.product_request import ProductRequest, RequestProposal
from app.schemas.product_request import (
    ProductRequestCreate,
    ProductRequestOut,
    ProductRequestUpdate,
    ProposalCreate,
    ProposalOut,
)

router = APIRouter(prefix="/requests", tags=["requests"])


async def _get_request_or_404(db: DbSession, request_id: int) -> ProductRequest:
    req = await db.get(ProductRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return req


async def _decorate(db: DbSession, req: ProductRequest) -> ProductRequestOut:
    out = ProductRequestOut.model_validate(req)
    company_name = None
    if req.company_id:
        c = await db.get(Company, req.company_id)
        company_name = c.name if c else None
    count = (
        await db.execute(
            select(func.count(RequestProposal.id)).where(RequestProposal.request_id == req.id)
        )
    ).scalar_one()
    return out.model_copy(update={"company_name": company_name, "proposals_count": count})


# --- Solicitudes ----------------------------------------------------------

@router.post(
    "",
    response_model=ProductRequestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def create_request(payload: ProductRequestCreate, db: DbSession):
    if payload.company_id is not None and await db.get(Company, payload.company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")
    req = ProductRequest(**payload.model_dump())
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return await _decorate(db, req)


@router.get(
    "",
    response_model=list[ProductRequestOut],
    dependencies=[Depends(require_permission("report.view"))],
)
async def list_requests(
    db: DbSession,
    status_: RequestStatus | None = Query(default=None, alias="status"),
    category: str | None = None,
    subcategory: str | None = None,
    city: str | None = None,
    company_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """Browse requests - what artists see on the board. Defaults to every status;
    pass status=open to see only the ones still taking proposals."""
    q = select(ProductRequest)
    if status_ is not None:
        q = q.where(ProductRequest.status == status_)
    if category:
        q = q.where(ProductRequest.category == category)
    if subcategory:
        q = q.where(ProductRequest.subcategory == subcategory)
    if city:
        q = q.where(ProductRequest.city == city)
    if company_id is not None:
        q = q.where(ProductRequest.company_id == company_id)
    if date_from is not None:
        q = q.where(ProductRequest.event_date >= date_from)
    if date_to is not None:
        q = q.where(ProductRequest.event_date <= date_to)
    q = q.order_by(ProductRequest.created_at.desc())
    reqs = list((await db.execute(q)).scalars().all())

    # batch counts + company names
    ids = [r.id for r in reqs]
    counts: dict[int, int] = {}
    if ids:
        rows = (
            await db.execute(
                select(RequestProposal.request_id, func.count(RequestProposal.id))
                .where(RequestProposal.request_id.in_(ids))
                .group_by(RequestProposal.request_id)
            )
        ).all()
        counts = {rid: n for rid, n in rows}
    cids = {r.company_id for r in reqs if r.company_id}
    names: dict[int, str] = {}
    if cids:
        rows = (await db.execute(select(Company.id, Company.name).where(Company.id.in_(cids)))).all()
        names = {cid: name for cid, name in rows}

    out = []
    for r in reqs:
        out.append(ProductRequestOut.model_validate(r).model_copy(update={
            "company_name": names.get(r.company_id),
            "proposals_count": counts.get(r.id, 0),
        }))
    return out


@router.get(
    "/{request_id}",
    response_model=ProductRequestOut,
    dependencies=[Depends(require_permission("report.view"))],
)
async def get_request(request_id: int, db: DbSession):
    return await _decorate(db, await _get_request_or_404(db, request_id))


@router.patch(
    "/{request_id}",
    response_model=ProductRequestOut,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def update_request(request_id: int, payload: ProductRequestUpdate, db: DbSession):
    req = await _get_request_or_404(db, request_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(req, field, value)
    await db.commit()
    await db.refresh(req)
    return await _decorate(db, req)


@router.delete(
    "/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def delete_request(request_id: int, db: DbSession):
    req = await _get_request_or_404(db, request_id)
    await db.delete(req)
    await db.commit()


# --- Propuestas -----------------------------------------------------------

async def _decorate_proposal(db: DbSession, p: RequestProposal) -> ProposalOut:
    name = None
    if p.artist_id:
        a = await db.get(Artist, p.artist_id)
        name = a.stage_name if a else None
    return ProposalOut.model_validate(p).model_copy(update={"artist_name": name})


@router.post(
    "/{request_id}/proposals",
    response_model=ProposalOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def submit_proposal(request_id: int, payload: ProposalCreate, db: DbSession):
    """An artist answers a request. One live proposal per artist (re-sending
    updates the existing one)."""
    req = await _get_request_or_404(db, request_id)
    if req.status != RequestStatus.OPEN:
        raise HTTPException(status_code=409, detail="La solicitud ya no admite propuestas")
    if await db.get(Artist, payload.artist_id) is None:
        raise HTTPException(status_code=404, detail="Artist not found")
    existing = (
        await db.execute(
            select(RequestProposal).where(
                RequestProposal.request_id == request_id,
                RequestProposal.artist_id == payload.artist_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        p = RequestProposal(request_id=request_id, **payload.model_dump())
        db.add(p)
    else:
        for field, value in payload.model_dump(exclude={"artist_id"}).items():
            setattr(existing, field, value)
        existing.status = ProposalStatus.PENDING
        p = existing
    await db.commit()
    await db.refresh(p)
    return await _decorate_proposal(db, p)


@router.get(
    "/{request_id}/proposals",
    response_model=list[ProposalOut],
    dependencies=[Depends(require_permission("report.view"))],
)
async def list_proposals(request_id: int, db: DbSession):
    await _get_request_or_404(db, request_id)
    rows = list(
        (await db.execute(
            select(RequestProposal)
            .where(RequestProposal.request_id == request_id)
            .order_by(RequestProposal.created_at)
        )).scalars().all()
    )
    aids = {p.artist_id for p in rows if p.artist_id}
    names: dict[int, str] = {}
    if aids:
        nrows = (await db.execute(select(Artist.id, Artist.stage_name).where(Artist.id.in_(aids)))).all()
        names = {aid: name for aid, name in nrows}
    return [
        ProposalOut.model_validate(p).model_copy(update={"artist_name": names.get(p.artist_id)})
        for p in rows
    ]


async def _get_proposal_or_404(db: DbSession, request_id: int, proposal_id: int) -> RequestProposal:
    p = await db.get(RequestProposal, proposal_id)
    if p is None or p.request_id != request_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return p


@router.post(
    "/{request_id}/proposals/{proposal_id}/accept",
    response_model=ProposalOut,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def accept_proposal(request_id: int, proposal_id: int, db: DbSession):
    """Hotel picks a winner: this proposal is accepted, the rest rejected, and
    the request is marked fulfilled."""
    req = await _get_request_or_404(db, request_id)
    winner = await _get_proposal_or_404(db, request_id, proposal_id)
    others = list(
        (await db.execute(
            select(RequestProposal).where(RequestProposal.request_id == request_id)
        )).scalars().all()
    )
    for p in others:
        p.status = ProposalStatus.ACCEPTED if p.id == winner.id else ProposalStatus.REJECTED
    req.status = RequestStatus.FULFILLED
    await db.commit()
    await db.refresh(winner)
    return await _decorate_proposal(db, winner)


@router.post(
    "/{request_id}/proposals/{proposal_id}/withdraw",
    response_model=ProposalOut,
    dependencies=[Depends(require_permission("booking.manage"))],
)
async def withdraw_proposal(request_id: int, proposal_id: int, db: DbSession):
    """The artist pulls their proposal."""
    p = await _get_proposal_or_404(db, request_id, proposal_id)
    p.status = ProposalStatus.WITHDRAWN
    await db.commit()
    await db.refresh(p)
    return await _decorate_proposal(db, p)
