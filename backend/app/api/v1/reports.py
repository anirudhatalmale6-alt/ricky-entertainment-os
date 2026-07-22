"""Executive / Master reports (admin-only).

Feeds the Master → Dashboard screen: the month KPIs (ingresos, contrataciones,
talentos, empresas, facturas), a 6-month ingresos/egresos series, the income
distribution by concept, the top talents and top companies, and a contable
summary. Everything is derived from the real bookings/companies/artists; the
tax figures (comision, IVA, ISR) use standard Mexican rates as a base and are
returned in `rates` so the UI can show them as configurable.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentScope, DbSession
from app.models.artist import Artist
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.show import Show

router = APIRouter(prefix="/reports", tags=["reports"])

_BOOKED = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED)
_MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
              "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

# Base assumptions — configurables. Returned in the payload so the UI shows them.
DEFAULT_COMMISSION = 0.15   # comisión promedio de SHOWMA sobre el bruto contratado
IVA_RATE = 0.16             # IVA México
ISR_RATE = 0.30             # ISR estimado sobre la utilidad


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _delta(cur: float, prev: float) -> float | None:
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


async def _sum_ingresos(db, start, end) -> float:
    res = await db.execute(
        select(func.coalesce(func.sum(Booking.agreed_price), 0)).where(
            Booking.status.in_(_BOOKED),
            Booking.starts_at >= start,
            Booking.starts_at < end,
        )
    )
    return float(res.scalar_one() or 0)


async def _count_contrataciones(db, start, end) -> int:
    res = await db.execute(
        select(func.count()).select_from(Booking).where(
            Booking.status != BookingStatus.CANCELLED,
            Booking.starts_at >= start,
            Booking.starts_at < end,
        )
    )
    return int(res.scalar_one() or 0)


async def _count_facturas(db, start, end) -> int:
    """Una actuación completada = una factura emitida."""
    res = await db.execute(
        select(func.count()).select_from(Booking).where(
            Booking.status == BookingStatus.COMPLETED,
            Booking.starts_at >= start,
            Booking.starts_at < end,
        )
    )
    return int(res.scalar_one() or 0)


@router.get("/executive")
async def executive_dashboard(
    scope: CurrentScope,
    db: DbSession,
    year: int | None = Query(default=None),
    month: int | None = Query(default=None, ge=1, le=12),
):
    if not scope.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el administrador puede ver el panel ejecutivo.",
        )

    # Default period = most recent month that has activity, else today's month.
    if not (year and month):
        res = await db.execute(select(func.max(Booking.starts_at)))
        latest = res.scalar_one_or_none()
        ref = latest or datetime.utcnow()
        year, month = ref.year, ref.month

    start, end = _month_bounds(year, month)
    py, pm = _prev_month(year, month)
    pstart, pend = _month_bounds(py, pm)

    # ---- KPIs (mes actual vs mes anterior) ----
    ingresos = await _sum_ingresos(db, start, end)
    ingresos_prev = await _sum_ingresos(db, pstart, pend)
    contrat = await _count_contrataciones(db, start, end)
    contrat_prev = await _count_contrataciones(db, pstart, pend)
    facturas = await _count_facturas(db, start, end)
    facturas_prev = await _count_facturas(db, pstart, pend)

    talentos = int((await db.execute(select(func.count()).select_from(Artist))).scalar_one() or 0)
    empresas = int((await db.execute(select(func.count()).select_from(Company))).scalar_one() or 0)

    # ---- Serie 6 meses (ingresos / egresos) ----
    series = []
    sy, sm = year, month
    trail = []
    for _ in range(6):
        trail.append((sy, sm))
        sy, sm = _prev_month(sy, sm)
    for (yy, mm) in reversed(trail):
        s, e = _month_bounds(yy, mm)
        ing = await _sum_ingresos(db, s, e)
        egr = round(ing * (1 - DEFAULT_COMMISSION), 2)   # pagos a talento
        series.append({"label": _MONTHS_ES[mm - 1], "year": yy,
                       "ingresos": round(ing, 2), "egresos": egr})

    # ---- Distribución de ingresos por concepto (categoría del show) ----
    dist_rows = (await db.execute(
        select(Show.category, func.coalesce(func.sum(Booking.agreed_price), 0))
        .join(Show, Show.id == Booking.show_id)
        .where(Booking.status.in_(_BOOKED),
               Booking.starts_at >= start, Booking.starts_at < end)
        .group_by(Show.category)
    )).all()
    dist_total = sum(float(t) for _, t in dist_rows) or 0
    distribucion = sorted(
        [{"concepto": (c or "otros"), "monto": round(float(t), 2),
          "pct": round(float(t) / dist_total * 100, 1) if dist_total else 0}
         for c, t in dist_rows if float(t) > 0],
        key=lambda x: x["monto"], reverse=True,
    )

    # ---- Top músicos por ingresos ----
    top_mus_rows = (await db.execute(
        select(Artist.stage_name, func.coalesce(func.sum(Booking.agreed_price), 0))
        .join(Artist, Artist.id == Booking.artist_id)
        .where(Booking.status.in_(_BOOKED),
               Booking.starts_at >= start, Booking.starts_at < end)
        .group_by(Artist.id, Artist.stage_name)
        .order_by(func.sum(Booking.agreed_price).desc())
        .limit(5)
    )).all()
    top_musicos = [{"name": n or "—", "monto": round(float(t), 2)} for n, t in top_mus_rows]

    # ---- Top empresas por facturación ----
    top_emp_rows = (await db.execute(
        select(Company.name, func.coalesce(func.sum(Booking.agreed_price), 0))
        .join(Company, Company.id == Booking.company_id)
        .where(Booking.status.in_(_BOOKED),
               Booking.starts_at >= start, Booking.starts_at < end)
        .group_by(Company.id, Company.name)
        .order_by(func.sum(Booking.agreed_price).desc())
        .limit(5)
    )).all()
    top_empresas = [{"name": n or "—", "monto": round(float(t), 2)} for n, t in top_emp_rows]

    # ---- Resumen contable (estimado, tasas configurables) ----
    egresos = round(ingresos * (1 - DEFAULT_COMMISSION), 2)     # pagos a talento
    utilidad = round(ingresos - egresos, 2)                     # comisión SHOWMA
    margen = round(utilidad / ingresos * 100, 1) if ingresos else 0
    iva = round(utilidad * IVA_RATE, 2)
    isr = round(utilidad * ISR_RATE, 2)

    # ---- Cobros y depósitos ----
    por_cobrar = float((await db.execute(
        select(func.coalesce(func.sum(Booking.agreed_price), 0)).where(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.starts_at >= start, Booking.starts_at < end)
    )).scalar_one() or 0)
    depositado = float((await db.execute(
        select(func.coalesce(func.sum(Booking.agreed_price), 0)).where(
            Booking.status == BookingStatus.COMPLETED,
            Booking.starts_at >= start, Booking.starts_at < end)
    )).scalar_one() or 0)

    return {
        "period": {"year": year, "month": month, "label": f"{_MONTHS_ES[month - 1]} {year}"},
        "kpis": {
            "ingresos": {"value": round(ingresos, 2), "delta": _delta(ingresos, ingresos_prev)},
            "contrataciones": {"value": contrat, "delta": _delta(contrat, contrat_prev)},
            "talentos": {"value": talentos},
            "empresas": {"value": empresas},
            "facturas": {"value": facturas, "delta": _delta(facturas, facturas_prev)},
        },
        "series": series,
        "distribucion": distribucion,
        "top_musicos": top_musicos,
        "top_empresas": top_empresas,
        "contable": {
            "ingresos": round(ingresos, 2), "egresos": egresos,
            "utilidad": utilidad, "margen": margen, "iva": iva, "isr": isr,
        },
        "cobros": {"por_cobrar": round(por_cobrar, 2), "depositado": round(depositado, 2)},
        "rates": {"comision": DEFAULT_COMMISSION, "iva": IVA_RATE, "isr": ISR_RATE},
    }
