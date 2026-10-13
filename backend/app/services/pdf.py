"""Generación de documentos PDF (facturas, recibos) con ReportLab.

El frontend ya arma el documento que se ve en pantalla (encabezado, datos,
renglones y totales); aquí sólo lo dibujamos en un PDF real para que el botón
"Descargar factura" baje un archivo .pdf en vez de abrir la impresión del
navegador.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape as _xml

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import landscape, letter
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


def _celda(value) -> str:
    """Texto de una celda listo para Paragraph: escapado, y con los saltos de
    línea convertidos (Paragraph los ignora). Los nombres de show y de
    proveedor los escribe la gente, y un "Rock & <b>Blues" rompía el PDF."""
    return _xml(_s(value)).replace("\n", "<br/>")


def _tabla(st: dict, width: float, table: dict):
    """Una tabla de renglones a partir de {head, rows, align, first_col, total}.

    ``total`` marca el último renglón como fila de totales (negrita y raya).
    Devuelve None si no hay cabecera o no hay renglones.
    """
    head_row = [_s(h) for h in (table.get("head") or [])]
    body_rows = table.get("rows") or []
    if not head_row or not body_rows:
        return None
    align = [str(a or "l").lower() for a in (table.get("align") or [])]
    align += ["l"] * (len(head_row) - len(align))
    n = len(head_row)
    # Con muchas columnas la letra baja un punto para que quepan importes.
    if n > 9:
        st = dict(st, **{k: ParagraphStyle(k + "_c", parent=st[k], fontSize=7.3, leading=9.4)
                         for k in ("cell", "cellc", "cellr")})
    cs = [{"r": st["cellr"], "c": st["cellc"]}.get(a, st["cell"]) for a in align]
    con_total = bool(table.get("total"))
    data = [[Paragraph(f"<b>{_celda(h)}</b>", cs[i]) for i, h in enumerate(head_row)]]
    for k, r in enumerate(body_rows):
        cells = list(r) + [""] * (len(head_row) - len(r))
        fuerte = con_total and k == len(body_rows) - 1
        fmt = "<b>%s</b>" if fuerte else "%s"
        data.append([Paragraph(fmt % _celda(c), cs[i]) for i, c in enumerate(cells[:len(head_row)])])
    # La primera columna se lleva el espacio sobrante; el resto se reparte.
    try:
        fc = float(table.get("first_col") or 0)
    except (TypeError, ValueError):
        fc = 0
    first = width * (fc if 0.05 < fc < 0.9 else (0.16 if n > 9 else 0.30 if n > 3 else 0.40))
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
    if con_total:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 1.2, BRAND))
    for i, a in enumerate(align[:n]):
        style.append(("ALIGN", (i, 0), (i, -1), _ALIGN.get(a, "LEFT")))
    lt.setStyle(TableStyle(style))
    return lt


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
    # Horizontal para las tablas anchas: el reparto por mes son 14 columnas y el
    # calendario semanal 8 con varias líneas por celda; en vertical no caben.
    apaisado = _s(doc.get("orientation")).lower() == "landscape"
    pdf = SimpleDocTemplate(
        buf, pagesize=landscape(letter) if apaisado else letter,
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
    t = _tabla(st, width, doc.get("table") or {})
    if t is not None:
        flow += [t, Spacer(1, 10)]

    # --- Secciones extra: más tablas con su título (p. ej. el reparto por
    #     categoría y el control anual del panel de Presupuesto) ---
    for sec in (doc.get("sections") or []):
        if not isinstance(sec, dict):
            continue
        tt = _tabla(st, width, sec)
        if tt is None:
            continue
        titulo = _s(sec.get("title")).strip()
        if titulo:
            flow += [Spacer(1, 4), Paragraph(f"<b>{_celda(titulo)}</b>", st["meta"]), Spacer(1, 4)]
        flow += [tt, Spacer(1, 10)]

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
