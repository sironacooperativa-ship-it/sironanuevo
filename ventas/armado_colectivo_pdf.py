"""PDF de armado colectivo (estilo documentos Sirona)."""

from __future__ import annotations

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.money_decimal import format_monto_ars
from core.pdf_membrete import emission_datetime_str, proportional_logo

from .armado_servicios import LineaArmadoColectivo
from .models import PuntoStockArmado, Venta


def armado_colectivo_pdf_response(
    *,
    ventas: list[Venta],
    lineas: list[LineaArmadoColectivo],
    puntos: list[PuntoStockArmado],
    asignaciones: dict[int, dict[int, int]],
) -> HttpResponse:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    story: list[Any] = []

    pedidos_txt = ", ".join(f"#{v.pk}" for v in ventas[:12])
    if len(ventas) > 12:
        pedidos_txt += f" … (+{len(ventas) - 12})"

    logo = proportional_logo(max_w=28 * mm, max_h=12 * mm)
    header_left = [[logo]] if logo else []
    header_left.append(
        [
            Paragraph(
                '<para leading="11">'
                '<font size="10"><b>SIRONA Cooperativa</b></font><br/>'
                '<font size="8" color="#64748b">Armado colectivo de pedidos</font>'
                "</para>",
                styles["Normal"],
            )
        ]
    )
    left = Table(header_left, colWidths=[doc.width * 0.5])
    left.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    emitido = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    right = Paragraph(
        f'<para align="right" leading="11">'
        f'<font size="10" color="#007aff"><b>ARMADO COLECTIVO</b></font><br/>'
        f'<font size="8" color="#64748b">Emitido: {escape(emitido)}</font><br/>'
        f'<font size="8">Pedidos: {escape(pedidos_txt)}</font>'
        f"</para>",
        styles["Normal"],
    )
    top = Table([[left, right]], colWidths=[doc.width * 0.55, doc.width * 0.45])
    top.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(top)
    story.append(Spacer(1, 4 * mm))

    hdr = ["#", "Código", "Descripción", "Cant.", "Costo", "P. venta"]
    for p in puntos:
        hdr.append(p.nombre)
    hdr.append("Asignado")

    data = [hdr]
    total_cant = 0
    total_costo = 0
    total_precio = 0
    for i, ln in enumerate(lineas, start=1):
        por_punto = asignaciones.get(ln.producto_id) or {}
        asig_sum = sum(por_punto.values())
        row = [
            str(i),
            ln.codigo,
            Paragraph(escape(ln.descripcion[:120]), styles["Normal"]),
            str(ln.cantidad_total),
            format_monto_ars(ln.costo_unitario),
            format_monto_ars(ln.precio_venta),
        ]
        for p in puntos:
            row.append(str(por_punto.get(p.pk, 0) or ""))
        row.append(str(asig_sum) if asig_sum else "")
        data.append(row)
        total_cant += ln.cantidad_total
        total_costo += float(ln.costo_unitario) * ln.cantidad_total
        total_precio += float(ln.subtotal_precio)

    data.append(
        [
            "",
            "",
            "TOTALES",
            str(total_cant),
            "",
            format_monto_ars(total_precio),
            *([""] * len(puntos)),
            "",
        ]
    )

    n_fixed = 6
    n_puntos = len(puntos)
    # Anchos: repartir espacio restante entre descripción y puntos
    w_desc = doc.width * 0.22
    w_pt = max(14 * mm, (doc.width - 60 * mm - w_desc) / max(n_puntos + 4, 1))
    col_widths = [8 * mm, 14 * mm, w_desc, 12 * mm, 18 * mm, 18 * mm]
    col_widths.extend([w_pt] * n_puntos)
    col_widths.append(14 * mm)

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (3, 1), (3, -1), "CENTER"),
                ("ALIGN", (n_fixed, 1), (-1, -1), "CENTER"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f8fafc")),
            ]
        )
    )
    story.append(tbl)

    generated = emission_datetime_str()

    def on_page(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
        y = doc.bottomMargin - 2 * mm
        canvas.line(doc.leftMargin, y, doc.leftMargin + doc.width, y)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(
            doc.leftMargin,
            y - 7,
            f"Documento interno de armado. | Generado: {generated} | Página {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="armado-colectivo.pdf"'
    return resp
