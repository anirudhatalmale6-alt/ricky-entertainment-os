"""Descarga de documentos en PDF (facturas del hotel, recibos del artista).

El frontend manda el documento ya armado (encabezado, datos, renglones y
totales) y aquí se devuelve el archivo .pdf listo para descargar.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.services.pdf import build_document_pdf

router = APIRouter(prefix="/documents", tags=["documents"])

_MAX_ROWS = 2000


class DocTable(BaseModel):
    head: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    align: list[str] = Field(default_factory=list)
    # Fraccion del ancho para la primera columna (opcional).
    first_col: float | None = None
    # El ultimo renglon es la fila de totales (negrita y raya encima).
    total: bool = False


class DocSection(DocTable):
    title: str | None = None


class DocIn(BaseModel):
    kind: str = "Documento"
    number: str | None = None
    title: str | None = None
    filename: str | None = None
    meta: list[list[str]] = Field(default_factory=list)
    table: DocTable | None = None
    summary: list[list[str]] = Field(default_factory=list)
    note: str | None = None
    # "landscape" para tablas anchas (reparto por mes, calendario semanal).
    orientation: str | None = None
    # Mas tablas, cada una con su titulo, despues de la principal.
    sections: list[DocSection] = Field(default_factory=list)


def _safe_filename(name: str | None, fallback: str) -> str:
    base = (name or fallback).strip() or fallback
    base = re.sub(r"[^A-Za-z0-9._ -]+", "", base).strip() or fallback
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base


@router.post("/pdf", dependencies=[Depends(get_current_user)])
async def document_pdf(payload: DocIn):
    total_rows = (len(payload.table.rows) if payload.table else 0) + sum(
        len(sec.rows) for sec in payload.sections)
    if total_rows > _MAX_ROWS or len(payload.sections) > 20:
        raise HTTPException(status_code=413, detail="El documento tiene demasiados renglones.")
    data = payload.model_dump()
    if payload.table is not None:
        data["table"] = payload.table.model_dump()
    # summary llega como listas de texto; el tercer elemento marca el renglón fuerte.
    data["summary"] = [
        [s[0] if len(s) > 0 else "", s[1] if len(s) > 1 else "",
         str(s[2]).lower() in ("1", "true", "si", "sí") if len(s) > 2 else False]
        for s in payload.summary
    ]
    pdf = build_document_pdf(data)
    fname = _safe_filename(payload.filename, payload.number or payload.kind or "documento")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
