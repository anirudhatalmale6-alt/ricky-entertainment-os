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

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select

from app.api.deps import DbSession, require_permission
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.product_request import ProductRequest
from app.models.property_budget import PropertyBudget
from app.models.show import Show
from app.schemas.intelligence import (
    CategoryTrend,
    DemandIntelligenceOut,
    DemandRow,
    DestinationStat,
    DestinationStudyOut,
    MarketIntelligenceOut,
    PriceRange,
    PriceRangesOut,
    PropertyIntelligence,
    SeasonalityOut,
    SeasonMonth,
    StarTierStat,
    ZoneIntelligenceOut,
    ZoneStat,
)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

_BOOKED = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED)
_DAYS_IN_MONTH = 30  # room-revenue estimate normalises the monthly budget
_GUESTS_PER_ROOM = 2.1  # supuesto para "gasto por huesped" (David); configurable
_MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
              "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


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

        # David's cost benchmarks (his corrected formula, 2026-07-14): both are
        # based on the PRESUPUESTO that each boss loads for the month, so they are
        # comparable on the same basis.
        #   gasto por habitacion = presupuesto / habitaciones
        #   gasto por huesped     = presupuesto / (habitaciones * ocupacion * 2.1)
        c_spend = spend.get(c.id, 0.0)
        per_room = round(budget_amt / c.rooms, 2) if (budget_amt and c.rooms) else None
        guests = (c.rooms * (occ / 100) * _GUESTS_PER_ROOM) if (c.rooms and occ) else None
        per_guest = round(budget_amt / guests, 2) if (budget_amt and guests) else None

        props.append(PropertyIntelligence(
            id=c.id, name=c.name, star_rating=c.star_rating, rooms=c.rooms,
            avg_daily_rate=adr, occupancy_pct=occ, est_room_revenue=est_rev,
            entertainment_budget=budget_amt, entertainment_spend=c_spend,
            intensity_pct=intensity, spend_per_room=per_room, spend_per_guest=per_guest,
            city=c.city, is_partner=c.is_partner,
        ))

    # --- market average intensity + deltas ---
    intensities = [p.intensity_pct for p in props if p.intensity_pct is not None]
    market_avg = round(sum(intensities) / len(intensities), 2) if intensities else None

    # market averages of the cost benchmarks (only properties that have a spend)
    per_rooms = [p.spend_per_room for p in props if p.spend_per_room]
    per_guests = [p.spend_per_guest for p in props if p.spend_per_guest]
    mkt_per_room = round(sum(per_rooms) / len(per_rooms), 2) if per_rooms else None
    mkt_per_guest = round(sum(per_guests) / len(per_guests), 2) if per_guests else None

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
        market_avg_spend_per_room=mkt_per_room, market_avg_spend_per_guest=mkt_per_guest,
        guests_per_room=_GUESTS_PER_ROOM,
        total_entertainment_budget=total_budget, total_entertainment_spend=total_spend,
        properties=props, by_star_rating=by_star, spend_by_category=cats,
        note=("Intensidad = gasto de entretenimiento / facturacion estimada de "
              "habitaciones (tarifa * ocupacion * habitaciones). El comparativo "
              "de mercado (vs_market, vs pares, por estrellas) es la funcion "
              "premium para Partners."),
    )


# --- Demand intelligence (supplier-facing) ---------------------------------

async def _resolve_company_ids(db, group_id: int | None) -> list[int] | None:
    """Company ids of a group, or None to mean 'the whole market'."""
    if group_id is None:
        return None
    rows = (
        await db.execute(select(Company.id).where(Company.group_id == group_id))
    ).all()
    return [cid for (cid,) in rows]


async def _request_demand(db, col, cids, start, end, category=None) -> dict[str, int]:
    q = select(col, func.count(ProductRequest.id)).where(
        ProductRequest.created_at >= start,
        ProductRequest.created_at < end,
        col.is_not(None),
    )
    if category is not None:
        q = q.where(ProductRequest.category == category)
    if cids is not None:
        q = q.where(ProductRequest.company_id.in_(cids))
    rows = (await db.execute(q.group_by(col))).all()
    return {k: n for k, n in rows if k}


async def _booking_demand(db, col, cids, start, end, category=None) -> dict[str, tuple[int, float]]:
    booked_value = func.coalesce(
        func.sum(case((Booking.status.in_(_BOOKED), Booking.agreed_price), else_=0)), 0
    )
    q = (
        select(col, func.count(Booking.id), booked_value)
        .join(Show, Show.id == Booking.show_id)
        .where(
            Booking.created_at >= start,
            Booking.created_at < end,
            Booking.status != BookingStatus.CANCELLED,
            col.is_not(None),
        )
    )
    if category is not None:
        q = q.where(Show.category == category)
    if cids is not None:
        q = q.where(Booking.company_id.in_(cids))
    rows = (await db.execute(q.group_by(col))).all()
    return {k: (n, float(v)) for k, n, v in rows if k}


def _demand_rows(req_cur, book_cur, req_prev, book_prev, limit=None) -> list[DemandRow]:
    keys = set(req_cur) | set(book_cur) | set(req_prev) | set(book_prev)
    rows: list[DemandRow] = []
    for k in keys:
        rq = req_cur.get(k, 0)
        bk, val = book_cur.get(k, (0, 0.0))
        score = rq + bk
        prev = req_prev.get(k, 0) + book_prev.get(k, (0, 0.0))[0]
        delta = score - prev
        rows.append(DemandRow(
            key=k, requests=rq, bookings=bk, booked_value=round(val, 2),
            demand_score=score, prev_score=prev, change_pct=_pct(delta, prev),
            trend="up" if delta > 0 else "down" if delta < 0 else "flat",
        ))
    total = sum(r.demand_score for r in rows)
    for r in rows:
        r.share_pct = _pct(r.demand_score, total) or 0.0
    rows.sort(key=lambda r: r.demand_score, reverse=True)
    return rows[:limit] if limit else rows


@router.get(
    "/demand",
    response_model=DemandIntelligenceOut,
    dependencies=[Depends(require_permission("report.view"))],
)
async def demand_intelligence(
    db: DbSession,
    days: int = Query(default=90, ge=1, le=365),
    group_id: int | None = Query(default=None),
    category: str | None = Query(default=None, description="Filtra a una categoria (p.ej. Musica o Shows) para ver el crecimiento de sus subgeneros"),
):
    """What the market is asking for - so proveedores/artistas know what to offer.

    Ranks act categories and subcategories by demand (published requests +
    contracted actuaciones) over the last `days`, with the trend vs the previous
    equal window. Pass `category` to drill into one category's subgenres - this
    is what powers "Trends Music" / "Trends Shows".
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now - timedelta(days=days)
    prev_start = now - timedelta(days=2 * days)
    cids = await _resolve_company_ids(db, group_id)

    cat_req_cur = await _request_demand(db, ProductRequest.category, cids, start, now, category)
    cat_book_cur = await _booking_demand(db, Show.category, cids, start, now, category)
    cat_req_prev = await _request_demand(db, ProductRequest.category, cids, prev_start, start, category)
    cat_book_prev = await _booking_demand(db, Show.category, cids, prev_start, start, category)

    sub_req_cur = await _request_demand(db, ProductRequest.subcategory, cids, start, now, category)
    sub_book_cur = await _booking_demand(db, Show.subcategory, cids, start, now, category)
    sub_req_prev = await _request_demand(db, ProductRequest.subcategory, cids, prev_start, start, category)
    sub_book_prev = await _booking_demand(db, Show.subcategory, cids, prev_start, start, category)

    top_categories = _demand_rows(cat_req_cur, cat_book_cur, cat_req_prev, cat_book_prev)
    top_subcategories = _demand_rows(sub_req_cur, sub_book_cur, sub_req_prev, sub_book_prev, limit=10)

    return DemandIntelligenceOut(
        window_days=days,
        total_requests=sum(cat_req_cur.values()),
        total_bookings=sum(n for n, _ in cat_book_cur.values()),
        top_categories=top_categories,
        top_subcategories=top_subcategories,
        note=("Demanda = solicitudes publicadas + actuaciones contratadas en la "
              "ventana. Sirve para que los proveedores sepan que es lo que mas se "
              "esta pidiendo y hacia donde crece."),
    )


# --- Zone intelligence (heat map + tarifa promedio por zona) ---------------

@router.get(
    "/zones",
    response_model=ZoneIntelligenceOut,
    dependencies=[Depends(require_permission("report.view"))],
)
async def zone_intelligence(
    db: DbSession,
    days: int = Query(default=90, ge=1, le=365),
    group_id: int | None = Query(default=None),
):
    """Geografia de la demanda por ciudad/zona: donde se contrata mas (mapa de
    calor) y donde la tarifa promedio es mas alta. 'Zona' = ciudad del hotel
    (aun no guardamos coordenadas para un mapa geografico con pines)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now - timedelta(days=days)

    booked_price = func.coalesce(
        func.sum(case((Booking.status.in_(_BOOKED), Booking.agreed_price), else_=0)), 0
    )
    booked_cnt = func.coalesce(
        func.sum(case((Booking.status.in_(_BOOKED), 1), else_=0)), 0
    )
    q = (
        select(
            Company.city,
            func.count(Company.id.distinct()),
            func.count(Booking.id),
            booked_price,
            booked_cnt,
        )
        .join(Company, Company.id == Booking.company_id)
        .where(
            Booking.created_at >= start,
            Booking.created_at < now,
            Booking.status != BookingStatus.CANCELLED,
            Company.city.is_not(None),
        )
    )
    if group_id is not None:
        q = q.where(Company.group_id == group_id)
    rows = (await db.execute(q.group_by(Company.city))).all()

    total_bookings = sum(int(n) for _, _, n, _, _ in rows)
    zones: list[ZoneStat] = []
    for city, n_props, n_book, spend, n_booked in rows:
        zones.append(ZoneStat(
            zone=city,
            properties=int(n_props),
            bookings=int(n_book),
            total_spend=round(float(spend), 2),
            avg_price=round(float(spend) / int(n_booked), 2) if int(n_booked) else None,
            share_pct=_pct(int(n_book), total_bookings) or 0.0,
        ))
    zones.sort(key=lambda z: z.bookings, reverse=True)

    return ZoneIntelligenceOut(
        window_days=days,
        total_bookings=total_bookings,
        zones=zones,
        note=("Mapa de calor por ciudad segun contrataciones + tarifa promedio por "
              "zona. Zona = ciudad del hotel; para un mapa geografico con pines se "
              "agregarian coordenadas mas adelante."),
    )


# --- Destination market study (promedios de todos los hoteles por destino) --

@router.get(
    "/destinations",
    response_model=DestinationStudyOut,
    dependencies=[Depends(require_permission("report.view"))],
)
async def destination_study(
    db: DbSession,
    year: int | None = None,
    month: int | None = None,
    days: int = Query(default=180, ge=1, le=365),
):
    """Estudio de mercado por DESTINO: promedia el gasto/habitacion, gasto/huesped,
    intensidad y ocupacion de TODOS los hoteles de cada ciudad (no compara
    propiedades individuales - es un benchmark anonimo del mercado). Las metricas
    de presupuesto son del mes dado; contrataciones y tarifa promedio, de la
    ventana de `days`."""
    now = datetime.now(timezone.utc)
    year = year or now.year
    month = month or now.month
    now_naive = now.replace(tzinfo=None)
    win_start = now_naive - timedelta(days=days)

    # market-wide: every hotel that has a city
    companies = list(
        (await db.execute(select(Company).where(Company.city.is_not(None)))).scalars().all()
    )
    cids = [c.id for c in companies]

    budgets: dict[int, PropertyBudget] = {}
    if cids:
        brows = (
            await db.execute(
                select(PropertyBudget).where(
                    PropertyBudget.company_id.in_(cids),
                    PropertyBudget.year == year,
                    PropertyBudget.month == month,
                )
            )
        ).scalars().all()
        budgets = {b.company_id: b for b in brows}

    # per-hotel budget metrics, bucketed by city
    by_city: dict[str, list[tuple]] = {}
    hotels_per_city: dict[str, int] = {}
    for c in companies:
        hotels_per_city[c.city] = hotels_per_city.get(c.city, 0) + 1
        b = budgets.get(c.id)
        if b is None:
            continue
        adr = float(c.avg_daily_rate) if c.avg_daily_rate is not None else None
        occ = float(b.occupancy_pct) if b.occupancy_pct is not None else None
        budget_amt = float(b.entertainment_budget) if b.entertainment_budget is not None else None
        if not (budget_amt and c.rooms):
            continue
        per_room = budget_amt / c.rooms
        est_rev = (c.rooms * adr * (occ / 100) * _DAYS_IN_MONTH) if (adr and occ) else None
        intensity = (budget_amt / est_rev * 100) if est_rev else None
        guests = (c.rooms * (occ / 100) * _GUESTS_PER_ROOM) if occ else None
        per_guest = (budget_amt / guests) if guests else None
        by_city.setdefault(c.city, []).append((per_room, per_guest, intensity, occ))

    # bookings + tarifa per city over the window
    booked_price = func.coalesce(
        func.sum(case((Booking.status.in_(_BOOKED), Booking.agreed_price), else_=0)), 0
    )
    booked_cnt = func.coalesce(
        func.sum(case((Booking.status.in_(_BOOKED), 1), else_=0)), 0
    )
    brows2 = (
        await db.execute(
            select(Company.city, func.count(Booking.id), booked_price, booked_cnt)
            .join(Company, Company.id == Booking.company_id)
            .where(
                Booking.created_at >= win_start,
                Booking.created_at < now_naive,
                Booking.status != BookingStatus.CANCELLED,
                Company.city.is_not(None),
            )
            .group_by(Company.city)
        )
    ).all()
    book_by_city = {city: (int(n), float(sp), int(bc)) for city, n, sp, bc in brows2}
    total_bookings = sum(n for n, _, _ in book_by_city.values())

    def _avg(rows, idx):
        vals = [r[idx] for r in rows if r[idx] is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    dests: list[DestinationStat] = []
    for city in hotels_per_city:
        rows = by_city.get(city, [])
        n_book, spend, bc = book_by_city.get(city, (0, 0.0, 0))
        dests.append(DestinationStat(
            zone=city, hotels=hotels_per_city[city],
            avg_spend_per_room=_avg(rows, 0), avg_spend_per_guest=_avg(rows, 1),
            avg_intensity_pct=_avg(rows, 2), avg_occupancy_pct=_avg(rows, 3),
            bookings=n_book, total_spend=round(spend, 2),
            avg_price=round(spend / bc, 2) if bc else None,
            share_pct=_pct(n_book, total_bookings) or 0.0,
        ))
    dests.sort(key=lambda d: d.bookings, reverse=True)

    rooms_avgs = [d.avg_spend_per_room for d in dests if d.avg_spend_per_room is not None]
    guest_avgs = [d.avg_spend_per_guest for d in dests if d.avg_spend_per_guest is not None]
    price_avgs = [d.avg_price for d in dests if d.avg_price is not None]

    return DestinationStudyOut(
        year=year, month=month, window_days=days,
        destinations_count=len(dests), hotels_count=len(companies),
        guests_per_room=_GUESTS_PER_ROOM,
        market_avg_spend_per_room=round(sum(rooms_avgs) / len(rooms_avgs), 2) if rooms_avgs else None,
        market_avg_spend_per_guest=round(sum(guest_avgs) / len(guest_avgs), 2) if guest_avgs else None,
        market_avg_price=round(sum(price_avgs) / len(price_avgs), 2) if price_avgs else None,
        total_bookings=total_bookings,
        destinations=dests,
        note=("Promedios de todos los hoteles por destino (ciudad). Metricas de "
              "presupuesto del mes; contrataciones y tarifa de la ventana. Estudio "
              "de mercado anonimo, sin comparar propiedades individuales."),
    )


@router.get(
    "/seasonality",
    response_model=SeasonalityOut,
    dependencies=[Depends(require_permission("report.view"))],
)
async def seasonality(
    db: DbSession,
    months: int = Query(default=12, ge=3, le=24),
):
    """Indicador 8 - Estacionalidad de la demanda: cuantas actuaciones (y cuanto
    gasto) tiene el mercado completo cada mes, para ver la curva del año y saber
    cuando se contrata mas. Anonimo, agregado de todos los hoteles."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # build the trailing window of `months` calendar months, oldest first
    seq: list[tuple[int, int]] = []
    y, m = now.year, now.month
    for _ in range(months):
        seq.append((y, m))
        y, m = _prev_month(y, m)
    seq.reverse()

    spend_expr = func.coalesce(
        func.sum(case((Booking.status.in_(_BOOKED), Booking.agreed_price), else_=0)), 0
    )
    out: list[SeasonMonth] = []
    for yy, mm in seq:
        start, end = _month_bounds(yy, mm)
        row = (
            await db.execute(
                select(func.count(Booking.id), spend_expr).where(
                    Booking.starts_at >= start,
                    Booking.starts_at < end,
                    Booking.status != BookingStatus.CANCELLED,
                )
            )
        ).one()
        out.append(SeasonMonth(
            year=yy, month=mm, label=f"{_MONTHS_ES[mm - 1]} {yy % 100:02d}",
            bookings=int(row[0] or 0), spend=round(float(row[1] or 0), 2),
        ))

    with_data = [s for s in out if s.bookings > 0]
    peak = max(with_data, key=lambda s: s.bookings) if with_data else None
    low = min(with_data, key=lambda s: s.bookings) if with_data else None
    return SeasonalityOut(
        months=out,
        peak_month=peak.label if peak else None,
        low_month=low.label if low else None,
        total_bookings=sum(s.bookings for s in out),
        note=("Actuaciones por mes en todo el mercado (por fecha del show). "
              "Muestra en que temporada se concentra la demanda."),
    )


@router.get(
    "/price-ranges",
    response_model=PriceRangesOut,
    dependencies=[Depends(require_permission("report.view"))],
)
async def price_ranges(
    db: DbSession,
    days: int = Query(default=180, ge=1, le=365),
):
    """Indicador 9 - Rango de precios por categoria: minimo, promedio y maximo que
    paga el mercado por cada tipo de show, para saber si una tarifa esta cara o
    barata. Anonimo, agregado de todas las contrataciones con precio."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    win_start = now - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                Show.category,
                func.count(Booking.id),
                func.min(Booking.agreed_price),
                func.avg(Booking.agreed_price),
                func.max(Booking.agreed_price),
            )
            .join(Show, Show.id == Booking.show_id)
            .where(
                Booking.created_at >= win_start,
                Booking.created_at < now,
                Booking.status.in_(_BOOKED),
                Booking.agreed_price.is_not(None),
                Show.category.is_not(None),
            )
            .group_by(Show.category)
        )
    ).all()

    cats = [
        PriceRange(
            category=cat, bookings=int(n or 0),
            min_price=round(float(mn), 2) if mn is not None else None,
            avg_price=round(float(av), 2) if av is not None else None,
            max_price=round(float(mx), 2) if mx is not None else None,
        )
        for cat, n, mn, av, mx in rows
    ]
    cats.sort(key=lambda c: c.avg_price or 0, reverse=True)
    return PriceRangesOut(
        window_days=days,
        categories=cats,
        note=("Precios de contratacion por categoria en la ventana. Minimo, "
              "promedio y maximo del mercado."),
    )
