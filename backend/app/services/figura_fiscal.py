"""Del régimen del SAT a la figura fiscal del catálogo.

Las retenciones de IVA e ISR NO se calculan del texto del régimen: salen de
`tax_figures`, y el enlace es `Artist.tax_figure_id`. Hoy ese enlace está vacío
en los 34 proveedores de producción, así que `compute_desglose` cae en la figura
por defecto y las retenciones salen iguales para todos — incluido un RESICO, que
retiene 1.25% de ISR en vez de 10%.

Este módulo cierra ese hueco: cuando alguien elige su régimen en el registro, se
le asigna la figura que le corresponde, sin pedirle un campo más que además
podría contradecir al régimen.

Sólo se mapean los cuatro casos que el propio catálogo nombra sin ambigüedad:

    612 -> Persona Física – Actividad Empresarial y Profesional
    626 -> Persona Física – RESICO
    601 -> Persona Moral – Régimen General
    603 -> Persona Moral – Otros regímenes vigentes

El resto de regímenes (605 sueldos, 606 arrendamiento, 621 incorporación, 625
plataformas…) se dejan SIN figura a propósito. Cada uno retiene distinto y eso
lo dice un contador, no yo: inventar el mapeo aquí produciría retenciones
plausibles y equivocadas, que es peor que no tener ninguna, porque nadie las
revisaría. `sin_mapear()` existe para poder listarlos y preguntarle.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tax_figure import TaxFigure

# código SAT -> trozo de nombre por el que se reconoce la figura en el catálogo
_POR_CODIGO = {
    "612": "actividad empresarial",
    "626": "resico",
    "601": "general",
    "603": "otros",
}

# Regímenes que existen en la lista del registro y NO se mapean aquí.
SIN_MAPEO = ("605", "606", "607", "608", "611", "614", "615", "616", "621", "622", "625")


def codigo_regimen(regimen: str | None) -> str | None:
    """El código SAT de un régimen, venga como "612" o como "612 - Personas…".

    El registro lo guarda con el texto completo y /me/fiscal lo guarda como
    código suelto. Las dos formas están en producción, así que se aceptan las
    dos en vez de arreglar una y romper la otra.
    """
    if not regimen:
        return None
    m = re.match(r"\s*(\d{3})", str(regimen))
    return m.group(1) if m else None


async def figura_para_regimen(db: AsyncSession, regimen: str | None) -> int | None:
    """El id de la figura fiscal que corresponde a ese régimen, o None.

    None significa "no lo sé", nunca "la primera": devolver una figura a boleo
    metería retenciones inventadas en los pagos de alguien.
    """
    codigo = codigo_regimen(regimen)
    if codigo not in _POR_CODIGO:
        return None
    aguja = _POR_CODIGO[codigo]
    es_moral = codigo in ("601", "603")
    figuras = (await db.execute(select(TaxFigure))).scalars().all()
    for f in figuras:
        nombre = (f.name or "").lower()
        # "general" aparece en "Persona Moral – Régimen General"; el filtro por
        # persona moral/física evita que un nombre parecido del otro lado case.
        if aguja in nombre and (("moral" in nombre) == es_moral):
            return f.id
    return None


async def asignar_figura(db: AsyncSession, artist) -> int | None:
    """Pone la figura que toca según el régimen del artista, si se reconoce.

    No pisa una figura ya puesta a mano: si el administrador o el contador la
    ajustaron para un caso raro (RESICO con ISR variable, por ejemplo), esa
    decisión manda sobre el automático.
    """
    if artist.tax_figure_id:
        return artist.tax_figure_id
    fid = await figura_para_regimen(db, artist.tax_regime)
    if fid:
        artist.tax_figure_id = fid
    return fid


def sin_mapear(regimen: str | None) -> bool:
    """True si es un régimen conocido para el que hace falta que un contador diga
    qué retenciones aplican. La pantalla lo usa para avisar en vez de callarse."""
    return codigo_regimen(regimen) in SIN_MAPEO
