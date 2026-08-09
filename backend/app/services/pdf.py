"""Generación de documentos PDF (facturas, recibos) con ReportLab.

El frontend ya arma el documento que se ve en pantalla (encabezado, datos,
renglones y totales); aquí sólo lo dibujamos en un PDF real para que el botón
"Descargar factura" baje un archivo .pdf en vez de abrir la impresión del
navegador.
"""
from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BRAND = colors.HexColor("#382ca1")
INK = colors.HexColor("#14141c")
MUTED = colors.HexColor("#6b6b7b")
LINE = colors.HexColor("#e4e4ee")

_ALIGN = {"l": "LEFT", "c": "CENTER", "r": "RIGHT"}


def _styles() -> dict:
    base = getSampleStyleSheet()["Normal"]
    return {
        "brand": ParagraphStyle("brand", parent=base, fontName="Helvetica-Bold",
                                fontSize=15, textColor=BRAND, leading=18),
        "sub": ParagraphStyle("sub", parent=base, fontName="Helvetica",
                              fontSize=8.5, textColor=MUTED, leading=11),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold",
                             fontSize=15, textColor=INK, alignment=TA_RIGHT, leading=18),
        "subr": ParagraphStyle("subr", parent=base, fontName="Helvetica",
                               fontSize=8.5, textColor=MUTED, alignment=TA_RIGHT, leading=11),
        "meta": ParagraphStyle("meta", parent=base, fontName="Helvetica",
                               fontSize=9, textColor=INK, leading=13),
        "cell": ParagraphStyle("cell", parent=base, fontName="Helvetica",
                               fontSize=8.5, textColor=INK, leading=11),
        "cellc": ParagraphStyle("cellc", parent=base, fontName="Helvetica",
                                fontSize=8.5, textColor=INK, leading=11, alignment=TA_CENTER),
        "cellr": ParagraphStyle("cellr", parent=base, fontName="Helvetica",
                                fontSize=8.5, textColor=INK, leading=11, alignment=TA_RIGHT),
        "foot": ParagraphStyle("foot", parent=base, fontName="Helvetica",
                               fontSize=7.5, textColor=MUTED, leading=10),
    }


def _s(value) -> str:
    return "" if value is None else str(value)


def build_document_pdf(doc: dict) -> bytes:
    """Arma el PDF a partir del documento genérico que manda el frontend.

    Estructura esperada (todo opcional salvo ``kind``)::

        {"kind": "Factura", "number": "INV-202608-001",
         "meta": [["Hotel", "..."], ["Periodo", "..."]],
         "table": {"head": [...], "rows": [[...]], "align": ["l", ..., "r"]},
         "summary": [["Subtotal", "$1,000.00", false], ["Total", "...", true]],
         "note": "texto opcional al pie"}
    """
    st = _styles()
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=14 * mm,
        title=_s(doc.get("title") or doc.get("kind") or "Documento"),
        author="SHOWMA",
    )
    width = pdf.width
    flow = []

    # --- Encabezado ---
    head = Table(
        [[
            [Paragraph("SHOWMA", st["brand"]), Paragraph("Entertainment OS", st["sub"])],
            [Paragraph(_s(doc.get("kind") or "Documento"), st["h1"]),
             Paragraph(_s(doc.get("number")), st["subr"])],
        ]],
        colWidths=[width * 0.5, width * 0.5],
    )
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -1), 1.4, BRAND),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    flow += [head, Spacer(1, 10)]

    # --- Datos generales (dos columnas de "etiqueta: valor") ---
    meta = [m for m in (doc.get("meta") or []) if m]
    if meta:
        pairs = [Paragraph(f"<b>{_s(m[0])}:</b> {_s(m[1] if len(m) > 1 else '')}", st["meta"])
                 for m in meta]
        rows = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]
        for r in rows:
            if len(r) == 1:
                r.append("")
        mt = Table(rows, colWidths=[width * 0.5, width * 0.5])
        mt.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        flow += [mt, Spacer(1, 12)]

    # --- Renglones ---
    table = doc.get("table") or {}
    head_row = [_s(h) for h in (table.get("head") or [])]
    body_rows = table.get("rows") or []
    if head_row and body_rows:
        align = [str(a or "l").lower() for a in (table.get("align") or [])]
        align += ["l"] * (len(head_row) - len(align))
        cs = [{"r": st["cellr"], "c": st["cellc"]}.get(a, st["cell"]) for a in align]
        data = [[Paragraph(f"<b>{h}</b>", cs[i]) for i, h in enumerate(head_row)]]
        for r in body_rows:
            cells = [_s(c) for c in r] + [""] * (len(head_row) - len(r))
            data.append([Paragraph(c, cs[i]) for i, c in enumerate(cells[:len(head_row)])])
        # La primera columna se lleva el espacio sobrante; el resto se reparte.
        n = len(head_row)
        first = width * (0.30 if n > 3 else 0.40)
        rest = (width - first) / max(n - 1, 1)
        lt = Table(data, colWidths=[first] + [rest] * (n - 1), repeatRows=1)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, a in enumerate(align[:n]):
            style.append(("ALIGN", (i, 0), (i, -1), _ALIGN.get(a, "LEFT")))
        lt.setStyle(TableStyle(style))
        flow += [lt, Spacer(1, 10)]

    # --- Totales (bloque a la derecha) ---
    summary = [s for s in (doc.get("summary") or []) if s]
    if summary:
        data, style = [], [
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, row in enumerate(summary):
            label, value = _s(row[0]), _s(row[1] if len(row) > 1 else "")
            strong = bool(row[2]) if len(row) > 2 else False
            tag = ("<b>%s</b>" if strong else "%s")
            data.append([Paragraph(tag % label, st["cell"]), Paragraph(tag % value, st["cellr"])])
            if strong:
                style.append(("LINEABOVE", (0, i), (-1, i), 1.2, BRAND))
            else:
                style.append(("LINEBELOW", (0, i), (-1, i), 0.4, LINE))
        sw = width * 0.56
        st_tbl = Table(data, colWidths=[sw * 0.62, sw * 0.38], hAlign="RIGHT")
        st_tbl.setStyle(TableStyle(style))
        flow += [st_tbl, Spacer(1, 14)]

    note = _s(doc.get("note")).strip()
    if note:
        flow += [Paragraph(note, st["foot"]), Spacer(1, 6)]
    flow.append(Paragraph(
        "SHOWMA · Entertainment OS — documento generado desde la plataforma.", st["foot"]))

    pdf.build(flow)
    return buf.getvalue()
