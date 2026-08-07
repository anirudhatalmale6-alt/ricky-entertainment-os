"""Facturama CFDI (e-invoicing) client — modalidad MULTIEMISOR.

SHOWMA emite CFDI reales a nombre de cada músico. En la modalidad Multiemisor
cada músico factura con su propio RFC: sube su CSD (Certificado de Sello Digital:
.cer + .key + contraseña) UNA sola vez y, a partir de ahí, el timbrado de cada
actuación es automático — el músico no hace nada manual (requisito de David).

Todos los recursos Multiemisor viven bajo /api-lite/ con autenticación HTTP Basic.
Endpoints usados (confirmados contra el sandbox 2026-08-07):
  CSD:   GET/POST /api-lite/csds · GET/PUT/DELETE /api-lite/csds/{rfc}
  CFDI:  POST /api-lite/3/cfdis (timbrado 4.0) · GET /api/Cfdi/{fmt}/IssuedLite/{id}
         DELETE /api-lite/cfdis/{id}?motive=.. (cancelación)

Este módulo NO decide importes ni reglas de negocio; sólo habla con Facturama.
El cálculo del desglose (honorarios − comisión, IVA trasladado, retenciones) lo
arma quien llama, para que coincida con la pantalla de Facturación.
"""
from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.config import settings


class FacturamaError(Exception):
    """Error de negocio devuelto por Facturama (RFC/CSD inválido, timbrado, etc.).

    `message` es apto para mostrar al usuario; `detail` guarda el cuerpo crudo
    para el log. `status_code` es el HTTP de Facturama (None si no hubo respuesta).
    """

    def __init__(self, message: str, *, detail: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.status_code = status_code


class FacturamaNotConfigured(FacturamaError):
    """La integración de facturación aún no tiene credenciales configuradas."""

    def __init__(self) -> None:
        super().__init__(
            "La facturación electrónica todavía no está configurada. "
            "Contacta al administrador."
        )


def _extract_error_message(status_code: int, body: Any) -> str:
    """Convierte una respuesta de error de Facturama en un texto entendible.

    Facturama devuelve o bien {"Message": "..."} o bien un ModelState con la
    validación por campo (RFC obligatorio, régimen no aplica, total incorrecto…).
    """
    if isinstance(body, dict):
        model_state = body.get("ModelState")
        if isinstance(model_state, dict):
            msgs: list[str] = []
            for field, errs in model_state.items():
                if isinstance(errs, list):
                    msgs.extend(str(e) for e in errs)
            if msgs:
                return " · ".join(dict.fromkeys(msgs))[:600]
        msg = body.get("Message") or body.get("message")
        if msg:
            return str(msg)[:600]
    if isinstance(body, str) and body.strip():
        return body.strip()[:600]
    return f"Facturama respondió con un error (HTTP {status_code})."


class FacturamaClient:
    """Cliente async ligero sobre la API de Facturama (Multiemisor)."""

    def __init__(
        self,
        user: str | None = None,
        password: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._user = user if user is not None else settings.FACTURAMA_USER
        self._password = password if password is not None else settings.FACTURAMA_PASSWORD
        self._base_url = (base_url or settings.facturama_base_url).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(settings.FACTURAMA_ENABLED and self._user and self._password)

    def _client(self) -> httpx.AsyncClient:
        if not self.configured:
            raise FacturamaNotConfigured()
        return httpx.AsyncClient(
            base_url=self._base_url,
            auth=(self._user, self._password),
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(45.0),
        )

    async def _request(self, method: str, path: str, *, json: Any = None, params: Any = None) -> Any:
        async with self._client() as client:
            try:
                resp = await client.request(method, path, json=json, params=params)
            except httpx.HTTPError as exc:  # red/timeout
                raise FacturamaError(
                    "No se pudo conectar con el servicio de facturación. "
                    "Inténtalo de nuevo en un momento."
                ) from exc

        ctype = resp.headers.get("content-type", "").lower()
        body: Any = resp.json() if "application/json" in ctype else resp.text

        if resp.status_code in (200, 201, 204):
            return body
        raise FacturamaError(
            _extract_error_message(resp.status_code, body),
            detail=body,
            status_code=resp.status_code,
        )

    # --- CSD (emisor por RFC) ---------------------------------------------

    async def get_csd(self, rfc: str) -> dict | None:
        """Devuelve el CSD registrado para un RFC, o None si no existe."""
        try:
            return await self._request("GET", f"/api-lite/csds/{rfc.upper()}")
        except FacturamaError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def upload_csd(
        self, rfc: str, cer_bytes: bytes, key_bytes: bytes, password: str
    ) -> dict:
        """Registra (o reemplaza) el CSD de un RFC.

        `cer_bytes`/`key_bytes` son el contenido binario de los archivos .cer y
        .key; aquí se codifican a base64 como pide Facturama. Si Facturama acepta
        el certificado, el RFC queda listo para timbrar. Un CSD inválido (o una
        contraseña equivocada) devuelve FacturamaError con el motivo.
        """
        rfc = rfc.upper()
        payload = {
            "Rfc": rfc,
            "Certificate": base64.b64encode(cer_bytes).decode("ascii"),
            "PrivateKey": base64.b64encode(key_bytes).decode("ascii"),
            "PrivateKeyPassword": password,
        }
        # Si ya hay uno cargado, reemplazamos con PUT; si no, POST.
        existing = await self.get_csd(rfc)
        if existing:
            return await self._request("PUT", f"/api-lite/csds/{rfc}", json=payload)
        return await self._request("POST", "/api-lite/csds", json=payload)

    async def delete_csd(self, rfc: str) -> None:
        await self._request("DELETE", f"/api-lite/csds/{rfc.upper()}")

    # --- CFDI (timbrado) ---------------------------------------------------

    async def stamp_cfdi(self, cfdi: dict) -> dict:
        """Timbra un CFDI 4.0. Devuelve el comprobante con Id + UUID (folio fiscal).

        `cfdi` debe traer Issuer.Rfc con un CSD ya registrado.
        """
        return await self._request("POST", "/api-lite/3/cfdis", json=cfdi)

    async def get_cfdi_file(self, cfdi_id: str, fmt: str) -> bytes:
        """Descarga el CFDI ya timbrado en pdf/xml/html. Devuelve los bytes."""
        fmt = fmt.lower()
        if fmt not in ("pdf", "xml", "html"):
            raise FacturamaError("Formato de archivo no válido.")
        body = await self._request("GET", f"/api/Cfdi/{fmt}/IssuedLite/{cfdi_id}")
        content = body.get("Content") if isinstance(body, dict) else None
        if not content:
            raise FacturamaError("El archivo del CFDI no está disponible.")
        return base64.b64decode(content)

    async def cancel_cfdi(self, cfdi_id: str, motive: str = "02") -> Any:
        """Cancela un CFDI timbrado (motivo SAT, por defecto 02 'sin relación')."""
        return await self._request(
            "DELETE", f"/api-lite/cfdis/{cfdi_id}", params={"motive": motive}
        )


def get_facturama() -> FacturamaClient:
    """Instancia el cliente con la configuración vigente."""
    return FacturamaClient()
