"""Distinciones: constancia y posición frente a los demás, calculadas solas.

David, 2026-08-14: "esto nos permite también reconocer constancia... 92% de
retención, Top 10% de shows familiares en hoteles All Inclusive".

Es la vuelta de tuerca al perfil: hasta aquí el perfil decía lo que este músico
hizo; una distinción dice lo que hizo COMPARADO CON LOS DEMÁS. Un hotel no sabe
si 82% de aforo es bueno — sí sabe qué significa "top 10%".

Y por eso mismo es lo más fácil de arruinar. Un "Top 10%" sacado de un grupo de
tres proveedores es una mentira con cara de dato, y a diferencia de un número
inflado, ésta el hotel la puede comprobar el día que conozca el mercado. Las
tres reglas:

1. NO HAY PERCENTIL SIN GRUPO. Con menos de MIN_GRUPO proveedores comparables,
   la distinción comparativa no se publica. Ninguna. Hoy en SHOWMA casi ningún
   grupo llega, y está bien: las absolutas (constancia, cumplimiento) sí son
   ciertas desde el primer día y ésas se publican solas.

2. NADIE ENTRA A UN RANKING CON DOS ACTUACIONES. Hace falta MIN_ACTUACIONES
   dentro de ese grupo, o el que trabajó una vez y le fue bien sale arriba del
   que lleva cien.

3. LA DISTINCIÓN DICE SU GRUPO Y SU MUESTRA. "Top 10%" a secas no significa
   nada; "Top 10% en retención · Shows familiares en hoteles All Inclusive · 14
   proveedores comparados" sí, y además se puede discutir.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.booking import Booking
from app.models.company import Company
from app.models.review import Review
from app.models.show import Show
from app.models.venue import Venue
from app.services.trayectoria import (
    BANDAS_AFLUENCIA,
    BANDAS_RETENCION,
    es_agendada,
    es_cumplida,
)

MIN_GRUPO = 8           # proveedores comparables para poder publicar un percentil
MIN_ACTUACIONES = 5     # actuaciones propias dentro del grupo para entrar al ranking
MIN_RACHA = 3           # meses seguidos con actuaciones para presumir constancia
MIN_CUMPLIMIENTO = 10   # actuaciones para presumir un cumplimiento perfecto
TOPES = ((0.10, "Top 10%"), (0.25, "Top 25%"))

# El barrido del mercado se reutiliza: abrir diez perfiles seguidos no puede
# recalcularlo diez veces. Con el volumen de hoy cuesta milisegundos; el día que
# la tabla de actuaciones sea grande, esto se cambia por una vista materializada.
_TTL_SEGUNDOS = 300
_cache: dict = {"en": 0.0, "datos": None}


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _bonito(s: str | None) -> str:
    return (s or "").replace("_", " ").strip().capitalize()


class _Acumulado:
    """Lo que lleva un proveedor dentro de un grupo concreto."""

    __slots__ = ("n", "aforo", "reten", "hoteles", "por_hotel")

    def __init__(self) -> None:
        self.n = 0
        self.aforo: list[float] = []
        self.reten: list[float] = []
        self.hoteles: set[int] = set()
        self.por_hotel: dict[int, int] = {}

    def suma(self, b, cap: int | None, r) -> None:
        self.n += 1
        if b.company_id:
            self.hoteles.add(b.company_id)
            self.por_hotel[b.company_id] = self.por_hotel.get(b.company_id, 0) + 1
        if b.headcount_start and cap:
            self.aforo.append(min(b.headcount_start * 100.0 / cap, 100.0))
        elif r is not None and r.afluencia in BANDAS_AFLUENCIA:
            self.aforo.append(BANDAS_AFLUENCIA[r.afluencia])
        if b.headcount_end is not None and b.headcount_start:
            self.reten.append(min(b.headcount_end * 100.0 / b.headcount_start, 100.0))
        elif r is not None and r.retencion in BANDAS_RETENCION:
            self.reten.append(BANDAS_RETENCION[r.retencion])

    def promedio(self, cual: str) -> float | None:
        vals = self.aforo if cual == "aforo" else self.reten
        return (sum(vals) / len(vals)) if vals else None


def _racha_meses(fechas: list[datetime], ahora: datetime) -> int:
    """Meses seguidos con al menos una actuación, contando hacia atrás.

    Se arranca desde el último mes con actuación, no desde hoy: si estamos a día
    3 y todavía no toca este mes, la racha de dos años no se rompe por eso.
    """
    if not fechas:
        return 0
    meses = {(f.year, f.month) for f in fechas}
    ultimo = max(meses)
    # Si hace más de un mes que no trabaja, la racha ya está cortada.
    corte = (ahora.year * 12 + ahora.month) - (ultimo[0] * 12 + ultimo[1])
    if corte > 1:
        return 0
    n, y, m = 0, ultimo[0], ultimo[1]
    while (y, m) in meses:
        n += 1
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return n


async def _barrer(db) -> dict:
    """Una pasada por todo el mercado: qué hizo cada proveedor y en qué grupo."""
    ahora = _ahora()
    bookings = list((await db.execute(select(Booking))).scalars().all())
    shows = {s.id: s for s in (await db.execute(select(Show))).scalars().all()}
    empresas = {c.id: c for c in (await db.execute(select(Company))).scalars().all()}
    aforos = {
        vid: cap
        for vid, cap in (await db.execute(select(Venue.id, Venue.capacity))).all()
        if cap
    }
    resenas = {
        r.booking_id: r
        for r in (await db.execute(select(Review))).scalars().all()
    }

    # artista -> grupo -> acumulado ; y aparte lo global de cada artista
    grupos: dict[int, dict[tuple, _Acumulado]] = {}
    etiquetas: dict[tuple, str] = {}
    fechas: dict[int, list[datetime]] = {}
    agendadas: dict[int, int] = {}
    canceladas: dict[int, int] = {}

    for b in bookings:
        aid = b.artist_id
        if not aid:
            continue
        if es_agendada(b):
            agendadas[aid] = agendadas.get(aid, 0) + 1
            if b.cancelled_by == "artist":
                canceladas[aid] = canceladas.get(aid, 0) + 1
        if not es_cumplida(b, ahora):
            continue
        ini = _naive(b.starts_at)
        if ini:
            fechas.setdefault(aid, []).append(ini)

        show = shows.get(b.show_id or 0)
        empresa = empresas.get(b.company_id or 0)
        sub = (show.subcategory or show.category) if show else None
        todo_incluido = bool(empresa is not None and empresa.is_all_inclusive)

        claves: list[tuple[tuple, str]] = [(("todos",), "toda la plataforma")]
        if sub:
            claves.append((("sub", sub), _bonito(sub)))
        if todo_incluido:
            claves.append((("ai",), "hoteles All Inclusive"))
            if sub:
                claves.append(
                    (("sub_ai", sub), f"{_bonito(sub)} en hoteles All Inclusive")
                )

        r = resenas.get(b.id)
        cap = aforos.get(b.venue_id or 0)
        for clave, etiqueta in claves:
            etiquetas[clave] = etiqueta
            grupos.setdefault(aid, {}).setdefault(clave, _Acumulado()).suma(b, cap, r)

    return {
        "grupos": grupos,
        "etiquetas": etiquetas,
        "fechas": fechas,
        "agendadas": agendadas,
        "canceladas": canceladas,
        "ahora": ahora,
    }


async def mercado(db, refrescar: bool = False) -> dict:
    ahora = time.monotonic()
    if not refrescar and _cache["datos"] is not None and (ahora - _cache["en"]) < _TTL_SEGUNDOS:
        return _cache["datos"]
    datos = await _barrer(db)
    _cache["en"] = ahora
    _cache["datos"] = datos
    return datos


def invalidar() -> None:
    """Lo llama quien cambie actuaciones o reseñas para no servir un ranking viejo."""
    _cache["datos"] = None


def _posicion(valores: list[tuple[int, float]], artist_id: int) -> tuple[str, int, int] | None:
    """Devuelve (etiqueta del tope, posición, total) si entra en Top 10/25%."""
    if len(valores) < MIN_GRUPO:
        return None
    orden = sorted(valores, key=lambda t: -t[1])
    total = len(orden)
    for i, (aid, _) in enumerate(orden):
        if aid == artist_id:
            # El primero es el percentil 1/total, no 0: con 10 comparados, el
            # primero es el top 10% y el segundo ya no.
            razon = (i + 1) / total
            for limite, etiqueta in TOPES:
                if razon <= limite:
                    return etiqueta, i + 1, total
            return None
    return None


# Qué tan concreto es el grupo. Importa al elegir: "Top 10% en retención" dicho
# sobre TODA la plataforma es cierto pero flojo; dicho sobre "Shows familiares en
# hoteles All Inclusive" es justo lo que el hotel quiere saber, y es el ejemplo
# que puso David. Ante el mismo dato gana siempre el grupo más concreto.
_ESPECIFICIDAD = {"sub_ai": 3, "ai": 2, "sub": 2, "todos": 0}


def _comparativas(datos: dict, artist_id: int) -> list[dict]:
    grupos = datos["grupos"]
    mios = grupos.get(artist_id, {})
    fuera: list[dict] = []
    for clave, acc in mios.items():
        if acc.n < MIN_ACTUACIONES:
            continue
        etiqueta = datos["etiquetas"].get(clave, "")
        esp = _ESPECIFICIDAD.get(clave[0], 0)
        for metrica, campo, texto in (
            ("retencion", "reten", "retención de público"),
            ("aforo", "aforo", "aforo"),
        ):
            valores = [
                (aid, g[clave].promedio(metrica))
                for aid, g in grupos.items()
                if clave in g and g[clave].n >= MIN_ACTUACIONES
                and g[clave].promedio(metrica) is not None
            ]
            mio = acc.promedio(metrica)
            if mio is None:
                continue
            pos = _posicion(valores, artist_id)
            if pos:
                tope, lugar, total = pos
                fuera.append({
                    "tipo": "top",
                    "metrica": metrica,
                    "texto": f"{tope} en {texto}",
                    "grupo": etiqueta,
                    "detalle": (f"Lugar {lugar} de {total} proveedores comparados en "
                                f"{etiqueta}, sobre {acc.n} actuaciones"),
                    "peso": 100 - lugar + esp * 3,
                    "esp": esp,
                })
        # El más contratado del grupo: sólo el primero, y sólo si hay grupo.
        volumen = [(aid, float(g[clave].n)) for aid, g in grupos.items() if clave in g]
        if len(volumen) >= MIN_GRUPO:
            lider = max(volumen, key=lambda t: t[1])
            if lider[0] == artist_id and clave != ("todos",):
                fuera.append({
                    "tipo": "lider",
                    "metrica": "volumen",
                    "texto": f"El más contratado en {etiqueta}",
                    "grupo": etiqueta,
                    "detalle": (f"{acc.n} actuaciones, más que cualquiera de los otros "
                                f"{len(volumen) - 1} proveedores del grupo"),
                    "peso": 95 + esp * 3,
                    "esp": esp,
                })

    # Una sola distinción por métrica: la del grupo más concreto. Si no, el
    # mismo mérito sale tres veces (plataforma, categoría, categoría+plan) y la
    # fila de medallas deja de decir nada.
    mejor: dict[str, dict] = {}
    for d in fuera:
        m = d["metrica"]
        if m not in mejor or (d["esp"], d["peso"]) > (mejor[m]["esp"], mejor[m]["peso"]):
            mejor[m] = d
    return list(mejor.values())


def _absolutas(datos: dict, artist_id: int) -> list[dict]:
    """Las que no necesitan con quién compararse. Ciertas desde el primer día."""
    fuera: list[dict] = []
    ahora = datos["ahora"]
    fechas = datos["fechas"].get(artist_id, [])
    racha = _racha_meses(fechas, ahora)
    if racha >= MIN_RACHA:
        if racha >= 12:
            años = racha // 12
            texto = f"{años} año{'s' if años > 1 else ''} seguido{'s' if años > 1 else ''} con actuaciones"
        else:
            texto = f"{racha} meses seguidos con actuaciones"
        fuera.append({
            "tipo": "constancia",
            "texto": texto,
            "grupo": "",
            "detalle": f"Encadena {racha} meses sin quedarse un solo mes sin trabajar en SHOWMA",
            "peso": 80 + min(racha, 18),
        })

    ag = datos["agendadas"].get(artist_id, 0)
    can = datos["canceladas"].get(artist_id, 0)
    if ag >= MIN_CUMPLIMIENTO and can == 0:
        fuera.append({
            "tipo": "cumplimiento",
            "texto": f"Nunca ha cancelado en {ag} actuaciones",
            "grupo": "",
            "detalle": f"Aceptó {ag} actuaciones y se presentó a todas",
            "peso": 70 + min(ag // 10, 15),
        })

    todos = datos["grupos"].get(artist_id, {}).get(("todos",))
    if todos and len(todos.por_hotel) >= 3:
        repiten = sum(1 for n in todos.por_hotel.values() if n > 1)
        if repiten == len(todos.por_hotel):
            fuera.append({
                "tipo": "recontratacion",
                "texto": "Todos los hoteles lo volvieron a contratar",
                "grupo": "",
                "detalle": f"Los {len(todos.por_hotel)} hoteles que lo contrataron repitieron",
                "peso": 90,
            })
    return fuera


async def de_artista(db, artist_id: int, limite: int = 3) -> list[dict]:
    datos = await mercado(db)
    todas = _absolutas(datos, artist_id) + _comparativas(datos, artist_id)
    todas.sort(key=lambda d: -d["peso"])
    # Tres como mucho: una fila de medallas deja de significar algo en cuanto
    # todo el mundo tiene siete.
    vistas: set[str] = set()
    fuera = []
    for d in todas:
        if d["texto"] in vistas:
            continue
        vistas.add(d["texto"])
        fuera.append({k: v for k, v in d.items() if k not in ("peso", "esp")})
        if len(fuera) >= limite:
            break
    return fuera


async def de_varios(db, artist_ids: list[int]) -> dict[int, dict | None]:
    """La distinción más fuerte de cada uno, para pintarla en las tarjetas."""
    await mercado(db)
    fuera: dict[int, dict | None] = {}
    for aid in artist_ids:
        top = await de_artista(db, aid, limite=1)
        fuera[aid] = top[0] if top else None
    return fuera
