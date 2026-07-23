"""Master console endpoints (admin-only): Administración + Contaduría.

Feeds David's Master console:

  Administración → Talentos, Empresas asociadas, Eventos / Shows (lists with
                   server-side filters + info pop-ups).
  Contaduría     → Facturación Ingresos (facturas emitidas a clientes),
                   Facturación Egresos (recibos de talento) y Pagos y depósitos
                   (conciliación).

Everything is derived from the real artists / companies / bookings. The only
persisted state added for this module is the reconciliation flag on each
booking: `invoice_paid` (cobrado al cliente) and `payout_paid` (pagado al
talento). Recibo numbers are derived deterministically from the booking id so
they stay stable across reloads without a separate invoice table (first stage —
"todo en pantalla", David 2026-07-22).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentScope, DbSession
from app.models.artist import Artist
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.media import ArtistDocument
from app.models.show import Show
from app.models.tax_figure import TaxFigure
from app.models.venue import Venue

router = APIRouter(prefix="/admin", tags=["admin"])

# Tasas base (configurables desde el Dashboard ejecutivo / reports.py).
DEFAULT_COMMISSION = 0.15   # comisión SHOWMA sobre el bruto contratado
IVA_RATE = 0.16             # IVA México

_BOOKED = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED)
_ACTIVE = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED, BookingStatus.PENDING)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _admin_only(scope) -> None:
    if not scope.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el administrador puede acceder al panel Master.",
        )


def _naive(dt: datetime | None) -> datetime | None:
    """SQLite stores DATETIME naive; normalise so arithmetic never mixes tz."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _days_since(dt: datetime | None) -> int | None:
    dt = _naive(dt)
    if dt is None:
        return None
    return (datetime.utcnow() - dt).days


def _mask(acct: str | None) -> str | None:
    """Número de cuenta enmascarado (solo últimos 4)."""
    if not acct:
        return None
    s = str(acct)
    return "•••• " + s[-4:] if len(s) > 4 else s


def _commission(b: Booking) -> float:
    if b.commission_pct is not None:
        return float(b.commission_pct) / 100.0
    return DEFAULT_COMMISSION


def _recibo(prefix: str, b: Booking) -> str:
    dt = _naive(b.starts_at) or _naive(b.created_at) or datetime.utcnow()
    return f"{prefix}-{dt.year}{dt.month:02d}-{b.id:04d}"


# --------------------------------------------------------------------------- #
# ADMINISTRACIÓN · Talentos
# --------------------------------------------------------------------------- #
@router.get("/talents")
async def list_talents(
    scope: CurrentScope,
    db: DbSession,
    q: str | None = Query(default=None),
    city: str | None = Query(default=None),
    estatus: str | None = Query(default=None),        # active / inactive
    regimen: str | None = Query(default=None),
    disponible: str | None = Query(default=None),      # si / no
    fac_min: float | None = Query(default=None),
    fac_max: float | None = Query(default=None),
):
    _admin_only(scope)

    # Rango de facturación + nº de actuaciones por talento (una sola pasada).
    tot_rows = (await db.execute(
        select(Booking.artist_id, func.coalesce(func.sum(Booking.agreed_price), 0))
        .where(Booking.status.in_(_BOOKED)).group_by(Booking.artist_id)
    )).all()
    totals = {aid: float(t) for aid, t in tot_rows if aid}
    cnt_rows = (await db.execute(
        select(Booking.artist_id, func.count())
        .where(Booking.status != BookingStatus.CANCELLED).group_by(Booking.artist_id)
    )).all()
    counts = {aid: int(c) for aid, c in cnt_rows if aid}
    # Constancia de situación fiscal (SAT) por talento.
    doc_rows = (await db.execute(
        select(ArtistDocument.artist_id, ArtistDocument.url)
        .where(ArtistDocument.doc_type == "constancia_sat")
    )).all()
    constancia = {aid: url for aid, url in doc_rows}

    stmt = select(Artist)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Artist.stage_name.ilike(like), Artist.email.ilike(like),
                              Artist.first_name.ilike(like), Artist.last_name.ilike(like)))
    if city:
        like = f"%{city}%"
        stmt = stmt.where(or_(Artist.city.ilike(like), Artist.region.ilike(like),
                              Artist.country.ilike(like)))
    if estatus in ("active", "inactive"):
        stmt = stmt.where(Artist.is_active.is_(estatus == "active"))
    if regimen:
        stmt = stmt.where(Artist.tax_regime.ilike(f"%{regimen}%"))
    if disponible in ("si", "no"):
        stmt = stmt.where(Artist.available_to_travel.is_(disponible == "si"))
    stmt = stmt.order_by(Artist.created_at.desc())
    artists = (await db.execute(stmt)).scalars().all()

    out = []
    for a in artists:
        fac = round(totals.get(a.id, 0.0), 2)
        if fac_min is not None and fac < fac_min:
            continue
        if fac_max is not None and fac > fac_max:
            continue
        ubic = " / ".join([p for p in (a.city, a.region, a.country) if p]) or None
        out.append({
            "id": a.id,
            "nombre": a.stage_name,
            "tipo": a.artist_type,
            "fecha_ingreso": (a.created_at.isoformat() if a.created_at else None),
            "ubicacion": ubic,
            "ciudad": a.city, "estado": a.region, "pais": a.country,
            "estatus": "Activo" if a.is_active else "Inactivo",
            "activo": bool(a.is_active),
            "regimen_fiscal": a.tax_regime,
            "facturacion": fac,
            "actuaciones": counts.get(a.id, 0),
            "disponible": bool(a.available_to_travel),
            # Pop-up financiero
            "financiero": {
                "banco": a.bank_name,
                "clabe": a.bank_clabe,
                "cuenta": _mask(a.bank_account),
                "rfc": a.rfc,
                "regimen_fiscal": a.tax_regime,
                "constancia_url": constancia.get(a.id),
                "beneficiario": a.bank_account_holder or a.legal_name,
                "moneda": a.preferred_currency,
                "retencion_isr": None,       # configurable por talento (pendiente)
                "retencion_iva": None,
            },
            # Pop-up perfil
            "perfil": {
                "telefono": a.phone,
                "whatsapp": a.phone,
                "correo": a.email,
                "direccion": ubic,
                "web": a.website,
                "contacto_emergencia": None,
            },
        })
    # Regímenes disponibles para poblar el filtro.
    regimenes = sorted({a.tax_regime for a in artists if a.tax_regime})
    return {"total": len(out), "items": out, "regimenes": regimenes}


# --------------------------------------------------------------------------- #
# ADMINISTRACIÓN · Empresas asociadas
# --------------------------------------------------------------------------- #
@router.get("/companies")
async def list_companies(
    scope: CurrentScope,
    db: DbSession,
    q: str | None = Query(default=None),
    tipo: str | None = Query(default=None),
    city: str | None = Query(default=None),
    estatus: str | None = Query(default=None),        # activo / prospecto
    estrellas: int | None = Query(default=None, ge=1, le=5),
):
    _admin_only(scope)

    # ¿Tiene actuaciones? -> Activo; si no, Prospecto.
    booked_rows = (await db.execute(
        select(Booking.company_id, func.count())
        .where(Booking.status.in_(_BOOKED)).group_by(Booking.company_id)
    )).all()
    booked = {cid: int(c) for cid, c in booked_rows if cid}

    stmt = select(Company)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Company.name.ilike(like), Company.legal_name.ilike(like),
                              Company.contact_person.ilike(like)))
    if tipo:
        stmt = stmt.where(Company.company_type.ilike(f"%{tipo}%"))
    if city:
        like = f"%{city}%"
        stmt = stmt.where(or_(Company.city.ilike(like), Company.region.ilike(like)))
    if estrellas:
        stmt = stmt.where(Company.star_rating == estrellas)
    stmt = stmt.order_by(Company.created_at.desc())
    companies = (await db.execute(stmt)).scalars().all()

    out = []
    for c in companies:
        activo = c.id in booked
        est = "Activo" if activo else "Prospecto"
        if estatus in ("activo", "prospecto") and estatus != est.lower():
            continue
        ubic = " / ".join([p for p in (c.city, c.region) if p]) or None
        dir_fiscal = ", ".join([p for p in (c.address, c.city, c.region, c.postal_code) if p]) or None
        out.append({
            "id": c.id,
            "nombre": c.name,
            "tipo": c.company_type,
            "fecha_alta": (c.created_at.isoformat() if c.created_at else None),
            "ubicacion": ubic,
            "ciudad": c.city, "estado": c.region,
            "categoria": c.star_rating,          # categoría hotelera (estrellas)
            "ejecutivo": None,                   # ejecutivo comercial asignado (pendiente)
            "estatus": est,
            "tarifa_promedio": (float(c.avg_daily_rate) if c.avg_daily_rate is not None else None),
            "habitaciones": c.rooms,
            "financiero": {
                "rfc": c.tax_id,
                "regimen_fiscal": c.tax_regime,
                "uso_cfdi": c.cfdi_use,
                "metodo_pago": None,             # (pendiente en el alta)
                "forma_pago": None,
                "credito_autorizado": None,
                "dias_credito": c.agreed_payment_days,
                "moneda": "MXN",
                "direccion_fiscal": dir_fiscal,
                "constancia_url": None,
            },
            "contacto": {
                "nombre": c.contact_person,
                "cargo": None,
                "telefono": c.contact_phone,
                "whatsapp": c.whatsapp,
                "correo": c.contact_email,
                "direccion": dir_fiscal,
                "notas": None,
            },
        })
    tipos = sorted({c.company_type for c in companies if c.company_type})
    return {"total": len(out), "items": out, "tipos": tipos}


# --------------------------------------------------------------------------- #
# ADMINISTRACIÓN · Eventos / Shows (actuaciones)
# --------------------------------------------------------------------------- #
_ESTATUS_ES = {
    BookingStatus.PENDING: "Pendiente",
    BookingStatus.CONFIRMED: "Confirmado",
    BookingStatus.COMPLETED: "Realizado",
    BookingStatus.CANCELLED: "Cancelado",
    BookingStatus.NO_SHOW: "No show",
}


@router.get("/events")
async def list_events(
    scope: CurrentScope,
    db: DbSession,
    q: str | None = Query(default=None),
    desde: str | None = Query(default=None),           # YYYY-MM-DD
    hasta: str | None = Query(default=None),
    tipo: str | None = Query(default=None),
    estatus: str | None = Query(default=None),
    city: str | None = Query(default=None),
):
    _admin_only(scope)

    stmt = (
        select(Booking, Artist.stage_name, Company.name, Company.city,
               Show.show_name, Venue.name)
        .outerjoin(Artist, Artist.id == Booking.artist_id)
        .outerjoin(Company, Company.id == Booking.company_id)
        .outerjoin(Show, Show.id == Booking.show_id)
        .outerjoin(Venue, Venue.id == Booking.venue_id)
    )
    if desde:
        try:
            stmt = stmt.where(Booking.starts_at >= datetime.fromisoformat(desde))
        except ValueError:
            pass
    if hasta:
        try:
            end = datetime.fromisoformat(hasta)
            end = end.replace(hour=23, minute=59, second=59)
            stmt = stmt.where(Booking.starts_at <= end)
        except ValueError:
            pass
    if tipo:
        stmt = stmt.where(Booking.event_type.ilike(f"%{tipo}%"))
    if estatus:
        try:
            stmt = stmt.where(Booking.status == BookingStatus(estatus))
        except ValueError:
            pass
    if city:
        stmt = stmt.where(Company.city.ilike(f"%{city}%"))
    stmt = stmt.order_by(Booking.starts_at.desc())
    rows = (await db.execute(stmt)).all()

    out = []
    for b, artist_name, company_name, company_city, show_title, venue_name in rows:
        if q:
            hay = " ".join(str(x or "") for x in (artist_name, company_name, show_title, venue_name)).lower()
            if q.lower() not in hay:
                continue
        out.append({
            "id": b.id,
            "fecha": (b.starts_at.isoformat() if b.starts_at else None),
            "talento": artist_name or "—",
            "show": show_title,
            "contratante": company_name or "—",
            "ciudad": company_city,
            "venue": venue_name,
            "tipo": b.event_type or "—",
            "estatus": _ESTATUS_ES.get(b.status, str(b.status)),
            "estatus_key": b.status.value if hasattr(b.status, "value") else str(b.status),
            "monto": (float(b.agreed_price) if b.agreed_price is not None else 0.0),
            "moneda": b.currency,
            "ejecutivo": None,
        })
    tipos = sorted({r[0].event_type for r in rows if r[0].event_type})
    return {"total": len(out), "items": out, "tipos": tipos}


# --------------------------------------------------------------------------- #
# CONTADURÍA · Facturación Ingresos (facturas emitidas a clientes)
# --------------------------------------------------------------------------- #
async def _billable(db, extra=None):
    """Bookings que generan factura: confirmadas o realizadas."""
    stmt = (
        select(Booking, Artist.stage_name, Company.name)
        .outerjoin(Artist, Artist.id == Booking.artist_id)
        .outerjoin(Company, Company.id == Booking.company_id)
        .where(Booking.status.in_(_BOOKED))
        .order_by(Booking.starts_at.desc())
    )
    if extra is not None:
        stmt = stmt.where(extra)
    return (await db.execute(stmt)).all()


@router.get("/contaduria/ingresos")
async def contaduria_ingresos(
    scope: CurrentScope,
    db: DbSession,
    q: str | None = Query(default=None),
    estado: str | None = Query(default=None),          # pagada / impagada
):
    _admin_only(scope)
    rows = await _billable(db)
    out = []
    for b, artist_name, company_name in rows:
        monto = float(b.agreed_price or 0)
        iva = round(monto * IVA_RATE, 2)
        pagada = bool(getattr(b, "invoice_paid", False))
        if estado == "pagada" and not pagada:
            continue
        if estado == "impagada" and pagada:
            continue
        if q and q.lower() not in (company_name or "").lower() and q.lower() not in _recibo("F", b).lower():
            continue
        out.append({
            "id": b.id,
            "recibo": _recibo("F", b),
            "fecha": (b.starts_at.isoformat() if b.starts_at else None),
            "dias": _days_since(b.starts_at),
            "cliente": company_name or "—",
            "metodo_pago": "Transferencia electrónica de fondos",
            "monto": round(monto, 2),
            "iva": iva,
            "total": round(monto + iva, 2),
            "moneda": b.currency,
            "pagada": pagada,
        })
    total = round(sum(r["monto"] for r in out), 2)
    pend = round(sum(r["monto"] for r in out if not r["pagada"]), 2)
    return {"total": len(out), "items": out, "suma": total, "pendiente": pend}


# --------------------------------------------------------------------------- #
# CONTADURÍA · Facturación Egresos (recibos de talento)
# --------------------------------------------------------------------------- #
@router.get("/contaduria/egresos")
async def contaduria_egresos(
    scope: CurrentScope,
    db: DbSession,
    q: str | None = Query(default=None),
    estado: str | None = Query(default=None),
):
    _admin_only(scope)
    rows = await _billable(db)
    out = []
    for b, artist_name, company_name in rows:
        bruto = float(b.agreed_price or 0)
        pago = round(bruto * (1 - _commission(b)), 2)     # neto al talento
        pagada = bool(getattr(b, "payout_paid", False))
        if estado == "pagada" and not pagada:
            continue
        if estado == "impagada" and pagada:
            continue
        if q and q.lower() not in (artist_name or "").lower() and q.lower() not in _recibo("R", b).lower():
            continue
        out.append({
            "id": b.id,
            "recibo": _recibo("R", b),
            "fecha": (b.starts_at.isoformat() if b.starts_at else None),
            "dias": _days_since(b.starts_at),
            "talento": artist_name or "—",
            "monto": pago,
            "moneda": b.currency,
            "pagada": pagada,
        })
    total = round(sum(r["monto"] for r in out), 2)
    pend = round(sum(r["monto"] for r in out if not r["pagada"]), 2)
    return {"total": len(out), "items": out, "suma": total, "pendiente": pend}


# --------------------------------------------------------------------------- #
# CONTADURÍA · Pagos y depósitos (conciliación)
# --------------------------------------------------------------------------- #
@router.get("/contaduria/pagos")
async def contaduria_pagos(
    scope: CurrentScope,
    db: DbSession,
    q: str | None = Query(default=None),
    conciliado: str | None = Query(default=None),      # si / no
):
    _admin_only(scope)
    rows = await _billable(db)
    out = []
    for b, artist_name, company_name in rows:
        bruto = float(b.agreed_price or 0)
        # Depósito del cliente (ingreso)
        out.append({
            "booking_id": b.id, "kind": "ingreso",
            "fecha": (b.starts_at.isoformat() if b.starts_at else None),
            "cuenta": "Cuenta SHOWMA · Transferencia",
            "contraparte": company_name or "—",
            "tipo": "Depósito de cliente",
            "referencia": _recibo("F", b),
            "monto": round(bruto * (1 + IVA_RATE), 2),
            "moneda": b.currency,
            "conciliado": bool(getattr(b, "invoice_paid", False)),
        })
        # Pago al talento (egreso)
        out.append({
            "booking_id": b.id, "kind": "egreso",
            "fecha": (b.starts_at.isoformat() if b.starts_at else None),
            "cuenta": (artist_name or "Talento") + " · Transferencia",
            "contraparte": artist_name or "—",
            "tipo": "Pago a proveedor",
            "referencia": _recibo("R", b),
            "monto": round(bruto * (1 - _commission(b)), 2),
            "moneda": b.currency,
            "conciliado": bool(getattr(b, "payout_paid", False)),
        })
    if conciliado in ("si", "no"):
        want = conciliado == "si"
        out = [r for r in out if r["conciliado"] is want]
    if q:
        ql = q.lower()
        out = [r for r in out if ql in (r["contraparte"] or "").lower() or ql in r["referencia"].lower()]
    out.sort(key=lambda r: (r["fecha"] or ""), reverse=True)
    pendientes = sum(1 for r in out if not r["conciliado"])
    return {"total": len(out), "items": out, "pendientes": pendientes}


# --------------------------------------------------------------------------- #
# CONTADURÍA · marcar pagada / conciliada
# --------------------------------------------------------------------------- #
@router.patch("/contaduria/{kind}/{booking_id}")
async def mark_paid(
    kind: str,
    booking_id: int,
    scope: CurrentScope,
    db: DbSession,
    paid: bool = Body(embed=True),
):
    _admin_only(scope)
    if kind not in ("ingreso", "egreso"):
        raise HTTPException(status_code=400, detail="Tipo inválido (ingreso/egreso).")
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Actuación no encontrada.")
    if kind == "ingreso":
        booking.invoice_paid = paid
    else:
        booking.payout_paid = paid
    await db.commit()
    return {"ok": True, "booking_id": booking_id, "kind": kind, "paid": paid}


# --------------------------------------------------------------------------- #
# CONFIGURACIÓN · Impuestos (figuras fiscales) — catálogo editable
# --------------------------------------------------------------------------- #
def _tax_out(t) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "commission_pct": float(t.commission_pct or 0),
        "isr_ret_pct": float(t.isr_ret_pct or 0),
        "iva_ret_pct": float(t.iva_ret_pct or 0),
        "notes": t.notes,
        "is_default": bool(t.is_default),
        "active": bool(t.active),
    }


def _pct(v) -> float:
    """Normaliza un porcentaje: acepta 16 o '16' → 16.0, acota a 0–100."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        f = 0.0
    return max(0.0, min(100.0, round(f, 4)))


@router.get("/config/taxes")
async def taxes_list(scope: CurrentScope, db: DbSession):
    _admin_only(scope)
    rows = (
        await db.execute(select(TaxFigure).order_by(TaxFigure.is_default.desc(), TaxFigure.name))
    ).scalars().all()
    return {"items": [_tax_out(t) for t in rows]}


@router.post("/config/taxes")
async def taxes_create(
    scope: CurrentScope,
    db: DbSession,
    name: str = Body(...),
    commission_pct: float = Body(default=0.0),
    isr_ret_pct: float = Body(default=0.0),
    iva_ret_pct: float = Body(default=0.0),
    notes: str | None = Body(default=None),
    is_default: bool = Body(default=False),
):
    _admin_only(scope)
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre de la figura fiscal es obligatorio.")
    if is_default:  # solo una figura por defecto
        for t in (await db.execute(select(TaxFigure).where(TaxFigure.is_default.is_(True)))).scalars().all():
            t.is_default = False
    fig = TaxFigure(
        name=name,
        commission_pct=_pct(commission_pct),
        isr_ret_pct=_pct(isr_ret_pct),
        iva_ret_pct=_pct(iva_ret_pct),
        notes=(notes or None),
        is_default=is_default,
        active=True,
    )
    db.add(fig)
    await db.commit()
    await db.refresh(fig)
    return _tax_out(fig)


@router.patch("/config/taxes/{tax_id}")
async def taxes_update(
    tax_id: int,
    scope: CurrentScope,
    db: DbSession,
    payload: dict = Body(...),
):
    _admin_only(scope)
    fig = await db.get(TaxFigure, tax_id)
    if not fig:
        raise HTTPException(status_code=404, detail="Figura fiscal no encontrada.")
    if "name" in payload:
        nm = (payload["name"] or "").strip()
        if not nm:
            raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío.")
        fig.name = nm
    if "commission_pct" in payload:
        fig.commission_pct = _pct(payload["commission_pct"])
    if "isr_ret_pct" in payload:
        fig.isr_ret_pct = _pct(payload["isr_ret_pct"])
    if "iva_ret_pct" in payload:
        fig.iva_ret_pct = _pct(payload["iva_ret_pct"])
    if "notes" in payload:
        fig.notes = (payload["notes"] or None)
    if "active" in payload:
        fig.active = bool(payload["active"])
    if payload.get("is_default"):
        for t in (await db.execute(select(TaxFigure).where(TaxFigure.is_default.is_(True)))).scalars().all():
            t.is_default = False
        fig.is_default = True
    elif "is_default" in payload:
        fig.is_default = False
    await db.commit()
    await db.refresh(fig)
    return _tax_out(fig)


@router.delete("/config/taxes/{tax_id}")
async def taxes_delete(tax_id: int, scope: CurrentScope, db: DbSession):
    _admin_only(scope)
    fig = await db.get(TaxFigure, tax_id)
    if not fig:
        raise HTTPException(status_code=404, detail="Figura fiscal no encontrada.")
    await db.delete(fig)
    await db.commit()
    return {"ok": True, "id": tax_id}
