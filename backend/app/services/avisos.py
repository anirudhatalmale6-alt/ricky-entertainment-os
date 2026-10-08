"""Avisos por correo: el mismo aviso que se ve dentro de la plataforma, enviado.

Hasta ahora todo aviso vivía dentro de SHOWMA (la campanita del músico, los
avisos del hotel). Mientras no exista la app, nadie entra a la plataforma a
mirar si pasó algo: hay que ir a buscarlos al correo (David 2026-08-14).

Dos reglas que rigen este módulo:

1. El correo NUNCA puede tumbar ni frenar la operación. Se envía DESPUÉS de que
   la petición terminó, en segundo plano, y ``mailer.send`` ya se traga sus
   propios errores. Si el SMTP está caído, la actuación se agenda igual y el
   aviso sigue estando dentro de la plataforma.

2. Se envía DESPUÉS del commit. Si se enviara antes y luego fallara la
   transacción, el músico tendría en el correo una actuación que no existe.

Por eso el flujo es siempre el mismo: durante la petición se van juntando
``Aviso``, se hace ``await db.commit()``, y sólo entonces ``despachar(...)``.
"""
from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import settings
from app.services import mailer

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Aviso:
    to: str
    subject: str
    text: str
    html: str
    # Si viene, se marca en artist_notifications que el correo salió, para que
    # en Master se pueda ver a quién se le avisó de verdad y a quién no.
    notification_id: int | None = None
    # Imágenes incrustadas por Content-ID: {"qrpase": b"...png..."}. Se usa para
    # el QR del pase de acceso; ver mailer._send_sync.
    imagenes: dict | None = None


def activo() -> bool:
    return settings.NOTIFY_EMAIL and mailer.is_configured()


# --- Envío ----------------------------------------------------------------

async def _marcar_enviados(ids: list[int]) -> None:
    """Sella email_sent_at en los avisos que sí salieron."""
    if not ids:
        return
    from sqlalchemy import update

    from app.db.session import AsyncSessionLocal
    from app.models.notification import ArtistNotification

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ArtistNotification)
                .where(ArtistNotification.id.in_(ids))
                .values(email_sent_at=datetime.now(timezone.utc).replace(tzinfo=None))
            )
            await db.commit()
    except Exception:  # noqa: BLE001 - sellar es contabilidad, no puede romper nada
        log.exception("No se pudo sellar email_sent_at de %s", ids)


async def _correr(avisos: list[Aviso]) -> None:
    enviados: list[int] = []
    for a in avisos:
        ok = await mailer.send(a.to, a.subject, a.text, a.html, a.imagenes)
        if ok and a.notification_id:
            enviados.append(a.notification_id)
    await _marcar_enviados(enviados)


def despachar(bg, avisos: list[Aviso]) -> None:
    """Encola los correos para después de responder.

    Va por ``BackgroundTasks`` de FastAPI y no por ``create_task``: la tarea
    queda enganchada al ciclo de la petición, así que se ejecuta seguro tanto
    con uvicorn como en el despliegue de cPanel (donde cada petición corre en
    su propio event loop y una tarea suelta moriría con él).
    """
    avisos = [a for a in avisos if a and a.to]
    if not avisos:
        return
    if not activo():
        log.info("Correo desactivado o sin SMTP; %d aviso(s) sólo quedan en la plataforma", len(avisos))
        return
    bg.add_task(_correr, avisos)


# --- A quién se le avisa ---------------------------------------------------

async def correo_artista(db, artist) -> str | None:
    """El correo del músico: el de su ficha y, si no tiene, el de su cuenta."""
    if artist is None:
        return None
    if artist.email:
        return artist.email.strip() or None
    if artist.user_id:
        from app.models.user import User

        user = await db.get(User, artist.user_id)
        if user and user.email:
            return user.email.strip() or None
    return None


async def correos_hotel(db, company_id: int | None) -> list[str]:
    """Los correos del hotel: el de contacto de la ficha más el de cada persona
    con cuenta en esa propiedad. Un aviso urgente (una cancelación) tiene que
    llegarle a alguien que lo lea, no a un buzón general que nadie abre."""
    if not company_id:
        return []
    from sqlalchemy import select

    from app.models.booker import Booker
    from app.models.company import Company
    from app.models.user import User

    destinos: list[str] = []
    company = await db.get(Company, company_id)
    if company and company.contact_email:
        destinos.append(company.contact_email.strip())
    rows = (
        await db.execute(
            select(User.email).join(Booker, Booker.user_id == User.id)
            .where(Booker.company_id == company_id, User.is_active.is_(True))
        )
    ).scalars().all()
    destinos += [e.strip() for e in rows if e]
    # Sin repetir y sin distinguir mayúsculas, conservando el orden.
    vistos: set[str] = set()
    out: list[str] = []
    for d in destinos:
        if d and d.lower() not in vistos:
            vistos.add(d.lower())
            out.append(d)
    return out


# --- Plantillas -----------------------------------------------------------

def _sin_marcas(v: str) -> str:
    """El HTML convertido a texto plano legible.

    Los <br> se convierten en saltos de linea ANTES de quitar las etiquetas. Si
    solo se borran, el texto plano sale con las frases pegadas ("...la
    solicitud.Gracias por formar parte...") y hay clientes de correo que leen
    unicamente esa version.
    """
    v = re.sub(r"<br\s*/?>", "\n", v, flags=re.I)
    v = re.sub(r"</p\s*>", "\n\n", v, flags=re.I)
    texto = _html.unescape(re.sub(r"<[^>]+>", "", v))
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _e(v: str | None) -> str:
    """Todo lo que viene de la base va escapado: el nombre de un show o un
    mensaje del chat no pueden meter etiquetas en el correo."""
    return _html.escape(v or "", quote=False)


def _panel_url() -> str:
    return settings.PUBLIC_BASE_URL.rstrip("/")


def _boton(texto: str, url: str) -> str:
    return (
        f'<p style="text-align:center;margin:26px 0"><a href="{url}" '
        'style="background:#111827;color:#fff;text-decoration:none;padding:13px 26px;'
        'border-radius:9px;font-weight:600;display:inline-block">'
        f"{texto}</a></p>"
    )


def _ficha(filas: list[tuple[str, str]]) -> str:
    """Tabla de datos de la actuación (fecha, lugar, etc.)."""
    tr = "".join(
        f'<tr><td style="padding:7px 0;color:#6b7280;width:38%">{k}</td>'
        f'<td style="padding:7px 0;color:#111827;font-weight:600">{_e(v)}</td></tr>'
        for k, v in filas
        if v
    )
    return (
        '<table style="width:100%;border-collapse:collapse;font-size:14px;'
        'background:#f7f8fa;border-radius:10px;padding:4px 14px;margin:18px 0">'
        f"{tr}</table>"
    )


def _mk(titulo: str, parrafo: str, filas: list[tuple[str, str]], cta: str, url: str,
        cierre: str = "") -> tuple[str, str]:
    """(texto plano, html) de un aviso de actuación.

    ``parrafo`` y ``cierre`` llegan con marcas (<b>) para el HTML; la versión de
    texto plano las quita, que hay clientes de correo que sólo leen esa.
    """
    plano = [_sin_marcas(parrafo), ""]
    plano += [f"{k}: {v}" for k, v in filas if v]
    if cierre:
        plano += ["", _sin_marcas(cierre)]
    plano += ["", f"Entra a tu panel: {url}", "", _FIRMA_PLANO]
    html = (
        f"<p>{parrafo}</p>"
        + _ficha(filas)
        + (f'<p style="color:#6b7280;font-size:13px">{cierre}</p>' if cierre else "")
        + _boton(cta, url)
    )
    return "\n".join(plano), mailer.wrap(html, footer=(
        f"{_FIRMA}<br><br>"
        "Recibes este correo porque tienes una cuenta en SHOWMA. "
        "Puedes ver y responder todo desde tu panel."
    ))


_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _dia_largo(dt: datetime | None) -> str:
    """"jueves, 12 de octubre de 2026". David pide "Dia y fecha"."""
    if dt is None:
        return ""
    d = dt.replace(tzinfo=None) if dt.tzinfo else dt
    return f"{_DIAS[d.weekday()]}, {d.day} de {_MESES[d.month - 1]} de {d.year}"


def _horario(ini: datetime | None, fin: datetime | None) -> str:
    """"20:00 - 21:30", o solo la hora de inicio si no se sabe cuando termina."""
    if ini is None:
        return ""
    a = (ini.replace(tzinfo=None) if ini.tzinfo else ini).strftime("%H:%M")
    if fin is None:
        return a
    b = (fin.replace(tzinfo=None) if fin.tzinfo else fin).strftime("%H:%M")
    return f"{a} - {b}"


def _fmt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    d = dt.replace(tzinfo=None) if dt.tzinfo else dt
    return d.strftime("%d/%m/%Y a las %H:%M")


# La firma con la que cierran todos los avisos. David, 08/10.
_FIRMA = "SHOWMA<br><span style=\"color:#8b93a1\">People Create Experiences</span>"
_FIRMA_PLANO = "SHOWMA\nPeople Create Experiences"


def actuacion(kind: str, *, show: str, venue: str, hotel: str, cuando: datetime | None,
              importe: str = "", motivo: str = "", artista: str = "",
              termina: datetime | None = None) -> tuple[str, str, str]:
    """(asunto, texto, html) del aviso al MÚSICO sobre una actuación.

    kind: new_booking | confirmed | reschedule | cancelled
    """
    filas = [
        ("Show", show),
        ("Lugar", f"{venue} · {hotel}" if hotel and venue else (venue or hotel)),
        ("Fecha y hora", _fmt(cuando)),
    ]
    if importe:
        filas.append(("Importe acordado", importe))
    url = _panel_url()

    if kind == "reschedule":
        asunto = f"Cambio de horario: {show}"
        texto, html = _mk(
            asunto, f"Tu actuación de <b>{_e(show)}</b> cambió de horario.", filas,
            "Ver mi agenda", url,
            "Si el nuevo horario no te funciona, avísale al hotel cuanto antes desde el chat.",
        )
    elif kind == "confirmed":
        asunto = f"Actuación confirmada: {show}"
        texto, html = _mk(
            asunto, f"Tu actuación de <b>{_e(show)}</b> quedó <b>confirmada</b>.", filas,
            "Ver mi agenda", url,
            "Recuerda avisar por la plataforma cuando vayas en camino y cuando llegues.",
        )
    elif kind == "cancelled":
        # Redaccion de David (08/10). Sus campos y su orden: Hotel, Fecha,
        # Horario, Propuesta. No son los mismos que en los otros avisos, y es a
        # proposito: aqui lo que el musico necesita de un vistazo es QUE dia se
        # le ha caido de la agenda.
        asunto = "Tu actuación ha sido cancelada"
        saludo = f"Hola, {_e(artista)}:" if artista else "Hola:"
        quien = f"<b>{_e(hotel)}</b>" if hotel else "El hotel"
        filas = [
            ("Hotel", hotel),
            ("Fecha", _dia_largo(cuando)),
            ("Horario", _horario(cuando, termina)),
            ("Propuesta", show),
        ]
        cierre = (
            "La cancelación ha sido solicitada por el cliente y ya se encuentra "
            "registrada en SHOWMA."
            + (f"<br><br>Motivo indicado: {_e(motivo)}" if motivo else "")
            + "<br><br><b>No es necesario que te presentes en la propiedad.</b>"
            "<br><br>Puedes consultar los detalles de la cancelación y, si "
            "corresponde, las condiciones económicas aplicables desde tu perfil."
            "<br><br>Lamentamos los inconvenientes que este cambio pueda "
            "ocasionarte."
            "<br><br>Tu perfil y disponibilidad permanecen activos para recibir "
            "nuevas oportunidades."
        )
        texto, html = _mk(
            asunto,
            f"{saludo}<br><br>Te informamos de que {quien} ha cancelado la "
            "siguiente actuación:",
            filas, "Ver cancelación en SHOWMA", url, cierre,
        )
    else:  # new_booking
        # Redaccion de David (08/10), tal cual la escribio.
        asunto = "¡Tienes una nueva solicitud!"
        saludo = f"Hola, {_e(artista)}:" if artista else "Hola:"
        quien = f"<b>{_e(hotel)}</b>" if hotel else "Un hotel"
        texto, html = _mk(
            asunto,
            f"{saludo}<br><br>{quien} quiere contar contigo para una próxima "
            "actuación. Entra en tu perfil de SHOWMA para revisar todos los "
            "detalles y confirmar o rechazar la solicitud.",
            filas,
            "Revisar la solicitud", url,
            "Recuerda que tu disponibilidad no quedará confirmada hasta que "
            "aceptes la solicitud.<br><br>Gracias por formar parte de SHOWMA.",
        )
    return asunto, texto, html


def cancelacion_musico(*, show: str, artista: str, venue: str, cuando: datetime | None,
                       motivo: str = "") -> tuple[str, str, str]:
    """(asunto, texto, html) del aviso al HOTEL: el músico canceló.

    Es el aviso más urgente del sistema: alguien tiene que salir a buscar
    reemplazo, y ese alguien no está mirando la plataforma un sábado a las 7.
    """
    asunto = f"El músico canceló: {show} del {_fmt(cuando)}"
    filas = [
        ("Show", show),
        ("Artista", artista),
        ("Lugar", venue),
        ("Fecha y hora", _fmt(cuando)),
    ]
    if motivo:
        filas.append(("Motivo", motivo))
    texto, html = _mk(
        asunto,
        f"<b>{_e(artista)}</b> canceló la actuación de <b>{_e(show)}</b>.",
        filas, "Buscar reemplazo", _panel_url(),
        "Desde la actuación puedes ver los artistas disponibles a esa misma hora "
        "y reemplazarlo en un par de clics.",
    )
    return asunto, texto, html


def confirmacion_musico(*, show: str, artista: str, venue: str,
                        cuando: datetime | None) -> tuple[str, str, str]:
    """(asunto, texto, html) del aviso al HOTEL: el músico aceptó."""
    asunto = f"{artista} confirmó: {show}"
    filas = [
        ("Show", show),
        ("Artista", artista),
        ("Lugar", venue),
        ("Fecha y hora", _fmt(cuando)),
    ]
    texto, html = _mk(
        asunto, f"<b>{_e(artista)}</b> confirmó su actuación.", filas,
        "Ver el calendario", _panel_url(),
    )
    return asunto, texto, html


def mensaje_chat(*, de: str, extracto: str) -> tuple[str, str, str]:
    """(asunto, texto, html) del aviso de mensaje nuevo en el chat."""
    asunto = f"Mensaje nuevo de {de}"
    cuerpo = (
        f"<p><b>{_e(de)}</b> te escribió por el chat de SHOWMA:</p>"
        f'<blockquote style="margin:16px 0;padding:12px 16px;background:#f7f8fa;'
        f'border-left:3px solid #111827;border-radius:0 8px 8px 0;color:#374151">'
        f"{_e(extracto)}</blockquote>"
        + _boton("Responder", _panel_url())
    )
    texto = (
        f"{de} te escribió por el chat de SHOWMA:\n\n"
        f"{extracto}\n\n"
        f"Responde desde tu panel: {_panel_url()}\n\n— SHOWMA"
    )
    return asunto, texto, mailer.wrap(cuerpo, footer=(
        "Sólo avisamos del primer mensaje sin leer de cada conversación, "
        "para no llenarte el correo."
    ))


def prueba() -> tuple[str, str, str]:
    """(asunto, texto, html) del correo de prueba de Master."""
    asunto = "Correo de prueba de SHOWMA"
    cuerpo = (
        "<p>Si estás leyendo esto, el envío de correos de SHOWMA está bien "
        "configurado.</p>"
        "<p>A partir de ahora los músicos y los hoteles reciben en su correo los "
        "avisos de actuaciones (nueva, confirmada, cambio de horario, cancelación) "
        "y de mensajes nuevos en el chat, sin necesidad de entrar a la "
        "plataforma.</p>"
        + _boton("Abrir SHOWMA", _panel_url())
    )
    texto = (
        "Si estás leyendo esto, el envío de correos de SHOWMA está bien configurado.\n\n"
        f"Panel: {_panel_url()}\n\n— SHOWMA"
    )
    return asunto, texto, mailer.wrap(cuerpo, footer="Correo de prueba enviado desde Master.")


def pase_actuacion(*, show: str, artista: str, venue: str, hotel: str,
                   cuando: datetime | None, folio: str | None,
                   integrantes: int | None, url_pase: str) -> tuple[str, str, str]:
    """(asunto, texto, html) de la confirmación con el PASE DE ACCESO.

    David, 06/10: "una confirmación por mail ademas de la registrada en el web,
    tal y como cuando reservamos un billete de avión u hotel. Este mail debería
    tener un QR para que personal de seguridad pueda verificar quién llega".

    El QR se incrusta con ``cid:qrpase`` y la imagen la pasa quien envía, en el
    parámetro ``imagenes`` de mailer.send. Ver allí por qué no es un data: URI.

    Y pase lo que pase con la imagen, LA DIRECCIÓN DEL PASE VA ESCRITA. Un
    correo cuyo QR no se pinta -porque el cliente de correo es raro, porque se
    reenvió como texto plano, porque el de la caseta lo abrió en un móvil de
    2015- tiene que seguir sirviendo. Por eso el enlace está a la vista y no
    sólo detrás del botón.
    """
    filas = [
        ("Orden", folio or ""),
        ("Show", show),
        ("Proveedor", artista),
        ("Lugar", f"{venue} · {hotel}" if hotel and venue else (venue or hotel)),
        ("Fecha y hora", _fmt(cuando)),
        ("Personas que llegan", str(integrantes) if integrantes else ""),
    ]

    # Redaccion de David (08/10), con sus correcciones del mismo dia:
    # "Presenta este codigo cuando llegues a la propiedad, su lectura permitira
    #  tu entrada y la hora de llegada"
    # "Una vez finalizada la actuacion, el CLIENTE confirmara la realizacion del
    #  servicio para continuar con el proceso de facturacion y pago"
    #
    # Va SOLO al proveedor. El hotel no lo recibe por correo a proposito: ya lo
    # tiene en el sistema, y reenviarle 3-5 pases al dia a seguridad acabaria en
    # el olvido (David, 07/10).
    saludo = f"Hola, {_e(artista)}:" if artista else "Hola:"
    donde = f"en <b>{_e(hotel)}</b>" if hotel else ""
    intro = (f"{saludo}<br><br>Tu actuación {donde} está confirmada y ya tienes "
             "disponible tu pase de acceso.")
    cierre = (
        "Presenta este código cuando llegues a la propiedad, su lectura "
        "permitirá tu entrada y la hora de llegada."
        "<br><br><b>Importante:</b> Si tu actuación incluye varios integrantes, "
        "revisa que todos estén registrados y autorizados. El QR es personal y "
        "no debe compartirse con terceros."
        "<br><br>Una vez finalizada la actuación, el cliente confirmará la "
        "realización del servicio para continuar con el proceso de facturación "
        "y pago."
        "<br><br>¡Que tengas una excelente actuación!"
    )

    qr_html = (
        '<div style="text-align:center;margin:22px 0">'
        '<div style="font-size:11px;font-weight:800;letter-spacing:2px;color:#6b7280;margin-bottom:10px">TU PASE DE ACCESO</div>'
        '<img src="cid:qrpase" alt="Pase de acceso" '
        'style="width:190px;height:190px;border:1px solid #e6e8ec;border-radius:10px">'
        f'<div style="font-size:12px;color:#6b7280;margin-top:6px">Pase {_e(folio or "")}</div>'
        "</div>"
    )
    enlace_visible = (
        '<p style="font-size:12.5px;color:#6b7280;word-break:break-all;text-align:center">'
        f'Si el código no se ve: <a href="{url_pase}" style="color:#382ca1">{url_pase}</a></p>'
    )

    asunto = "¡Todo listo para tu próxima actuación!"
    html = (
        f"<p>{intro}</p>"
        + _ficha(filas)
        + qr_html
        + _boton("Abrir el pase", url_pase)
        + enlace_visible
        + f'<p style="color:#6b7280;font-size:13px">{cierre}</p>'
    )
    plano = [
        _sin_marcas(intro), "",
        *[f"{k}: {v}" for k, v in filas if v],
        "",
        f"Pase de acceso: {url_pase}",
        "",
        _sin_marcas(cierre),
        "", _FIRMA_PLANO,
    ]
    return asunto, "\n".join(plano), mailer.wrap(html, footer=(
        f"{_FIRMA}<br><br>"
        "Recibes este correo porque tienes una actuación agendada en SHOWMA."
    ))
