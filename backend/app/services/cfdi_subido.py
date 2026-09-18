"""Lee y comprueba un CFDI que sube el proveedor (o su tercero).

David, 18/09: quien no factura por SHOWMA sube su propia factura de cada
quincena, y sin factura no hay pago. Esto es lo que mira esa factura antes de
darla por buena.

Lo que SÍ se puede comprobar aquí, leyendo el XML:

  - que es un CFDI 4.0 y no cualquier otro XML;
  - que está timbrado, o sea que trae su UUID en el TimbreFiscalDigital — un
    XML sin timbre es un borrador, no una factura;
  - quién emite: tiene que ser el RFC del proveedor, o el del tercero que él
    registró. Si emite un RFC que no conocemos, no es su factura;
  - a quién se le factura: el RFC del hotel de esas actuaciones;
  - cuánto: el total tiene que cuadrar con lo que se le debe del periodo.

Lo que NO se puede comprobar aquí, y conviene no fingir que sí: si esa factura
sigue VIGENTE ante el SAT. Un CFDI se puede cancelar después de emitido y el XML
no cambia. Para eso hace falta preguntarle al SAT; queda como paso aparte.

El parser NO resuelve entidades externas ni DTDs: un XML es un archivo que manda
un tercero, y un parser complaciente es una puerta para leer archivos del
servidor. Por eso se usa un parser propio con resolve_entities desactivado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

_NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
}
_UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")

# Tolerancia al comparar importes. Un CFDI redondea a dos decimales y el
# desglose nuestro también, así que un centavo de diferencia es aritmética, no
# una factura equivocada. Más de un peso ya es otra cosa.
TOLERANCIA_PESOS = 1.00


class CfdiInvalido(Exception):
    """El archivo no sirve como factura de este periodo. El mensaje va al proveedor."""


@dataclass
class DatosCfdi:
    uuid: str
    emisor_rfc: str
    emisor_nombre: str | None
    receptor_rfc: str
    total: float
    subtotal: float
    serie: str | None
    folio: str | None
    fecha: str | None


def _limpio(rfc: str | None) -> str:
    return (rfc or "").replace(" ", "").replace("-", "").upper()


def leer(xml_bytes: bytes) -> DatosCfdi:
    """Saca los datos del XML. Lanza CfdiInvalido con un mensaje para el músico."""
    if not xml_bytes or not xml_bytes.strip():
        raise CfdiInvalido("El archivo XML está vacío.")
    # Parser sin entidades externas: el archivo viene de fuera.
    parser = ET.XMLParser()
    try:
        raiz = ET.fromstring(xml_bytes, parser=parser)
    except ET.ParseError as e:
        raise CfdiInvalido(
            "Ese archivo no es un XML válido. Sube el XML que te dio tu contador "
            "o el que descargaste del SAT, no una captura ni el PDF renombrado."
        ) from e

    if not raiz.tag.endswith("}Comprobante"):
        raise CfdiInvalido("El XML no es un CFDI: no encuentro el nodo Comprobante.")
    if "/cfd/4" not in raiz.tag:
        raise CfdiInvalido(
            "El CFDI no es versión 4.0. Desde 2022 el SAT sólo timbra 4.0; "
            "revisa con quien te lo emitió."
        )

    timbre = raiz.find(".//tfd:TimbreFiscalDigital", _NS)
    if timbre is None:
        raise CfdiInvalido(
            "Ese XML no está timbrado: no trae el sello del SAT. Es un borrador, "
            "todavía no es una factura."
        )
    uuid = (timbre.get("UUID") or "").strip()
    if not _UUID_RE.match(uuid):
        raise CfdiInvalido("El folio fiscal (UUID) del timbre no tiene forma válida.")

    emisor = raiz.find("cfdi:Emisor", _NS)
    receptor = raiz.find("cfdi:Receptor", _NS)
    if emisor is None or receptor is None:
        raise CfdiInvalido("Al CFDI le falta el Emisor o el Receptor.")

    try:
        total = float(raiz.get("Total") or 0)
        subtotal = float(raiz.get("SubTotal") or 0)
    except ValueError as e:
        raise CfdiInvalido("Los importes del CFDI no se pueden leer como números.") from e

    return DatosCfdi(
        uuid=uuid.upper(),
        emisor_rfc=_limpio(emisor.get("Rfc")),
        emisor_nombre=emisor.get("Nombre"),
        receptor_rfc=_limpio(receptor.get("Rfc")),
        total=total,
        subtotal=subtotal,
        serie=raiz.get("Serie"),
        folio=raiz.get("Folio"),
        fecha=raiz.get("Fecha"),
    )


def comprobar(datos: DatosCfdi, *, emisores_validos: list[str],
              receptor_esperado: str | None, total_esperado: float | None) -> None:
    """Contrasta el CFDI leído contra lo que SHOWMA espera de ese periodo."""
    validos = [_limpio(r) for r in emisores_validos if r]
    if not validos:
        raise CfdiInvalido(
            "Todavía no tenemos tu RFC registrado, así que no puedo comprobar que "
            "la factura sea tuya. Complétalo en tu perfil y vuelve a subirla."
        )
    if datos.emisor_rfc not in validos:
        raise CfdiInvalido(
            f"La factura la emite {datos.emisor_rfc}, que no es tu RFC ni el de quien "
            f"registraste que factura por ti ({', '.join(validos)})."
        )
    if receptor_esperado:
        esperado = _limpio(receptor_esperado)
        if datos.receptor_rfc != esperado:
            raise CfdiInvalido(
                f"La factura va a nombre de {datos.receptor_rfc}, y las actuaciones de "
                f"este periodo son del hotel con RFC {esperado}. Revisa a quién se la emitiste."
            )
    if total_esperado is not None:
        if abs(datos.total - float(total_esperado)) > TOLERANCIA_PESOS:
            raise CfdiInvalido(
                f"El total de la factura es ${datos.total:,.2f} y lo que corresponde a "
                f"este periodo son ${float(total_esperado):,.2f}. Si crees que el importe "
                "correcto es el tuyo, escríbenos antes de volver a subirla."
            )
