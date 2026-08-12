"""Tipo `Rfc` reutilizable para los esquemas que guardan un RFC.

Se pone como anotación en el campo (`tax_id: Rfc = None`) y así la validación
queda en un solo lugar, sirva el RFC para un hotel, para un grupo o para un
prospecto. Rechaza sólo lo que con certeza está mal formado y normaliza a
mayúsculas sin guiones ni espacios; el dígito verificador se avisa aparte
(ver app/services/rfc.py) porque hay RFC emitidos que no lo cumplen.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator

from app.services import rfc as rfc_svc


def _validar(v):
    if v is None:
        return None
    chk = rfc_svc.check(str(v))
    if not chk["ok"]:
        raise ValueError(chk["mensaje"])
    return chk["rfc"] or None


Rfc = Annotated[str | None, BeforeValidator(_validar)]
