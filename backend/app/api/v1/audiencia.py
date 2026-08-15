"""Analisis de audiencia de UNA propiedad: cuanta gente llego, cuanta se quedo
y cuanto costo cada persona.

El hotel ya captura dos numeros la noche del show (aforo al iniciar y al
terminar) y el venue tiene su capacidad. Con eso y el precio pactado sale lo
unico que un director de entretenimiento pregunta de verdad: que show me llena
la terraza, cual la vacia, y cuanto me esta costando cada persona sentada.

Reglas de calculo, porque de aqui salen decisiones de dinero:

 * Solo cuentan actuaciones COMPLETED. Una confirmada todavia no ocurrio y
   meterla ensuciaria el promedio con ceros.
 * "Asistentes" es el conteo de la noche (headcount_start). No se estima
   nunca desde la capacidad: si nadie lo capturo, esa actuacion no entra y se
   reporta aparte en `cobertura`.
 * El costo por persona de un grupo es SUMA(dinero) / SUMA(personas), no el
   promedio de los costos por persona de cada noche. Promediar razones le da
   el mismo peso a un show de 30 personas que a uno de 600 y sale un numero
   que no cuadra con el estado de cuenta.
 * La atraccion (que tan lleno estuvo) necesita la capacidad del venue. Varias
   actuaciones viejas apuntan a salones ya borrados y se quedaron sin ella:
   esas suman en asistentes y en costo por persona, pero NO en atraccion, y se
   dicen en `cobertura`. Mejor un dato de menos que un porcentaje inventado.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentScope, DbSession
from app.models.artist import Artist
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.show import Show
from app.models.venue import Venue

router = APIRouter(prefix="/audiencia", tags=["audiencia"])

_MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
             "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _pct(parte: float, total: float) -> float | None:
    return round(parte / total * 100, 1) if total else None


def _por_persona(dinero: float, personas: int) -> float | None:
    return round(dinero / personas, 2) if personas else None


class _Grupo:
    """Acumulador de un corte (venue, show, artista o mes)."""

    def __init__(self, nombre: str, capacidad: int | None = None):
        self.nombre = nombre
        self.capacidad = capacidad
        self.actuaciones = 0
        self.asistentes = 0
        self.se_quedaron = 0
        self.gasto = 0.0
        # La atraccion se calcula SOLO con las noches cuyo salon tiene capacidad:
        # se guardan aparte su gente y su aforo. Si se mezclara la gente de una
        # noche sin capacidad contra el aforo de las otras, el porcentaje sube
        # solo (paso en la primera version: 97% cuando era 84%).
        self.aforo_posible = 0
        self.gente_con_aforo = 0
        self.noches_con_aforo = 0

    def suma(self, asistentes: int, final: int | None, precio: float, cap: int | None):
        self.actuaciones += 1
        self.asistentes += asistentes
        self.se_quedaron += final if final is not None else asistentes
        self.gasto += precio
        if cap:
            self.aforo_posible += cap
            self.gente_con_aforo += asistentes
            self.noches_con_aforo += 1

    def salida(self) -> dict:
        return {
            "nombre": self.nombre,
            "capacidad": self.capacidad,
            "actuaciones": self.actuaciones,
            "asistentes": self.asistentes,
            "se_quedaron": self.se_quedaron,
            "gasto": round(self.gasto, 2),
            "costo_persona": _por_persona(self.gasto, self.asistentes),
            "atraccion": _pct(self.gente_con_aforo, self.aforo_posible),
            # Cuantas de esas noches pudieron medir que tan lleno estuvo.
            "noches_con_aforo": self.noches_con_aforo,
            "retencion": _pct(self.se_quedaron, self.asistentes),
        }


async def _propiedades_visibles(scope, db) -> list[Company]:
    """Las propiedades que este usuario puede analizar."""
    stmt = select(Company).order_by(Company.name)
    if scope.is_admin:
        pass
    elif scope.group_id is not None:
        stmt = stmt.where(Company.group_id == scope.group_id)
    elif scope.company_id is not None:
        stmt = stmt.where(Company.id == scope.company_id)
    else:
        return []
    return list((await db.execute(stmt)).scalars().all())


@router.get("")
async def analisis_audiencia(
    scope: CurrentScope,
    db: DbSession,
    company_id: int | None = Query(default=None, description="Propiedad a analizar"),
    desde: datetime | None = None,
    hasta: datetime | None = None,
):
    propiedades = await _propiedades_visibles(scope, db)
    if not propiedades:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu cuenta no tiene ninguna propiedad asociada.",
        )
    permitidas = {c.id for c in propiedades}
    if company_id is not None and company_id not in permitidas:
        # No se dice si existe o no: para este usuario, no existe.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esa propiedad.",
        )
    # Sin elegir propiedad se analiza toda la cadena que le toca ver.
    objetivo = [company_id] if company_id is not None else sorted(permitidas)

    stmt = select(Booking).where(
        Booking.company_id.in_(objetivo),
        Booking.status == BookingStatus.COMPLETED,
    )
    if desde is not None:
        stmt = stmt.where(Booking.starts_at >= desde)
    if hasta is not None:
        stmt = stmt.where(Booking.starts_at <= hasta)
    actuaciones = list((await db.execute(stmt.order_by(Booking.starts_at))).scalars().all())

    vids = {b.venue_id for b in actuaciones if b.venue_id}
    sids = {b.show_id for b in actuaciones if b.show_id}
    aids = {b.artist_id for b in actuaciones if b.artist_id}
    venues = {v.id: v for v in (
        (await db.execute(select(Venue).where(Venue.id.in_(vids)))).scalars().all() if vids else []
    )}
    shows = {s.id: s for s in (
        (await db.execute(select(Show).where(Show.id.in_(sids)))).scalars().all() if sids else []
    )}
    artistas = {a.id: a for a in (
        (await db.execute(select(Artist).where(Artist.id.in_(aids)))).scalars().all() if aids else []
    )}

    por_venue: dict[str, _Grupo] = {}
    por_show: dict[str, _Grupo] = {}
    por_artista: dict[str, _Grupo] = {}
    por_mes: dict[str, _Grupo] = {}
    detalle: list[dict] = []
    total = _Grupo("total")

    sin_conteo = sin_precio = sin_capacidad = 0

    for b in actuaciones:
        asistentes = b.headcount_start
        precio = float(b.agreed_price) if b.agreed_price is not None else None
        if not asistentes:
            sin_conteo += 1
            continue
        if precio is None:
            sin_precio += 1
            continue
        venue = venues.get(b.venue_id) if b.venue_id else None
        cap = venue.capacity if venue and venue.capacity else None
        if cap is None:
            sin_capacidad += 1
        final = b.headcount_end
        show = shows.get(b.show_id) if b.show_id else None
        artista = artistas.get(b.artist_id) if b.artist_id else None

        total.suma(asistentes, final, precio, cap)

        nom_v = venue.name if venue else "Sin salón registrado"
        g = por_venue.setdefault(nom_v, _Grupo(nom_v, cap))
        if g.capacidad is None and cap:
            g.capacidad = cap
        g.suma(asistentes, final, precio, cap)

        nom_s = show.show_name if show else "Show no identificado"
        por_show.setdefault(nom_s, _Grupo(nom_s)).suma(asistentes, final, precio, cap)

        nom_a = artista.stage_name if artista else "Proveedor no identificado"
        por_artista.setdefault(nom_a, _Grupo(nom_a)).suma(asistentes, final, precio, cap)

        clave = f"{b.starts_at.year}-{b.starts_at.month:02d}"
        etiqueta = f"{_MESES_ES[b.starts_at.month - 1]} {b.starts_at.year}"
        por_mes.setdefault(clave, _Grupo(etiqueta)).suma(asistentes, final, precio, cap)

        detalle.append({
            "id": b.id,
            "fecha": b.starts_at.isoformat(),
            "venue": nom_v,
            "show": nom_s,
            "artista": nom_a,
            "capacidad": cap,
            "asistentes": asistentes,
            "se_quedaron": final,
            "atraccion": _pct(asistentes, cap) if cap else None,
            "retencion": _pct(final, asistentes) if final is not None else None,
            "gasto": round(precio, 2),
            "costo_persona": _por_persona(precio, asistentes),
        })

    def ordenar(d: dict[str, _Grupo], por_fecha: bool = False) -> list[dict]:
        items = sorted(d.items()) if por_fecha else sorted(
            d.items(), key=lambda kv: kv[1].asistentes, reverse=True
        )
        return [g.salida() for _, g in items]

    filas_show = ordenar(por_show)
    # Barato/caro solo se compara entre shows con mas de una noche: con una sola
    # funcion, una lluvia o un puente cambian el ranking y no dice nada.
    comparables = [f for f in filas_show if f["costo_persona"] is not None and f["actuaciones"] > 1]
    comparables.sort(key=lambda f: f["costo_persona"])

    resumen = total.salida()
    resumen["propiedades"] = len(objetivo)

    return {
        "propiedades": [{"id": c.id, "name": c.name} for c in propiedades],
        "company_id": company_id,
        "periodo": {
            "desde": desde.isoformat() if desde else None,
            "hasta": hasta.isoformat() if hasta else None,
            "primera": actuaciones[0].starts_at.isoformat() if actuaciones else None,
            "ultima": actuaciones[-1].starts_at.isoformat() if actuaciones else None,
        },
        "resumen": resumen,
        "por_venue": ordenar(por_venue),
        "por_show": filas_show,
        "por_artista": ordenar(por_artista),
        "por_mes": ordenar(por_mes, por_fecha=True),
        "mejores": comparables[:3],
        "peores": list(reversed(comparables[-3:])) if len(comparables) > 3 else [],
        "detalle": detalle,
        # Lo que NO alcanzo a entrar, dicho de frente: es la diferencia entre
        # "mi hotel atrae poco" y "no lo estamos capturando".
        "cobertura": {
            "realizadas": len(actuaciones),
            "analizadas": total.actuaciones,
            "sin_conteo": sin_conteo,
            "sin_precio": sin_precio,
            "sin_capacidad": sin_capacidad,
        },
    }
