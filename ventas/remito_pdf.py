"""PDF tipo pedido/remito (ReportLab): plantilla única Sirona.

Reglas:
- A4 vertical.
- Máximo 25 productos por página.
- PEDIDO (Original) y REMITO como copias en el mismo PDF (cada copia empieza en página nueva).
- Totales en la última página de cada copia (mismo contenido comercial).
"""
from __future__ import annotations

from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.pdf_membrete import emission_datetime_str
from core.sirona_docs_pdf import (
    DocMeta,
    LineItem,
    PartyInfo,
    Totals,
    build_story_for_commercial_doc,
    money,
)


def _numero_remito(venta) -> str:
    """Número correlativo de remito (mismo criterio que el pedido, 8 dígitos)."""
    return str(venta.pk).zfill(8)


def _recibo_conforme_block(doc_width: float, styles) -> list:
    """Bloque visible debajo de los totales (original y copia) para firmar al entregar."""
    titulo = Paragraph(
        '<para leading="13"><font size="10" color="#16323a"><b>Recibí conforme</b></font></para>',
        styles["Normal"],
    )
    campos = Table(
        [
            [
                Paragraph('<font size="9"><b>Fecha:</b></font>', styles["Normal"]),
                Paragraph('<font size="9">_______________</font>', styles["Normal"]),
                Paragraph('<font size="9"><b>Firma:</b></font>', styles["Normal"]),
                Paragraph('<font size="9">_______________</font>', styles["Normal"]),
                Paragraph('<font size="9"><b>Aclaración:</b></font>', styles["Normal"]),
                Paragraph('<font size="9">_______________</font>', styles["Normal"]),
            ]
        ],
        colWidths=[
            doc_width * 0.10,
            doc_width * 0.20,
            doc_width * 0.10,
            doc_width * 0.20,
            doc_width * 0.14,
            doc_width * 0.26,
        ],
    )
    campos.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 1),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    caja = Table(
        [[titulo], [campos]],
        colWidths=[doc_width],
    )
    caja.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#16323a")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (0, 0), 6),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
            ]
        )
    )
    return [Spacer(1, 8 * mm), KeepTogether([caja])]


def _draw_remito_page_footer(canvas, doc, generated: str, pages_str: str) -> None:
    """Pie de cada página (original y copia): recepción + disclaimer."""
    left = doc.leftMargin
    right = doc.leftMargin + doc.width
    canvas.saveState()

    y_recibo = 18 * mm
    canvas.setFillColor(colors.HexColor("#16323a"))
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(left, y_recibo, "Recibí conforme:")

    canvas.setFont("Helvetica", 8)
    canvas.setStrokeColor(colors.HexColor("#16323a"))
    canvas.setLineWidth(0.5)
    campos = (
        ("Fecha:", 36 * mm),
        ("Firma:", 46 * mm),
        ("Aclaración:", 50 * mm),
    )
    cursor = left + 28 * mm
    for etiqueta, ancho in campos:
        canvas.drawString(cursor, y_recibo, etiqueta)
        etiqueta_w = canvas.stringWidth(etiqueta, "Helvetica", 8) + 1.8 * mm
        x1 = cursor + etiqueta_w
        x2 = min(x1 + ancho, right)
        canvas.line(x1, y_recibo - 1, x2, y_recibo - 1)
        cursor = x2 + 3.5 * mm

    y = 10 * mm
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.6)
    canvas.line(left, y + 3.5 * mm, right, y + 3.5 * mm)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.setFont("Helvetica", 8)
    footer = f"Documento no válido como factura. | Generado: {generated} | {pages_str}"
    canvas.drawString(left, y - 2.5 * mm, footer)
    canvas.restoreState()


def remito_venta_pdf_response(venta) -> HttpResponse:
    """Genera PDF con formato moderno de pedido/remito (ver docstring del módulo)."""
    buf = BytesIO()
    lineas = list(venta.lineas.all())
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=12 * mm,
        # Espacio para renglón de recepción + disclaimer.
        bottomMargin=28 * mm,
    )
    styles = getSampleStyleSheet()
    numero = _numero_remito(venta)

    vendedor = venta.vendedor
    cliente = None
    if venta.comprador_id:
        c = venta.comprador
        cliente = PartyInfo(
            codigo=str(c.codigo),
            nombre=f"{c.apellido}, {c.nombre}",
            direccion=(c.direccion or "").strip(),
        )

    meta_base = dict(
        doc_number=numero,
        fecha_emision=venta.creado_en.strftime("%d/%m/%Y %H:%M"),
        estado=venta.get_estado_display(),
        vendedor=PartyInfo(codigo=str(vendedor.codigo), nombre=f"{vendedor.apellido}, {vendedor.nombre}"),
        cliente=cliente,
    )

    items: list[LineItem] = []
    for n_item, ln in enumerate(lineas, start=1):
        # Misma tabla para pedido/remito; el remito conserva importes (solo presentación).
        items.append(
            LineItem(
                numero=n_item,
                codigo=str(ln.texto_codigo),
                marca=str(ln.texto_marca),
                descripcion=str(ln.texto_descripcion or ""),
                cantidad=str(ln.cantidad),
                precio_unitario=money(ln.precio_unitario),
                subtotal=money(ln.subtotal),
            )
        )

    totals_pedido = Totals(
        subtotal_lineas=money(venta.subtotal_lineas),
        descuento=(money(venta.descuento_monto) if venta.descuento_monto and venta.descuento_monto > 0 else None),
        envio=(money(venta.envio) if getattr(venta, "envio", None) and venta.envio > 0 else None),
        total_neto=money(venta.neto),
    )
    venc = venta.fecha_vencimiento_pago.strftime("%d/%m/%Y") if venta.fecha_vencimiento_pago else None

    story: list[Any] = []
    pages_meta: list[Any] = []

    # Copia 1: Pedido (con totales al final)
    meta_pedido = DocMeta(doc_type="PEDIDO", copy_label="Original", **meta_base)
    st1, pm1 = build_story_for_commercial_doc(
        doc=doc,
        styles=styles,
        meta=meta_pedido,
        items=items,
        totals=totals_pedido,
        vencimiento_pago=venc,
        observaciones=None,
    )
    story.extend(st1)
    story.extend(_recibo_conforme_block(doc.width, styles))
    pages_meta.extend(pm1)

    # Copia 2: Remito (mismo detalle y totales que el pedido)
    story.append(PageBreak())
    meta_rem = DocMeta(doc_type="REMITO", copy_label="Remito", **meta_base)
    st2, pm2 = build_story_for_commercial_doc(
        doc=doc,
        styles=styles,
        meta=meta_rem,
        items=items,
        totals=totals_pedido,
        vencimiento_pago=venc,
        observaciones=None,
    )
    story.extend(st2)
    story.extend(_recibo_conforme_block(doc.width, styles))
    pages_meta.extend(pm2)

    generated = emission_datetime_str()

    def on_page(canvas, _doc):
        pnum = canvas.getPageNumber()
        meta = pages_meta[pnum - 1] if 1 <= pnum <= len(pages_meta) else None
        pages_str = (
            f"Página {meta.page_in_copy} de {meta.pages_in_copy}"  # type: ignore[union-attr]
            if meta is not None
            else f"Página {pnum}"
        )
        _draw_remito_page_footer(canvas, doc, generated, pages_str)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)

    buf.seek(0)
    safe = f"Pedido_Remito_{numero}"
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{safe}.pdf"'
    return resp
