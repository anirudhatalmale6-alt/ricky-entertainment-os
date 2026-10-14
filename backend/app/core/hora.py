"""La hora de la PROPIEDAD, para compararla con la hora de una actuación.

Las actuaciones se guardan con la hora de pared del hotel: "20:00" es las ocho
de la noche en Cancún. El servidor, en cambio, vive en UTC, que en Quintana Roo
va CINCO horas por delante (sin horario de verano). Comparar `starts_at` con un
`now()` en UTC desplazaba todo cinco horas:

  * el pase de acceso decía "FUE AYER" a partir de las 19:00 de Cancún, justo
    cuando empiezan casi todos los shows;
  * el aviso al hotel de "el músico canceló, busca reemplazo" desaparecía en
    las cinco horas previas al show, que es cuando más falta hace;
  * la cancelación se bloqueaba siete horas antes en vez de dos;
  * se podía calificar una actuación cinco horas ANTES de que empezara.

Regla: para comparar con la hora de una actuación, `ahora_local()`. Para sellar
CUÁNDO pasó algo (cancelled_at, confirmed_at…), se sigue usando UTC: esos
sellos son registro, no se comparan con la hora del show.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def zona() -> ZoneInfo:
    return ZoneInfo(settings.ZONA_HORARIA or "America/Cancun")


def ahora_local() -> datetime:
    """Ahora, en la hora de pared de las propiedades, sin tzinfo (como starts_at)."""
    return datetime.now(zona()).replace(tzinfo=None)


def utc_a_local(valor):
    """Un sello de registro (UTC, sin tzinfo) a la hora de la propiedad.

    Para ENSEÑAR cuándo pasó algo (llegó, se canceló…) junto a la hora del show.
    Sin esto la bitácora decía "cancelada a las 03:44" de un show de las 00:44 y
    parecía que el hotel había cancelado cuando el show ya había empezado.
    """
    from datetime import timezone

    if valor is None:
        return None
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(zona()).replace(tzinfo=None)
