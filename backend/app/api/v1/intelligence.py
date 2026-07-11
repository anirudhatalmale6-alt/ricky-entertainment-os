"""Market Intelligence endpoints.

Reads the property profile + monthly budget + real bookings and produces the
benchmarking that lets a hotel see how it stacks up against the market:
- entertainment-spend intensity  = gasto / facturacion de habitaciones
- comparative vs the whole market and vs same-star peers
- how the market's entertainment spend splits across 5* / 4* / ... properties
- which act categories are rising or falling this month vs the previous one

The market comparative (the vs-market / vs-peers / by-star blocks) is the piece
sold as the premium "Partners" add-on; the endpoint marks it so the UI can gate
it per property.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, require_permission
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.property_budget import PropertyBudget
from app.models.show import Show
from app.schemas.intelligence import (
    CategoryTrend,
    MarketIntelligenceOut,
    PropertyIntelligence,
    StarTierStat,
)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

_BOOKED = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED)
_DAYS_IN_MONTH = 30  # room-revenue estimate normalises the monthly budget


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _pct(part: float, whole: float) -> float | None:
    return round(part / whole * 100, 2) if whole else None


async def _spend_by_company(db, company_ids, start, end) -> dict[int, float]:
    if not company_ids:
        return {}
    rows = (
        await db.execute(
            select(Booking.company_id, func.coalesce(func.sum(Booking.agreed_price), 0))
            .where(
                Booking.company_id.in_(company_ids),
                Booking.status.in_(_BOOKED),
                Booking.starts_at >= start,
                Booking.starts_at < end,
            )
            .group_by(Booking.company_id)
        )
    ).all()
    return {cid: float(total) for cid, total in rows}


async def _spend_by_category(db, company_ids, start, end) -> dict[str, float]:
    if not company_ids:
        return {}
    rows = (
        await db.execute(
            select(Show.category, func.coalesce(func.sum(Booking.agreed_price), 0))
            .join(Show, Show.id == Booking.show_id)
            .where(
                Booking.company_id.in_(company_ids),
                Booking.status.in_(_BOOKED),
                Booking.starts_at >= start,
                Booking.starts_at < end,
            )
            .group_by(Show.category)
        )
    ).all()
    return {cat: float(total) for cat, total in rows if cat}


@router.get(
    "/market",
    response_model=MarketIntelligenceOut,
    dependencies=[Depends(require_permission("report.view"))],
)
async def market_intelligence(
    db: DbSession,
    year: int | None = None,
    month: int | None = None,
    group_id: int | None = Query(default=None),
):
    """Consolidated market benchmarking for a given month (defaults to current)."""
    now = datetime.now(timezone.utc)
    year = year or now.year
    month = month or now.month
    start, end = _month_bounds(year, month)
    prev_start, prev_end = _month_bounds(*_prev_month(year, month))

    q = select(Company).order_by(Company.name)
    if group_id is not None:
        q = q.where(Company.group_id == group_id)
    companies = list((await db.execute(q)).scalars().all())
    company_ids = [c.id for c in companies]

    # monthly budget rows for this period
    budgets: dict[int, PropertyBudget] = {}
    if company_ids:
        brows = (
            await db.execute(
                select(PropertyBudget).where(
                    PropertyBudget.company_id.in_(company_ids),
                    PropertyBudget.year == year,
                    PropertyBudget.month == month,
                )
            )
        ).scalars().all()
        budgets = {b.company_id: b for b in brows}

    spend = await _spend_by_company(db, company_ids, start, end)
    cur_cat = await _spend_by_category(db, company_ids, start, end)
    prev_cat = await _spend_by_category(db, company_ids, prev_start, prev_end)

    # --- per property ---
    props: list[PropertyIntelligence] = []
    for c in companies:
        b = budgets.get(c.id)
        adr = float(c.avg_daily_rate) if c.avg_daily_rate is not None else None
        occ = float(b.occupancy_pct) if (b and b.occupancy_pct is not None) else None
        budget_amt = float(b.entertainment_budget) if b else None

        est_rev = None
        if c.rooms and adr and occ is not None:
            est_rev = round(c.rooms * adr * (occ / 100) * _DAYS_IN_MONTH, 2)
        intensity = _pct(budget_amt, est_rev) if (budget_amt is not None and est_rev) else None

        props.append(PropertyIntelligence(
            id=c.id, name=c.name, star_rating=c.star_rating, rooms=c.rooms,
            avg_daily_rate=adr, occupancy_pct=occ, est_room_revenue=est_rev,
            entertainment_budget=budget_amt, entertainment_spend=spend.get(c.id, 0.0),
            intensity_pct=intensity, is_partner=c.is_partner,
        ))

    # --- market average intensity + deltas ---
    intensities = [p.intensity_pct for p in props if p.intensity_pct is not None]
    market_avg = round(sum(intensities) / len(intensities), 2) if intensities else None

    # per-star average intensity (for the peer comparison)
    star_intensity: dict[int, list[float]] = {}
    for p in props:
        if p.star_rating is not None and p.intensity_pct is not None:
            star_intensity.setdefault(p.star_rating, []).append(p.intensity_pct)
    star_avg = {s: sum(v) / len(v) for s, v in star_intensity.items()}

    for p in props:
        if p.intensity_pct is not None:
            if market_avg is not None:
                p.vs_market_pct = round(p.intensity_pct - market_avg, 2)
            if p.star_rating in star_avg:
                p.vs_star_peers_pct = round(p.intensity_pct - star_avg[p.star_rating], 2)

    # --- spend distribution by star rating ---
    total_spend = round(sum(spend.values()), 2)
    star_groups: dict[int, list[PropertyIntelligence]] = {}
    for p in props:
        if p.star_rating is not None:
            star_groups.setdefault(p.star_rating, []).append(p)
    by_star: list[StarTierStat] = []
    for s in sorted(star_groups, reverse=True):
        members = star_groups[s]
        s_spend = round(sum(m.entertainment_spend for m in members), 2)
        s_int = [m.intensity_pct for m in members if m.intensity_pct is not None]
        by_star.append(StarTierStat(
            star_rating=s, properties=len(members),
            avg_intensity_pct=round(sum(s_int) / len(s_int), 2) if s_int else None,
            total_spend=s_spend, spend_share_pct=_pct(s_spend, total_spend) or 0.0,
        ))

    # --- act-category trend (this month vs previous) ---
    total_cur_cat = round(sum(cur_cat.values()), 2)
    cats: list[CategoryTrend] = []
    for cat in sorted(set(cur_cat) | set(prev_cat), key=lambda k: cur_cat.get(k, 0), reverse=True):
        cur = round(cur_cat.get(cat, 0.0), 2)
        prev = round(prev_cat.get(cat, 0.0), 2)
        delta = round(cur - prev, 2)
        trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
        cats.append(CategoryTrend(
            category=cat, spend=cur, prev_spend=prev, delta=delta,
            change_pct=_pct(delta, prev), share_pct=_pct(cur, total_cur_cat) or 0.0,
            trend=trend,
        ))

    total_budget = round(sum(p.entertainment_budget or 0.0 for p in props), 2)

    return MarketIntelligenceOut(
        year=year, month=month, property_count=len(companies),
        market_avg_intensity_pct=market_avg,
        total_entertainment_budget=total_budget, total_entertainment_spend=total_spend,
        properties=props, by_star_rating=by_star, spend_by_category=cats,
        note=("Intensidad = gasto de entretenimiento / facturacion estimada de "
              "habitaciones (tarifa * ocupacion * habitaciones). El comparativo "
              "de mercado (vs_market, vs pares, por estrellas) es la funcion "
              "premium para Partners."),
    )
