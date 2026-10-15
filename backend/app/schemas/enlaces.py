"""Enlaces que un proveedor puede poner en su ficha: solo video.

David, 15/10: un proveedor puso su Instagram donde iba su canal de YouTube, y
la ficha lo enseñaba como "Ver canal". El perfil sólo admite video (desde el
08/08 se quitaron Instagram, Facebook, TikTok y webs propias): los hoteles
contratan a través de SHOWMA, no por mensaje directo en una red.

Como `Rfc`, se pone como anotación SÓLO en los esquemas de entrada (alta y
edición). Los de lectura heredan de las mismas bases y en la base ya hay
enlaces de Instagram guardados; validarlos al LEER tiraría el catálogo entero
en vez de dejar corregirlos.

Se acepta lo que se puede ver dentro de la plataforma o es un canal de video:
  * video de un show: YouTube o Vimeo;
  * campo "YouTube" del perfil: YouTube.
Un "@usuario" suelto se entiende como canal de YouTube, que es como lo escriben.
"""
from __future__ import annotations

from typing import Annotated
from urllib.parse import urlparse

from pydantic import BeforeValidator

_YOUTUBE = ("youtube.com", "youtu.be", "youtube-nocookie.com")
_VIMEO = ("vimeo.com",)

MSG_VIDEO = ("Solo se aceptan enlaces de YouTube o Vimeo. Instagram, Facebook, "
             "TikTok u otras redes no se pueden poner aquí: los hoteles contratan "
             "a través de SHOWMA.")
MSG_YOUTUBE = ("Aquí va el enlace de tu canal de YouTube. Instagram, Facebook, "
               "TikTok u otras redes no se pueden poner: los hoteles contratan a "
               "través de SHOWMA.")


def _normaliza(v) -> str | None:
    if v is None:
        return None
    u = str(v).strip()
    if not u:
        return None
    if u.startswith("@") and " " not in u:
        return "https://www.youtube.com/" + u
    if "://" not in u:
        u = "https://" + u
    return u


def _host(u: str) -> str:
    h = (urlparse(u).hostname or "").lower()
    for pre in ("www.", "m.", "music."):
        if h.startswith(pre):
            h = h[len(pre):]
    return h


def _de(u: str, dominios: tuple[str, ...]) -> bool:
    h = _host(u)
    return any(h == d or h.endswith("." + d) for d in dominios)


def _video(v):
    u = _normaliza(v)
    if u is None:
        return None
    if not _de(u, _YOUTUBE + _VIMEO):
        raise ValueError(MSG_VIDEO)
    return u


def _redes(d):
    """El perfil sólo enseña YouTube. Las demás claves que pudieran venir (de
    fichas antiguas) se descartan al guardar en vez de rechazar el guardado:
    no se ven en ningún sitio, y bloquear por ellas impediría editar la ficha."""
    if d is None:
        return None
    if not isinstance(d, dict):
        raise ValueError("Formato de redes no válido.")
    yt = _normaliza(d.get("youtube"))
    if yt is None:
        return {}
    if not _de(yt, _YOUTUBE):
        raise ValueError(MSG_YOUTUBE)
    return {"youtube": yt}


Video = Annotated[str | None, BeforeValidator(_video)]
Redes = Annotated[dict[str, str] | None, BeforeValidator(_redes)]


def es_video_valido(v) -> bool:
    try:
        _video(v)
        return True
    except ValueError:
        return False


def es_youtube_valido(v) -> bool:
    u = _normaliza(v)
    return u is None or _de(u, _YOUTUBE)
