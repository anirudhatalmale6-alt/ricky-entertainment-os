"""Límite de largo para las descripciones (David, 29/10).

"Limitar a 800 caracteres las descripciones de shows y proveedores, para
ofrecer perfiles fáciles de comparar". Sólo en la ENTRADA (alta y edición): en
la base hay biografías de hasta 2,594 caracteres y validarlas al leer tiraría el
catálogo. Quien tenga una más larga la recorta la próxima vez que guarde.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator

MAX_DESCRIPCION = 800


def _corta(v):
    if v is None:
        return None
    t = str(v).strip()
    if len(t) > MAX_DESCRIPCION:
        raise ValueError(
            f"La descripción tiene {len(t):,} caracteres y el máximo es {MAX_DESCRIPCION}. "
            "Recórtala para que los hoteles puedan comparar perfiles de un vistazo.")
    return t or None


Descripcion = Annotated[str | None, BeforeValidator(_corta)]


def recorta(t: str | None, n: int = MAX_DESCRIPCION) -> str | None:
    """Lo que ve un HOTEL de una descripción vieja más larga de 800 (David,
    29/10: "justo por ellos los quise regular"). Se corta en el último espacio
    antes del límite, con "…". El texto guardado no se toca: su dueño lo sigue
    viendo entero para recortarlo como él quiera."""
    if not t or len(t) <= n:
        return t
    corte = t[:n]
    espacio = corte.rfind(" ")
    if espacio > n * 0.8:
        corte = corte[:espacio]
    return corte.rstrip(" ,.;:-\n") + "…"
