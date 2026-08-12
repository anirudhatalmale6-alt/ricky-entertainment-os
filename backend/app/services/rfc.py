"""Validación del RFC (estructura y dígito verificador del SAT).

David, 2026-08-12: "todas las validaciones de hoteles se harán manualmente en una
primera fase, para no tener errores". Esto no sustituye esa revisión a mano — la
apoya: atrapa el dedazo en el momento de capturar, y no diez días después cuando
la factura no timbra.

Dos niveles a propósito:

  * ESTRUCTURA mal formada -> es un error seguro (faltan letras, sobra un dígito,
    la fecha no existe). Eso sí se rechaza.
  * DÍGITO VERIFICADOR que no cuadra -> casi siempre es un dedazo, pero el SAT ha
    emitido algún RFC que no cumple el cálculo. Por eso se AVISA y se deja
    guardar: preferimos molestar con una advertencia a bloquear a un hotel real.

Quien decide qué hacer con el aviso es la pantalla; aquí sólo se informa.
"""
from __future__ import annotations

import re
from datetime import date

# El orden importa: la posición de cada carácter ES su valor.
#  0-9 -> 0..9 · A-N -> 10..23 · & -> 24 · O-Z -> 25..36 · espacio -> 37 · Ñ -> 38
_DIC = "0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ Ñ"

# 3 letras (moral) o 4 (física) + AAMMDD + homoclave de 3.
_FORMA = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3}$")

# RFC genéricos del SAT. XAXX010101000 NO cumple el dígito verificador y aun así
# es el válido para "público en general", así que va exento a mano.
GENERICOS = {
    "XAXX010101000",   # público en general
    "XEXX010101000",   # residentes en el extranjero
}


def normalize(rfc: str | None) -> str:
    return re.sub(r"[\s\-\.]", "", (rfc or "")).upper()


def _check_digit(rfc: str) -> str:
    """Dígito verificador que le tocaría a este RFC."""
    base = rfc[:-1].rjust(12, " ")     # las morales (12) se alinean con un espacio
    suma = sum(_DIC.index(ch) * (13 - i) for i, ch in enumerate(base))
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "A"
    return str(resto)


def _fecha_ok(rfc: str) -> bool:
    """Los 6 dígitos del centro son una fecha real (AAMMDD)."""
    cuerpo = rfc[:-3]
    seis = cuerpo[-6:]
    try:
        anio, mes, dia = int(seis[0:2]), int(seis[2:4]), int(seis[4:6])
    except ValueError:
        return False
    # Sin siglo no se puede saber el año exacto; basta con que mes y día existan.
    # Se prueba con un año bisiesto para no rechazar un 29 de febrero legítimo.
    try:
        date(2000 if anio % 4 == 0 else 2001, mes, dia)
    except ValueError:
        return False
    return True


def check(rfc: str | None) -> dict:
    """{'rfc', 'ok', 'malformado', 'digito_ok', 'tipo', 'mensaje'}."""
    r = normalize(rfc)
    if not r:
        return {"rfc": "", "ok": True, "malformado": False, "digito_ok": True,
                "tipo": None, "mensaje": None}

    if len(r) not in (12, 13) or not _FORMA.match(r) or not _fecha_ok(r):
        return {
            "rfc": r, "ok": False, "malformado": True, "digito_ok": False,
            "tipo": None,
            "mensaje": ("El RFC no tiene la forma correcta. Deben ser 12 caracteres "
                        "para una empresa o 13 para una persona física, con la fecha "
                        "en medio (por ejemplo ABC180429TM6)."),
        }

    tipo = "moral" if len(r) == 12 else "fisica"
    if r in GENERICOS:
        return {"rfc": r, "ok": True, "malformado": False, "digito_ok": True,
                "tipo": tipo, "mensaje": None}

    digito_ok = _check_digit(r) == r[-1]
    return {
        "rfc": r, "ok": True, "malformado": False, "digito_ok": digito_ok, "tipo": tipo,
        "mensaje": None if digito_ok else (
            "El último carácter del RFC no corresponde con el resto. Casi siempre "
            "es un error de captura: revísalo contra la constancia de situación "
            "fiscal antes de facturar."),
    }


def is_valid(rfc: str | None) -> bool:
    """Sólo estructura: lo que sí se puede rechazar sin miedo."""
    return check(rfc)["ok"]
