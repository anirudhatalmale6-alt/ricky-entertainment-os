"""Lógica de facturación: arma el CFDI de una actuación y lo timbra.

Este módulo es el puente entre el negocio de SHOWMA y el cliente de Facturama.
El desglose que calcula aquí es EL MISMO que muestra la pantalla de Facturación
(ver /me/payouts): honorarios − comisión = base CFDI; sobre la base, IVA
trasladado (+) y retenciones de IVA e ISR (−). Así el CFDI timbrado coincide
peso por peso con lo que ve el músico.

El timbrado es automático: cuando una actuación pasa a "realizada" (COMPLETED),
`issue_cfdi_for_booking` construye el comprobante a nombre del músico (su RFC/CSD)
y lo manda a Facturama. El músico no hace nada manual.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artist import Artist
from app.models.booking import Booking
from app.models.cfdi import Cfdi
from app.models.company import Company
from app.models.show import Show
from app.models.tax_figure import TaxFigure
from app.services.facturama import FacturamaError, get_facturama

logger = logging.getLogger("showma.facturacion")

_DEFAULT_COMMISSION_PCT = 3.7
# Clave de producto/servicio SAT: "Servicios de entretenimiento" (espectáculos).
_SAT_PROD_CODE = "90101800"


def _round2(x: float) -> float:
    return round(float(x or 0), 2)


def compute_desglose(honorarios: float, figura: TaxFigure | None) -> dict:
    """Desglose fiscal de un importe de honorarios, idéntico a /me/payouts."""
    com_pct = float(getattr(figura, "commission_pct", 0) or 0) if figura else 0.0
    if not com_pct:
        com_pct = _DEFAULT_COMMISSION_PCT
    iva_pct = float(figura.iva_traslado_pct) if figura and figura.iva_traslado_pct is not None else 16.0
    riva_pct = float(getattr(figura, "iva_ret_pct", 0) or 0) if figura else 0.0
    risr_pct = float(getattr(figura, "isr_ret_pct", 0) or 0) if figura else 0.0

    honorarios = _round2(honorarios)
    comision = _round2(honorarios * com_pct / 100.0)
    base_cfdi = _round2(honorarios - comision)
    iva = _round2(base_cfdi * iva_pct / 100.0)
    ret_iva = _round2(base_cfdi * riva_pct / 100.0)
    ret_isr = _round2(base_cfdi * risr_pct / 100.0)
    total = _round2(base_cfdi + iva - ret_iva - ret_isr)
    return {
        "com_pct": com_pct, "comision": comision,
        "base_cfdi": base_cfdi,
        "iva_pct": iva_pct, "iva": iva,
        "riva_pct": riva_pct, "ret_iva": ret_iva,
        "risr_pct": risr_pct, "ret_isr": ret_isr,
        "total": total,
    }


class FiscalDataMissing(FacturamaError):
    """Faltan datos fiscales (del músico o del hotel) para poder timbrar."""


def _require(value, label: str) -> str:
    v = (value or "").strip() if isinstance(value, str) else value
    if not v:
        raise FiscalDataMissing(f"Falta {label} para poder emitir el CFDI.")
    return v


def _sat_code(value: str) -> str:
    """Extrae la clave SAT del inicio de un texto de catálogo.

    Los selectores del frontend guardan valores como "612 - Personas Físicas…"
    o "G03 · Gastos en general"; Facturama sólo quiere la clave ("612", "G03").
    """
    token = str(value or "").strip().split()[0] if value else ""
    return token.strip(" -·")


def build_cfdi_payload(
    booking: Booking,
    artist: Artist,
    company: Company,
    figura: TaxFigure | None,
    show: Show | None,
    folio: str | int,
) -> dict:
    """Construye el JSON del CFDI 4.0 (Multiemisor) para una actuación."""
    d = compute_desglose(float(booking.agreed_price or 0), figura)
    base = d["base_cfdi"]

    issuer_rfc = _require(artist.rfc, "el RFC del músico")
    issuer_regime = _sat_code(_require(artist.tax_regime, "el régimen fiscal del músico"))
    receiver_rfc = _require(company.tax_id, "el RFC del hotel")
    receiver_regime = _sat_code(_require(company.tax_regime, "el régimen fiscal del hotel"))
    receiver_cp = _require(company.postal_code, "el código postal fiscal del hotel")
    receiver_use = _sat_code(company.cfdi_use) or "G03"

    taxes = [
        {
            "Name": "IVA", "Base": base, "Rate": round(d["iva_pct"] / 100.0, 6),
            "Total": d["iva"], "IsRetention": False,
        }
    ]
    if d["ret_iva"] > 0:
        taxes.append({
            "Name": "IVA", "Base": base, "Rate": round(d["riva_pct"] / 100.0, 6),
            "Total": d["ret_iva"], "IsRetention": True,
        })
    if d["ret_isr"] > 0:
        taxes.append({
            "Name": "ISR", "Base": base, "Rate": round(d["risr_pct"] / 100.0, 6),
            "Total": d["ret_isr"], "IsRetention": True,
        })
    item_total = _round2(base + d["iva"] - d["ret_iva"] - d["ret_isr"])

    desc = "Servicio de espectáculo / entretenimiento en vivo"
    if show and getattr(show, "show_name", None):
        desc = f"Espectáculo: {show.show_name}"

    return {
        "NameId": "1",
        "Currency": booking.currency or "MXN",
        "Folio": str(folio),
        "Serie": "SHOWMA",
        "CfdiType": "I",
        "PaymentForm": "03",       # transferencia electrónica
        "PaymentMethod": "PUE",    # pago en una exhibición
        "ExpeditionPlace": _require(artist.fiscal_postal_code, "el código postal fiscal del músico"),
        "Exportation": "01",       # no aplica exportación
        "Issuer": {
            "Rfc": issuer_rfc.upper(),
            "Name": _require(artist.legal_name or artist.stage_name, "la razón social del músico"),
            "FiscalRegime": issuer_regime,
        },
        "Receiver": {
            "Rfc": receiver_rfc.upper(),
            "Name": _require(company.legal_name or company.name, "la razón social del hotel"),
            "CfdiUse": receiver_use,
            "FiscalRegime": receiver_regime,
            "TaxZipCode": receiver_cp,
        },
        "Items": [
            {
                "ProductCode": _SAT_PROD_CODE,
                "IdentificationNumber": f"SHOW-{booking.id}",
                "Description": desc,
                "Unit": "Servicio",
                "UnitCode": "E48",
                "UnitPrice": base,
                "Quantity": 1.0,
                "Subtotal": base,
                "TaxObject": "02",
                "Taxes": taxes,
                "Total": item_total,
            }
        ],
    }


async def _load_figura(db: AsyncSession, artist: Artist) -> TaxFigure | None:
    figuras = (await db.execute(select(TaxFigure))).scalars().all()
    by_id = {f.id: f for f in figuras}
    default_fig = next((f for f in figuras if f.is_default), (figuras[0] if figuras else None))
    return by_id.get(artist.tax_figure_id) if artist.tax_figure_id else default_fig


async def issue_cfdi_for_booking(db: AsyncSession, booking: Booking, *, force: bool = False) -> Cfdi:
    """Timbra el CFDI de una actuación y guarda el resultado.

    Idempotente: si ya hay un CFDI timbrado para esta actuación lo devuelve tal
    cual (salvo `force`). Un fallo NO rompe el flujo del que llama: se guarda un
    Cfdi con status="error" y el motivo, y se devuelve ese registro.
    """
    # ¿Ya existe un CFDI para esta actuación?
    existing = (
        await db.execute(select(Cfdi).where(Cfdi.booking_id == booking.id))
    ).scalar_one_or_none()
    if existing and existing.status == "stamped" and not force:
        return existing

    artist = await db.get(Artist, booking.artist_id) if booking.artist_id else None
    company = await db.get(Company, booking.company_id) if booking.company_id else None
    show = await db.get(Show, booking.show_id) if booking.show_id else None

    cfdi = existing or Cfdi(booking_id=booking.id)
    cfdi.artist_id = booking.artist_id
    cfdi.company_id = booking.company_id

    try:
        if artist is None or company is None:
            raise FiscalDataMissing("La actuación no tiene músico u hotel asignado.")
        if (artist.csd_status or "none") != "active":
            raise FiscalDataMissing(
                "El músico todavía no ha cargado (o validado) su CSD de facturación."
            )
        figura = await _load_figura(db, artist)
        payload = build_cfdi_payload(booking, artist, company, figura, show, folio=booking.id)

        client = get_facturama()
        result = await client.stamp_cfdi(payload)

        stamp = (result.get("Complement") or {}).get("TaxStamp") or {}
        cfdi.status = "stamped"
        cfdi.facturama_id = result.get("Id")
        cfdi.uuid = stamp.get("Uuid")
        cfdi.serie = result.get("Serie")
        cfdi.folio = str(result.get("Folio")) if result.get("Folio") is not None else None
        cfdi.issuer_rfc = (result.get("Issuer") or {}).get("Rfc") or artist.rfc
        cfdi.receiver_rfc = (result.get("Receiver") or {}).get("Rfc") or company.tax_id
        cfdi.subtotal = result.get("Subtotal")
        cfdi.total = result.get("Total")
        stamp_date = stamp.get("Date") or result.get("Date")
        if stamp_date:
            try:
                from datetime import datetime as _dt
                cfdi.stamped_at = _dt.fromisoformat(stamp_date.replace("Z", ""))
            except (ValueError, AttributeError):
                cfdi.stamped_at = None
        cfdi.error = None
    except FacturamaError as exc:
        cfdi.status = "error"
        cfdi.error = exc.message
        logger.warning("Timbrado falló para booking %s: %s", booking.id, exc.message)
    except Exception as exc:  # noqa: BLE001 — nunca romper el flujo del caller
        cfdi.status = "error"
        cfdi.error = "Error inesperado al emitir el CFDI."
        logger.exception("Error inesperado timbrando booking %s: %s", booking.id, exc)

    if cfdi.id is None:
        db.add(cfdi)
    await db.commit()
    await db.refresh(cfdi)
    return cfdi
