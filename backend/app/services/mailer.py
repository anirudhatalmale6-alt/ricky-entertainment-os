"""Envío de correo (SMTP).

SHOWMA no dependía de correo hasta ahora: todos los avisos viven dentro de la
plataforma. La recuperación de contraseña sí lo necesita, así que esto es un
envío mínimo por SMTP con la configuración en el .env.

Si no hay SMTP configurado la plataforma NO se rompe: ``send()`` devuelve False
y quien llama decide qué hacer (en el caso de la recuperación, el enlace queda
disponible para que MASTER se lo pase al usuario). smtplib es bloqueante, así
que va en un hilo para no parar el event loop.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings

log = logging.getLogger(__name__)


def usa_mailgun() -> bool:
    return bool(settings.MAILGUN_API_KEY and settings.MAILGUN_DOMAIN)


def is_configured() -> bool:
    return bool(usa_mailgun() and settings.mail_from) or bool(
        settings.SMTP_HOST and settings.mail_from)


def _mailgun_url() -> str:
    """La región NO es cosmética: una cuenta creada en Europa responde 401
    contra la dirección de Estados Unidos, y ese 401 se lee como clave mala."""
    host = ("api.eu.mailgun.net" if (settings.MAILGUN_REGION or "us").lower() == "eu"
            else "api.mailgun.net")
    return f"https://{host}/v3/{settings.MAILGUN_DOMAIN}/messages"


def _mailgun_payload(to: str, subject: str, text: str, html: str | None,
                     imagenes: dict[str, bytes] | None):
    """(data, files) de la petición. Separado del envío para poder revisarlo en
    una prueba sin tocar la red."""
    data = {
        "from": formataddr((settings.SMTP_FROM_NAME, settings.mail_from)),
        "to": to,
        "subject": subject,
        "text": text,
    }
    if html:
        data["html"] = html
    files = []
    for nombre, datos in (imagenes or {}).items():
        # Mailgun usa el NOMBRE DEL ARCHIVO como Content-ID de una imagen
        # "inline". Por eso el archivo se llama igual que el cid que referencia
        # el HTML (cid:qrpase) y NO qrpase.png: si le pongo la extensión, el
        # cid pasa a ser "qrpase.png", deja de coincidir, y llega el hueco
        # blanco donde va el código. Es el mismo fallo silencioso que por SMTP.
        files.append(("inline", (nombre, datos, "image/png")))
    return data, files


async def _send_mailgun(to: str, subject: str, text: str, html: str | None,
                        imagenes: dict[str, bytes] | None) -> None:
    import httpx

    data, files = _mailgun_payload(to, subject, text, html, imagenes)
    async with httpx.AsyncClient(timeout=20) as cli:
        r = await cli.post(_mailgun_url(), auth=("api", settings.MAILGUN_API_KEY),
                           data=data, files=files or None)
        r.raise_for_status()


def _send_sync(to: str, subject: str, text: str, html: str | None,
               imagenes: dict[str, bytes] | None = None) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.mail_from))
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    # Imágenes incrustadas (el QR del pase). Van como adjunto con Content-ID y
    # se referencian con <img src="cid:nombre">.
    #
    # NO se usa un data: URI, que es lo primero que uno piensa: Gmail las
    # descarta enteras y el correo llega con un hueco. Tampoco una URL contra
    # nuestro servidor, que casi todos los clientes bloquean hasta que el
    # usuario pulsa "mostrar imágenes" — y un QR que hay que desbloquear para
    # verlo no sirve en una caseta de vigilancia. El cid es lo único que pinta
    # solo en Gmail, Outlook y el correo del iPhone.
    if imagenes and html:
        parte = msg.get_payload()[-1]          # la alternativa HTML
        for nombre, datos in imagenes.items():
            parte.add_related(datos, maintype="image", subtype="png",
                              cid=f"<{nombre}>", filename=f"{nombre}.png")

    mode = (settings.SMTP_SECURITY or "starttls").lower()
    if mode == "ssl":
        server = smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=20,
            context=ssl.create_default_context(),
        )
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
    with server:
        if mode == "starttls":
            server.starttls(context=ssl.create_default_context())
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


async def send(to: str, subject: str, text: str, html: str | None = None,
               imagenes: dict[str, bytes] | None = None) -> bool:
    """True si el correo salió. Nunca lanza: un fallo de SMTP no puede tumbar
    una petición del usuario."""
    if not is_configured():
        log.warning("SMTP no configurado; no se envió '%s' a %s", subject, to)
        return False
    try:
        if usa_mailgun():
            # Por HTTPS, que es lo único que sale del droplet.
            await _send_mailgun(to, subject, text, html, imagenes)
        else:
            await asyncio.to_thread(_send_sync, to, subject, text, html, imagenes)
        return True
    except Exception:  # noqa: BLE001 - se registra y se sigue
        log.exception("Falló el envío de '%s' a %s", subject, to)
        return False


# --- Plantillas -----------------------------------------------------------

_WRAP = """<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
 background:#f4f5f7;padding:28px 12px">
 <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:14px;
  overflow:hidden;border:1px solid #e6e8ec">
  <div style="background:#111827;color:#fff;padding:18px 24px">
   <div style="font-size:21px;font-weight:800;letter-spacing:1px;line-height:1">SHOWMA</div>
   <div style="font-size:10px;letter-spacing:3px;opacity:.65;margin-top:3px">ENTERTAINMENT OS</div>
  </div>
  <div style="padding:24px;color:#1f2937;font-size:15px;line-height:1.55">{body}</div>
  <div style="padding:16px 24px;background:#fafafa;color:#8b93a1;font-size:12px;
   border-top:1px solid #eef0f3">{footer}</div>
 </div></div>"""

_PIE_RESET = ("Si no solicitaste esto puedes ignorar este correo, tu contraseña "
              "no cambiará.")


def wrap(body: str, footer: str = _PIE_RESET) -> str:
    """Envuelve un cuerpo HTML en la plantilla de marca de SHOWMA."""
    return _WRAP.format(body=body, footer=footer)


def reset_email(full_name: str, link: str, minutes: int) -> tuple[str, str, str]:
    """(asunto, texto plano, html) del correo de recuperación."""
    subject = "Recupera tu contraseña de SHOWMA"
    text = (
        f"Hola {full_name}:\n\n"
        "Recibimos una solicitud para restablecer la contraseña de tu cuenta "
        "en SHOWMA. Abre este enlace para crear una nueva:\n\n"
        f"{link}\n\n"
        f"El enlace caduca en {minutes} minutos y sólo se puede usar una vez.\n\n"
        "Si no fuiste tú, ignora este correo: tu contraseña no cambiará.\n\n"
        "— Equipo SHOWMA"
    )
    body = (
        f"<p>Hola <b>{full_name}</b>:</p>"
        "<p>Recibimos una solicitud para restablecer la contraseña de tu cuenta "
        "en SHOWMA. Pulsa el botón para crear una nueva:</p>"
        f'<p style="text-align:center;margin:26px 0"><a href="{link}" '
        'style="background:#111827;color:#fff;text-decoration:none;padding:13px 26px;'
        'border-radius:9px;font-weight:600;display:inline-block">'
        "Crear nueva contraseña</a></p>"
        f'<p style="color:#6b7280;font-size:13px">El enlace caduca en {minutes} '
        "minutos y sólo se puede usar una vez. Si el botón no funciona, copia y "
        f'pega esta dirección:<br><span style="word-break:break-all">{link}</span></p>'
    )
    return subject, text, wrap(body)
