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


# ---------------------------------------------------------------------------
# Analisis de desempeno: lo mismo, pero comparado
# ---------------------------------------------------------------------------
# David (2026-08-15): "comparar con el dato promedio de retencion y convocatoria
# de esa persona en OTRAS propiedades, marcando si esta por debajo o por encima".
# Su argumento de venta es exactamente ese: el hotel ya lleva estos numeros,
# lo que no tiene es contra que compararlos.
#
# DOS COMPARACIONES, y conviene no confundirlas:
#   1. vs. el mismo proveedor en otras propiedades  -> "aqui rinde mas o menos
#      que en el resto del mercado".
#   2. vs. el promedio de su categoria EN ESTE HOTEL -> "comparado con lo que
#      normalmente me funciona a mi".
#
# LO QUE NUNCA SALE DE AQUI: el nombre de las otras propiedades, sus precios y
# su costo por persona. Un hotel no puede enterarse por este panel de lo que
# paga el de enfrente. Solo viajan promedios de asistencia y retencion.
#
# PISO DE PRIVACIDAD: la comparacion externa exige al menos 2 propiedades
# distintas y 3 noches. Con una sola propiedad detras, el "promedio en otras
# propiedades" ES el dato de ese hotel, con nombre y todo para quien conozca el
# mercado. Es el mismo criterio de las distinciones del perfil.
_MIN_PROPIEDADES_FUERA = 2
_MIN_NOCHES_FUERA = 3


class _Medida:
    """Convocatoria y retencion de un conjunto de noches."""

    def __init__(self):
        self.noches = 0
        self.gente = 0
        self.se_quedaron = 0
        self.gasto = 0.0
        # Una noche sin precio SI cuenta para la asistencia (el conteo de gente
        # es real) pero no puede contar para el costo por persona: su gente
        # entraria al divisor sin que su dinero entre al dividendo, y el costo
        # saldria mas barato de lo que fue.
        self.gente_con_precio = 0
        self.noches_con_precio = 0
        self.propiedades: set[int] = set()

    def suma(self, b, asistentes: int, precio: float | None):
        self.noches += 1
        self.gente += asistentes
        self.se_quedaron += b.headcount_end if b.headcount_end is not None else asistentes
        if precio is not None:
            self.gasto += precio
            self.gente_con_precio += asistentes
            self.noches_con_precio += 1
        if b.company_id:
            self.propiedades.add(b.company_id)

    @property
    def convocatoria(self) -> float | None:
        """Gente por noche. Comparar totales seria comparar quien trabajo mas."""
        return round(self.gente / self.noches, 1) if self.noches else None

    @property
    def retencion(self) -> float | None:
        return _pct(self.se_quedaron, self.gente)


def _delta_pct(mio: float | None, otro: float | None) -> float | None:
    """Cuanto mas (o menos) que la referencia, en %."""
    if mio is None or not otro:
        return None
    return round((mio - otro) / otro * 100, 1)


def _delta_puntos(mio: float | None, otro: float | None) -> float | None:
    """Diferencia entre dos porcentajes, en puntos. Un 92% contra un 85% son
    7 puntos, no un 8%: decirlo en % de % confunde a quien lo lee."""
    if mio is None or otro is None:
        return None
    return round(mio - otro, 1)


@router.get("/desempeno")
async def desempeno(
    scope: CurrentScope,
    db: DbSession,
    company_id: int | None = Query(default=None),
    venue_id: int | None = Query(default=None),
    categoria: str | None = Query(default=None),
    desde: datetime | None = None,
    hasta: datetime | None = None,
    por: str = Query(default="proveedor", pattern="^(proveedor|show)$"),
):
    propiedades = await _propiedades_visibles(scope, db)
    if not propiedades:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu cuenta no tiene ninguna propiedad asociada.",
        )
    permitidas = {c.id for c in propiedades}
    if company_id is not None and company_id not in permitidas:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esa propiedad.",
        )
    objetivo = [company_id] if company_id is not None else sorted(permitidas)

    stmt = select(Booking).where(
        Booking.company_id.in_(objetivo),
        Booking.status == BookingStatus.COMPLETED,
        Booking.headcount_start.isnot(None),
        Booking.headcount_start > 0,
    )
    if desde is not None:
        stmt = stmt.where(Booking.starts_at >= desde)
    if hasta is not None:
        stmt = stmt.where(Booking.starts_at <= hasta)
    if venue_id is not None:
        stmt = stmt.where(Booking.venue_id == venue_id)
    mias = list((await db.execute(stmt)).scalars().all())

    sids = {b.show_id for b in mias if b.show_id}
    aids = {b.artist_id for b in mias if b.artist_id}
    shows = {s.id: s for s in (
        (await db.execute(select(Show).where(Show.id.in_(sids)))).scalars().all() if sids else []
    )}
    artistas = {a.id: a for a in (
        (await db.execute(select(Artist).where(Artist.id.in_(aids)))).scalars().all() if aids else []
    )}
    venues_mios = {v.id: v for v in (
        (await db.execute(select(Venue).where(Venue.company_id.in_(objetivo)))).scalars().all()
    )}

    def etiqueta_categoria(show) -> str:
        if not show:
            return "Sin categoría"
        return show.subcategory or show.category or "Sin categoría"

    # El filtro de categoria se aplica DESPUES de resolver los shows: la
    # categoria vive en el show, no en la actuacion.
    if categoria:
        mias = [b for b in mias if etiqueta_categoria(shows.get(b.show_id)) == categoria]

    # --- lo mio, agrupado -------------------------------------------------
    grupos: dict[tuple, dict] = {}
    for b in mias:
        show = shows.get(b.show_id) if b.show_id else None
        artista = artistas.get(b.artist_id) if b.artist_id else None
        if por == "show":
            clave = ("show", b.show_id)
            nombre = show.show_name if show else "Show no identificado"
        else:
            clave = ("artista", b.artist_id)
            nombre = artista.stage_name if artista else "Proveedor no identificado"
        g = grupos.setdefault(clave, {
            "nombre": nombre,
            "artist_id": b.artist_id,
            "show_id": b.show_id if por == "show" else None,
            "medida": _Medida(),
            "cats": {},
        })
        g["medida"].suma(b, b.headcount_start, float(b.agreed_price) if b.agreed_price is not None else None)
        cat = etiqueta_categoria(show)
        g["cats"][cat] = g["cats"].get(cat, 0) + 1

    # --- los mismos proveedores, FUERA de las propiedades analizadas ------
    fuera: dict[int, _Medida] = {}
    ids_fuera = {g["artist_id"] for g in grupos.values() if g["artist_id"]}
    if ids_fuera:
        f = select(Booking).where(
            Booking.artist_id.in_(ids_fuera),
            Booking.status == BookingStatus.COMPLETED,
            Booking.headcount_start.isnot(None),
            Booking.headcount_start > 0,
            Booking.company_id.isnot(None),
            Booking.company_id.notin_(objetivo),
        )
        # Mismo periodo en los dos lados: en la Riviera un agosto no se compara
        # con un septiembre, y si el filtro solo aplicara a un lado la diferencia
        # seria de temporada, no del show.
        if desde is not None:
            f = f.where(Booking.starts_at >= desde)
        if hasta is not None:
            f = f.where(Booking.starts_at <= hasta)
        for b in (await db.execute(f)).scalars().all():
            fuera.setdefault(b.artist_id, _Medida()).suma(b, b.headcount_start, None)

    # --- promedio de cada categoria EN ESTE HOTEL -------------------------
    # Se guarda tambien lo que aporto cada fila para poder restarselo: si un
    # proveedor se compara contra un promedio que lo incluye a el, se esta
    # comparando en parte consigo mismo y la diferencia sale achicada.
    por_categoria: dict[str, _Medida] = {}
    aporte: dict[tuple, _Medida] = {}
    for b in mias:
        cat = etiqueta_categoria(shows.get(b.show_id))
        por_categoria.setdefault(cat, _Medida()).suma(b, b.headcount_start, None)
        clave = ("show", b.show_id) if por == "show" else ("artista", b.artist_id)
        aporte.setdefault((cat, clave), _Medida()).suma(b, b.headcount_start, None)

    def resto_de_categoria(cat: str, clave: tuple) -> _Medida | None:
        """El promedio de la categoria SIN esta fila. None si no queda nadie."""
        total = por_categoria.get(cat)
        if total is None:
            return None
        propio = aporte.get((cat, clave))
        r = _Medida()
        r.noches = total.noches - (propio.noches if propio else 0)
        r.gente = total.gente - (propio.gente if propio else 0)
        r.se_quedaron = total.se_quedaron - (propio.se_quedaron if propio else 0)
        return r if r.noches > 0 and r.gente > 0 else None

    filas = []
    for clave, g in grupos.items():
        m: _Medida = g["medida"]
        cat = max(g["cats"].items(), key=lambda kv: kv[1])[0] if g["cats"] else "Sin categoría"
        ref_cat = resto_de_categoria(cat, clave)

        ext = fuera.get(g["artist_id"]) if g["artist_id"] else None
        # El piso de privacidad se aplica aqui y no se negocia.
        publicable = bool(
            ext
            and len(ext.propiedades) >= _MIN_PROPIEDADES_FUERA
            and ext.noches >= _MIN_NOCHES_FUERA
        )
        bloque_fuera = {
            "propiedades": len(ext.propiedades) if ext else 0,
            "noches": ext.noches if ext else 0,
            "convocatoria": ext.convocatoria if publicable else None,
            "retencion": ext.retencion if publicable else None,
            "publicable": publicable,
        }

        filas.append({
            "nombre": g["nombre"],
            "artist_id": g["artist_id"],
            "show_id": g["show_id"],
            "categoria": cat,
            "noches": m.noches,
            "gente": m.gente,
            "convocatoria": m.convocatoria,
            "retencion": m.retencion,
            "costo_persona": _por_persona(m.gasto, m.gente_con_precio),
            "gasto": round(m.gasto, 2),
            "noches_con_precio": m.noches_con_precio,
            "fuera": bloque_fuera,
            # Positivo = aqui le va mejor que en el resto del mercado.
            "vs_fuera_convocatoria": _delta_pct(m.convocatoria, bloque_fuera["convocatoria"]),
            "vs_fuera_retencion": _delta_puntos(m.retencion, bloque_fuera["retencion"]),
            # Contra lo que normalmente funciona en esta propiedad. Con una sola
            # fila en la categoria no hay contra que comparar: seria consigo mismo.
            "vs_categoria_convocatoria": (
                _delta_pct(m.convocatoria, ref_cat.convocatoria) if ref_cat else None
            ),
            "vs_categoria_retencion": (
                _delta_puntos(m.retencion, ref_cat.retencion) if ref_cat else None
            ),
            "categoria_noches": ref_cat.noches if ref_cat else 0,
        })

    filas.sort(key=lambda f: f["gente"], reverse=True)
    sin_referencia = sum(1 for f in filas if not f["fuera"]["publicable"])

    return {
        "propiedades": [{"id": c.id, "name": c.name} for c in propiedades],
        "venues": [
            {"id": v.id, "name": v.name, "company_id": v.company_id}
            for v in sorted(venues_mios.values(), key=lambda v: v.name)
        ],
        "categorias": sorted(por_categoria),
        "por": por,
        "filas": filas,
        "reglas": {
            "min_propiedades_fuera": _MIN_PROPIEDADES_FUERA,
            "min_noches_fuera": _MIN_NOCHES_FUERA,
            "sin_referencia": sin_referencia,
        },
    }
