"""Trayectoria verificada: lo que la plataforma puede DEMOSTRAR de un músico.

David, 2026-08-14: a los hoteles les cuesta contratar a alguien que no conocen y
un video de YouTube no convence a nadie, porque lo sube cualquiera. La idea es
que la credibilidad la ponga la plataforma y no el propio músico: aquí no hay un
solo dato que él escriba, todo sale de lo que ya pasó dentro de SHOWMA.

Dos reglas de honestidad, que son las que hacen que esto valga algo:

1. Todo número va con su tamaño de muestra. "Retiene el 82% del público" no dice
   nada; "el 82%, medido en 6 actuaciones" sí. Por eso cada bloque devuelve su
   ``muestra`` y la pantalla la enseña siempre.

2. Con muy poca historia NO se publica un porcentaje. Un músico con una sola
   actuación cumplida saldría con "100% de cumplimiento", que es verdad y a la
   vez es mentira. Debajo del mínimo se dice "Nuevo en SHOWMA" y se muestran sus
   verificaciones, que sí son ciertas desde el primer día.

Si alguna vez hay que elegir entre que un perfil luzca mejor y que el número sea
honesto, gana el número: el día que un hotel contrate por una cifra de aquí y le
salga mal, se acabó la confianza en la plataforma entera.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.models.artist import Artist
from app.models.booking import Booking
from app.models.contract import ContractAcceptance
from app.models.enums import BookingStatus
from app.models.media import ArtistDocument
from app.models.venue import Venue

# Mínimos por debajo de los cuales no se publica un porcentaje.
MIN_CUMPLIMIENTO = 3      # actuaciones agendadas
MIN_AFORO = 2             # actuaciones con conteo de público
MIN_RESPUESTA = 3         # actuaciones respondidas


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _pct(parte: float, total: float) -> float | None:
    if not total:
        return None
    return round(parte * 100.0 / total, 1)


async def de_artista(db, artist: Artist) -> dict:
    """Todo lo demostrable de un músico, listo para pintar."""
    bookings = list((await db.execute(
        select(Booking).where(Booking.artist_id == artist.id)
    )).scalars().all())

    ahora = _ahora()
    # "Agendadas" = las que llegaron a existir para el músico. Las que canceló el
    # hotel no cuentan en su contra: no fue él quien falló.
    agendadas = [b for b in bookings if b.cancelled_by != "hotel"]
    canceladas_por_el = [b for b in agendadas if b.cancelled_by == "artist"]
    cumplidas = [
        b for b in agendadas
        if b.status == BookingStatus.COMPLETED
        or (b.status == BookingStatus.CONFIRMED and _naive(b.starts_at) and _naive(b.starts_at) < ahora)
    ]

    hoteles = {b.company_id for b in cumplidas if b.company_id}
    venues = {b.venue_id for b in cumplidas if b.venue_id}

    # Recontratación: de los hoteles que ya lo contrataron, cuántos repitieron.
    # Es el dato más fuerte del perfil — nadie repite con alguien que salió mal.
    por_hotel: dict[int, int] = {}
    for b in cumplidas:
        if b.company_id:
            por_hotel[b.company_id] = por_hotel.get(b.company_id, 0) + 1
    repitieron = sum(1 for n in por_hotel.values() if n > 1)

    # Primera actuación / alta: "desde cuándo está aquí".
    fechas = [_naive(b.starts_at) for b in cumplidas if b.starts_at]
    desde = min(fechas) if fechas else _naive(artist.created_at)

    out: dict = {
        "artist_id": artist.id,
        "stage_name": artist.stage_name,
        "desde": desde.date().isoformat() if desde else None,
        "actuaciones": len(cumplidas),
        "hoteles": len(hoteles),
        "venues": len(venues),
        "nuevo": len(cumplidas) < MIN_CUMPLIMIENTO,
    }

    # --- Recontratación ---
    if len(por_hotel) >= 2 and repitieron:
        out["recontratacion"] = {
            "hoteles_que_repitieron": repitieron,
            "hoteles_totales": len(por_hotel),
            "pct": _pct(repitieron, len(por_hotel)),
        }
    else:
        out["recontratacion"] = None

    # --- Cumplimiento ---
    if len(agendadas) >= MIN_CUMPLIMIENTO:
        out["cumplimiento"] = {
            "cumplidas": len(cumplidas),
            "agendadas": len(agendadas),
            "canceladas_por_el": len(canceladas_por_el),
            "pct": _pct(len(agendadas) - len(canceladas_por_el), len(agendadas)),
            "muestra": len(agendadas),
        }
    else:
        out["cumplimiento"] = None

    # --- Tiempo de respuesta: de que se le avisa a que contesta ---
    horas = []
    for b in bookings:
        ini, fin = _naive(b.notified_at), _naive(b.confirmed_at)
        if ini and fin and fin >= ini:
            horas.append((fin - ini).total_seconds() / 3600.0)
    if len(horas) >= MIN_RESPUESTA:
        horas.sort()
        mid = len(horas) // 2
        mediana = horas[mid] if len(horas) % 2 else (horas[mid - 1] + horas[mid]) / 2
        out["respuesta"] = {"horas": round(mediana, 1), "muestra": len(horas)}
    else:
        out["respuesta"] = None

    # --- Público: cuánto llenó y cuánta gente se quedó ---
    # Necesita el aforo del venue, así que se piden sólo los que hagan falta.
    medidas = [b for b in cumplidas if b.headcount_start]
    aforos: dict[int, int] = {}
    ids = {b.venue_id for b in medidas if b.venue_id}
    if ids:
        for vid, cap in (await db.execute(
            select(Venue.id, Venue.capacity).where(Venue.id.in_(ids))
        )).all():
            if cap:
                aforos[vid] = cap
    ocup, reten = [], []
    for b in medidas:
        cap = aforos.get(b.venue_id or 0)
        if cap:
            ocup.append(min(b.headcount_start * 100.0 / cap, 100.0))
        if b.headcount_end is not None and b.headcount_start:
            reten.append(min(b.headcount_end * 100.0 / b.headcount_start, 100.0))
    out["publico"] = None
    if len(medidas) >= MIN_AFORO and (ocup or reten):
        out["publico"] = {
            "ocupacion_pct": round(sum(ocup) / len(ocup), 1) if ocup else None,
            "retencion_pct": round(sum(reten) / len(reten), 1) if reten else None,
            "muestra": len(medidas),
        }

    # --- Verificaciones: ciertas desde el primer día, sin historial ---
    docs = {
        d.doc_type for d in (await db.execute(
            select(ArtistDocument).where(ArtistDocument.artist_id == artist.id)
        )).scalars().all()
    }
    firmado = (await db.execute(
        select(func.count(ContractAcceptance.id)).where(ContractAcceptance.artist_id == artist.id)
    )).scalar_one() > 0

    out["verificaciones"] = {
        "identidad": bool(artist.is_verified) or "identificacion" in docs,
        "constancia_sat": "constancia_sat" in docs or bool(artist.rfc),
        "puede_facturar": artist.csd_status == "active",
        "contrato_firmado": firmado,
        "partner": bool(artist.is_partner),
    }
    return out
