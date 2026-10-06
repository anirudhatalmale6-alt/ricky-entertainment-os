"""El pase de acceso de una actuación: el QR que enseña quién llega.

David, 06/10: la orden de actuación debe llegar con un QR "como cuando reservamos
un billete de avión", para que el personal de seguridad del hotel vea quién
llega, en qué estado está la actuación, a qué hora y cuántos integrantes son, y
pueda confirmar que llegó.

Dos decisiones que están metidas en la forma de este archivo:

1. EL TOKEN NO ES EL FOLIO. El folio (OA-2026-00147) es correlativo: quien tenga
   uno puede adivinar los demás sumando uno. La página del pase es pública -tiene
   que serlo, el de seguridad no tiene cuenta en SHOWMA- así que lo que viaja en
   el QR es un token aleatorio de 32 caracteres. El folio se SE ENSEÑA dentro,
   que es donde sirve, pero no es la llave.

2. LA PÁGINA ENSEÑA LO JUSTO. Quién llega, cuántos son, cuándo, en qué salón y
   el estado. Ni el precio, ni la comisión, ni el teléfono del músico, ni el
   correo de nadie. Es una página pública: hay que leerla pensando en que la
   puede abrir cualquiera a quien le reenvíen el mensaje.
"""
from __future__ import annotations

import base64
import io
import secrets
from datetime import datetime

def nuevo_token() -> str:
    """32 caracteres hexadecimales = 128 bits. No se adivina.

    Hexadecimal y no url-safe a propósito: es la misma forma que produce
    ``lower(hex(randomblob(16)))`` en SQLite, que es lo que rellena los pases de
    las órdenes que ya existían. Un solo formato, un solo sitio donde mirar.
    """
    return secrets.token_hex(16)


def url_pase(token: str, base: str | None = None) -> str:
    """La dirección que lleva el QR."""
    raiz = (base or "").rstrip("/")
    return f"{raiz}/pase/{token}"


def png_qr(texto: str, escala: int = 8) -> bytes:
    """El QR como PNG.

    Corrección de errores M: aguanta que el papel se ensucie o se arrugue, que
    es lo que le va a pasar a una hoja en una caseta de vigilancia, sin hacer el
    código tan grande que no quepa en el correo.
    """
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M,
                       box_size=escala, border=2)
    qr.add_data(texto)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1b1f2e", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_data_uri(texto: str, escala: int = 6) -> str:
    """El mismo QR, embebido. Para el correo: un <img src="https://…"> contra
    nuestro servidor lo bloquea casi todo cliente de correo hasta que el usuario
    pulsa "mostrar imágenes", y un pase que hay que desbloquear para verlo no
    sirve de nada en una caseta de vigilancia."""
    return "data:image/png;base64," + base64.b64encode(png_qr(texto, escala)).decode()


# --- Lo que ve el de seguridad --------------------------------------------

ESTADOS = {
    "pending": ("Pendiente de que el proveedor acepte", "pend"),
    "confirmed": ("Confirmada", "ok"),
    "completed": ("Realizada", "ok"),
    "cancelled": ("CANCELADA", "mal"),
    "no_show": ("Marcada como no completada", "mal"),
}


def puede_pasar(status: str, llegada_at: datetime | None = None) -> bool:
    """¿Seguridad debe dejar pasar a esta gente?

    Sólo con la actuación confirmada o ya realizada. Una pendiente todavía no la
    aceptó el proveedor y una cancelada no debería presentarse: en los dos casos
    el pase sale en rojo y el de la caseta llama a quien contrató, que es
    exactamente el control que hoy no existe.
    """
    return status in ("confirmed", "completed")
