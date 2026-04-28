"""PDF tipo pedido/remito (ReportLab).

Reglas de salida:
- Si la venta tiene <= 15 renglones: A4 apaisado con dos comprobantes en una hoja:
  PEDIDO (izquierda) + REMITO (derecha) con guía de corte.
- Si tiene > 15 renglones: A4 vertical:
  PEDIDO en hoja(s) completa(s) + REMITO en hoja(s) completa(s).
"""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.money_decimal import format_monto_ars
from django.contrib.staticfiles import finders
from reportlab.platypus import Image as RLImage


def _money(v) -> str:
    return format_monto_ars(v)


def _numero_remito(venta) -> str:
    """Número correlativo de remito (mismo criterio que el pedido, 8 dígitos)."""
    return str(venta.pk).zfill(8)


def _logo_flowable():
    logo_path = finders.find("img/sirona-logo.png")
    if not logo_path:
        return None
    # Tamaño compacto para caber en media hoja sin “aplastar”.
    return RLImage(logo_path, width=26 * mm, height=10 * mm)


def _header_block(*, doc_width: float, tipo: str, numero: str, fecha_hora: str, styles):
    """
    Header compacto:
    - izquierda: logo + SIRONA Cooperativa / Sistema de Gestión
    - derecha: tipo / N.º / fecha-hora
    + línea azul sutil abajo
    """
    logo = _logo_flowable()
    left_stack = []
    if logo is not None:
        left_stack.append(logo)
    left_stack.append(
        Paragraph(
            '<para leading="10"><font size="9"><b>SIRONA Cooperativa</b></font><br/>'
            '<font size="7" color="#64748b">Sistema de Gestión</font></para>',
            styles["Normal"],
        )
    )
    left = Table([[x] for x in left_stack], colWidths=[doc_width * 0.52])
    left.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    right = Paragraph(
        f'<para align="right" leading="10">'
        f'<font size="9" color="#2563eb"><b>{escape(tipo)}</b></font><br/>'
        f'<font size="9"><b>N.º {escape(numero)}</b></font><br/>'
        f'<font size="7" color="#64748b">{escape(fecha_hora)}</font>'
        f"</para>",
        styles["Normal"],
    )

    row = Table([[left, right]], colWidths=[doc_width * 0.58, doc_width * 0.42])
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, 0), (-1, -1), 0.75, colors.HexColor("#93c5fd")),
            ]
        )
    )
    return row


def _vendedor_comprador_block(*, doc_width: float, venta, styles):
    vend = venta.vendedor
    c = venta.comprador if venta.comprador_id else None

    v = Paragraph(
        f'<para leading="10"><font size="7" color="#64748b"><b>VENDEDOR</b></font><br/>'
        f'<font size="7" color="#64748b">Código:</font> <font size="8">{escape(str(vend.codigo))}</font><br/>'
        f'<font size="8"><b>{escape(vend.apellido)}, {escape(vend.nombre)}</b></font></para>',
        styles["Normal"],
    )
    if c:
        extra = ""
        if getattr(c, "direccion", None):
            extra = f'<br/><font size="7" color="#64748b">{escape(c.direccion[:28])}</font>'
        comp = Paragraph(
            f'<para leading="10"><font size="7" color="#64748b"><b>COMPRADOR</b></font><br/>'
            f'<font size="7" color="#64748b">Código:</font> <font size="8">{escape(str(c.codigo))}</font><br/>'
            f'<font size="8"><b>{escape(c.apellido)}, {escape(c.nombre)}</b></font>{extra}</para>',
            styles["Normal"],
        )
    else:
        comp = Paragraph(
            '<para leading="10"><font size="7" color="#64748b"><b>COMPRADOR</b></font><br/>'
            '<font size="8" color="#64748b">—</font></para>',
            styles["Normal"],
        )

    t = Table([[v, comp]], colWidths=[doc_width * 0.5, doc_width * 0.5])
    t.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t


def _tabla_pedido(*, doc_width: float, lineas, styles):
    data = [["N.º", "Código", "Descripción", "Cant.", "P. Unit.", "Subtotal"]]
    for n_item, ln in enumerate(lineas, start=1):
        data.append(
            [
                str(n_item),
                escape(str(ln.texto_codigo)),
                # En landscape (media hoja) priorizamos descripción: truncar un poco menos.
                escape((ln.texto_descripcion or "")[:96]),
                str(ln.cantidad),
                _money(ln.precio_unitario),
                _money(ln.subtotal),
            ]
        )
    if len(data) == 1:
        data.append(["—", "—", "Sin líneas", "", "", ""])

    # Más aire para la descripción: le ganamos ancho a Código / importes.
    col_w = [
        doc_width * 0.06,  # N.º
        doc_width * 0.12,  # Código
        doc_width * 0.48,  # Descripción (más ancho)
        doc_width * 0.08,  # Cant.
        doc_width * 0.13,  # P. Unit.
        doc_width * 0.13,  # Subtotal
    ]
    t = Table(data, colWidths=col_w, repeatRows=1, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 6.8),
                ("FONTSIZE", (0, 1), (-1, -1), 7.2),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd5e1")),
                ("GRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2.4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (3, 1), (3, -1), "CENTER"),
                ("ALIGN", (4, 1), (5, -1), "RIGHT"),
            ]
        )
    )
    return t


def _tabla_remito(*, doc_width: float, lineas, styles):
    data = [["N.º", "Código", "Descripción", "Cant."]]
    for n_item, ln in enumerate(lineas, start=1):
        data.append(
            [
                str(n_item),
                escape(str(ln.texto_codigo)),
                escape((ln.texto_descripcion or "")[:108]),
                str(ln.cantidad),
            ]
        )
    if len(data) == 1:
        data.append(["—", "—", "Sin líneas", ""])

    col_w = [
        doc_width * 0.07,  # N.º
        doc_width * 0.16,  # Código
        doc_width * 0.64,  # Descripción (más ancho)
        doc_width * 0.13,  # Cant.
    ]
    t = Table(data, colWidths=col_w, repeatRows=1, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 6.8),
                ("FONTSIZE", (0, 1), (-1, -1), 7.2),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd5e1")),
                ("GRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2.4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
            ]
        )
    )
    return t


def _totales_pedido(*, doc_width: float, venta, styles):
    rows = [["Subtotal", _money(venta.subtotal_lineas)]]
    if venta.descuento_monto and venta.descuento_monto > 0:
        rows.append(["Descuento", _money(venta.descuento_monto)])
    rows.append(["TOTAL", _money(venta.neto)])

    t = Table(rows, colWidths=[doc_width * 0.55, doc_width * 0.45], hAlign="RIGHT")
    total_row = len(rows) - 1
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, total_row), (-1, total_row), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEABOVE", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0, total_row), (-1, total_row), colors.HexColor("#eff6ff")),
                ("TEXTCOLOR", (0, total_row), (-1, total_row), colors.HexColor("#2563eb")),
            ]
        )
    )
    return t


def _remito_campos(*, doc_width: float, styles):
    # Líneas simples para completar.
    rows = [
        [
            Paragraph('<font size="7" color="#64748b"><b>Total de bultos:</b></font>', styles["Normal"]),
            Paragraph('<font size="7" color="#64748b"><b>Observaciones:</b></font>', styles["Normal"]),
        ],
        ["", ""],
        ["", ""],
    ]
    t = Table(rows, colWidths=[doc_width * 0.35, doc_width * 0.65])
    t.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 1), (0, 1), 0.5, colors.HexColor("#cbd5e1")),
                ("LINEBELOW", (1, 1), (1, 1), 0.5, colors.HexColor("#cbd5e1")),
                ("LINEBELOW", (1, 2), (1, 2), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return t


def _gracias(styles):
    return Paragraph(
        '<para align="center"><font size="7" color="#64748b">Gracias por confiar en nosotros.</font></para>',
        styles["Normal"],
    )


def _draw_cut_line(canvas, doc):
    # Línea guía de corte (solo cuando usamos dos mitades).
    x = doc.leftMargin + (doc.width / 2.0)
    y0 = doc.bottomMargin
    y1 = doc.pagesize[1] - doc.topMargin
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.6)
    canvas.setDash(2, 3)
    canvas.line(x, y0, x, y1)
    canvas.restoreState()


def remito_venta_pdf_response(venta) -> HttpResponse:
    """Genera PDF con formato moderno de pedido/remito (ver docstring del módulo)."""
    buf = BytesIO()
    lineas = list(venta.lineas.all())
    n = len(lineas)
    short = n <= 15

    if short:
        pagesize = landscape(A4)
        # Márgenes compactos para dos mitades.
        doc = SimpleDocTemplate(
            buf,
            pagesize=pagesize,
            rightMargin=9 * mm,
            leftMargin=9 * mm,
            topMargin=8 * mm,
            bottomMargin=8 * mm,
        )
    else:
        pagesize = A4
        doc = SimpleDocTemplate(
            buf,
            pagesize=pagesize,
            rightMargin=14 * mm,
            leftMargin=14 * mm,
            topMargin=16 * mm,
            bottomMargin=14 * mm,
        )
    styles = getSampleStyleSheet()
    numero = _numero_remito(venta)
    fecha_hora = venta.creado_en.strftime("%d/%m/%Y %H:%M")

    def build_pedido_story(doc_width: float):
        st = []
        st.append(_header_block(doc_width=doc_width, tipo="PEDIDO", numero=numero, fecha_hora=fecha_hora, styles=styles))
        st.append(_vendedor_comprador_block(doc_width=doc_width, venta=venta, styles=styles))
        st.append(_tabla_pedido(doc_width=doc_width, lineas=lineas, styles=styles))
        st.append(Spacer(1, 2 * mm))
        st.append(_totales_pedido(doc_width=doc_width, venta=venta, styles=styles))
        st.append(Spacer(1, 2 * mm))
        st.append(_gracias(styles))
        return st

    def build_remito_story(doc_width: float):
        st = []
        st.append(_header_block(doc_width=doc_width, tipo="REMITO", numero=numero, fecha_hora=fecha_hora, styles=styles))
        st.append(_vendedor_comprador_block(doc_width=doc_width, venta=venta, styles=styles))
        st.append(_tabla_remito(doc_width=doc_width, lineas=lineas, styles=styles))
        st.append(Spacer(1, 3 * mm))
        st.append(_remito_campos(doc_width=doc_width, styles=styles))
        st.append(Spacer(1, 2 * mm))
        st.append(_gracias(styles))
        return st

    story = []
    if short:
        # Media hoja: ancho útil dividido en dos, con un pequeño gutter.
        gutter = 6 * mm
        half_w = (doc.width - gutter) / 2.0
        left_story = build_pedido_story(half_w)
        right_story = build_remito_story(half_w)
        container = Table([[left_story, right_story]], colWidths=[half_w, half_w])
        container.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("COLPADDING", (0, 0), (-1, -1), 0),
                    ("LEFTPADDING", (1, 0), (1, 0), gutter),
                ]
            )
        )
        story.append(container)
        doc.build(story, onFirstPage=_draw_cut_line, onLaterPages=_draw_cut_line)
    else:
        # Formato largo: una copia por hoja, primero pedido, luego remito.
        story.extend(build_pedido_story(doc.width))
        story.append(PageBreak())
        story.extend(build_remito_story(doc.width))
        doc.build(story)

    buf.seek(0)
    safe = f"Pedido_Remito_{numero}"
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{safe}.pdf"'
    return resp
