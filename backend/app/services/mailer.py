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


def is_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.mail_from)


def _send_sync(to: str, subject: str, text: str, html: str | None) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.mail_from))
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

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


async def send(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """True si el correo salió. Nunca lanza: un fallo de SMTP no puede tumbar
    una petición del usuario."""
    if not is_configured():
        log.warning("SMTP no configurado; no se envió '%s' a %s", subject, to)
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, text, html)
        return True
    except Exception:  # noqa: BLE001 - se registra y se sigue
        log.exception("Falló el envío de '%s' a %s", subject, to)
        return False


# --- Plantillas -----------------------------------------------------------

_WRAP = """<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
 background:#f4f5f7;padding:28px 12px">
 <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:14px;
  overflow:hidden;border:1px solid #e6e8ec">
  <div style="background:#111827;color:#fff;padding:20px 24px;font-size:20px;
   font-weight:700;letter-spacing:.5px">SHOWMA</div>
  <div style="padding:24px;color:#1f2937;font-size:15px;line-height:1.55">{body}</div>
  <div style="padding:16px 24px;background:#fafafa;color:#8b93a1;font-size:12px;
   border-top:1px solid #eef0f3">Si no solicitaste esto puedes ignorar este
   correo, tu contraseña no cambiará.</div>
 </div></div>"""


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
    return subject, text, _WRAP.format(body=body)
