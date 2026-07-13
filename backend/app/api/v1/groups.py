"""Property group (chain) endpoints + consolidated director dashboard.

Lets a chain director oversee several properties from one place: manage the group,
attach/detach properties, and see a consolidated dashboard across all of them.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DbSession, require_permission
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.property_group import PropertyGroup
from app.models.venue import Venue
from app.schemas.property_group import (
    GroupDashboardOut,
    PropertyGroupCreate,
    PropertyGroupOut,
    PropertyGroupUpdate,
    PropertySummary,
)

router = APIRouter(prefix="/groups", tags=["groups"])


async def _get_group_or_404(db: DbSession, group_id: int) -> PropertyGroup:
    group = await db.get(PropertyGroup, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


async def _property_count(db: DbSession, group_id: int) -> int:
    return (
        await db.execute(
            select(func.count(Company.id)).where(Company.group_id == group_id)
        )
    ).scalar_one()


def _with_count(group: PropertyGroup, count: int) -> PropertyGroupOut:
    return PropertyGroupOut.model_validate(group).model_copy(update={"property_count": count})


@router.post(
    "",
    response_model=PropertyGroupOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def create_group(payload: PropertyGroupCreate, db: DbSession):
    group = PropertyGroup(**payload.model_dump())
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return _with_count(group, 0)


@router.get(
    "",
    response_model=list[PropertyGroupOut],
    dependencies=[Depends(require_permission("company.manage"))],
)
async def list_groups(db: DbSession):
    groups = list((await db.execute(select(PropertyGroup).order_by(PropertyGroup.name))).scalars().all())
    out = []
    for g in groups:
        out.append(_with_count(g, await _property_count(db, g.id)))
    return out


@router.get(
    "/{group_id}",
    response_model=PropertyGroupOut,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def get_group(group_id: int, db: DbSession):
    group = await _get_group_or_404(db, group_id)
    return _with_count(group, await _property_count(db, group_id))


@router.patch(
    "/{group_id}",
    response_model=PropertyGroupOut,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def update_group(group_id: int, payload: PropertyGroupUpdate, db: DbSession):
    group = await _get_group_or_404(db, group_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.commit()
    await db.refresh(group)
    return _with_count(group, await _property_count(db, group_id))


@router.delete(
    "/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def delete_group(group_id: int, db: DbSession):
    group = await _get_group_or_404(db, group_id)
    await db.delete(group)  # Company.group_id is SET NULL - properties survive, become independent
    await db.commit()


@router.post(
    "/{group_id}/properties/{company_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def attach_property(group_id: int, company_id: int, db: DbSession):
    await _get_group_or_404(db, group_id)
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    company.group_id = group_id
    await db.commit()


@router.delete(
    "/{group_id}/properties/{company_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def detach_property(group_id: int, company_id: int, db: DbSession):
    company = await db.get(Company, company_id)
    if company is None or company.group_id != group_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not in this group")
    company.group_id = None
    await db.commit()


@router.get(
    "/{group_id}/dashboard",
    response_model=GroupDashboardOut,
    # Read-only consolidated view = reporting, not management. A chain director
    # (booker role: report.view) must be able to see their own exec dashboard;
    # creating/editing/attaching properties stays gated by company.manage above.
    dependencies=[Depends(require_permission("report.view"))],
)
async def group_dashboard(group_id: int, db: DbSession):
    """Consolidated dashboard across all properties of the group - what a chain
    director sees when overseeing (for the example) their 12 hotels at once."""
    group = await _get_group_or_404(db, group_id)
    companies = list(
        (await db.execute(select(Company).where(Company.group_id == group_id).order_by(Company.name)))
        .scalars()
        .all()
    )
    # venues count + capacity per property, in one grouped query
    rows = (
        await db.execute(
            select(
                Venue.company_id,
                func.count(Venue.id),
                func.coalesce(func.sum(Venue.capacity), 0),
            )
            .where(Venue.company_id.in_([c.id for c in companies]) if companies else False)
            .group_by(Venue.company_id)
        )
    ).all()
    stats = {cid: (n, cap) for cid, n, cap in rows}

    # actuaciones + gasto per property (confirmed + completed count as booked spend)
    counted = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED)
    brows = (
        await db.execute(
            select(
                Booking.company_id,
                func.count(Booking.id),
                func.coalesce(func.sum(Booking.agreed_price), 0),
            )
            .where(
                Booking.company_id.in_([c.id for c in companies]) if companies else False,
                Booking.status.in_(counted),
            )
            .group_by(Booking.company_id)
        )
    ).all()
    bstats = {cid: (n, spend) for cid, n, spend in brows}

    props = []
    total_venues = total_cap = total_bookings = 0
    total_spend = 0.0
    for c in companies:
        n, cap = stats.get(c.id, (0, 0))
        bn, spend = bstats.get(c.id, (0, 0))
        total_venues += n
        total_cap += int(cap)
        total_bookings += bn
        total_spend += float(spend)
        props.append(PropertySummary(
            id=c.id, name=c.name, company_type=c.company_type, city=c.city,
            risk_tier=c.risk_tier, venues_count=n, total_capacity=int(cap),
            bookings_count=bn, total_spend=float(spend),
        ))
    return GroupDashboardOut(
        group_id=group.id, group_name=group.name, property_count=len(companies),
        total_venues=total_venues, total_capacity=total_cap,
        total_bookings=total_bookings, total_spend=round(total_spend, 2),
        properties=props,
    )
