"""PDF tipo pedido/remito (ReportLab): plantilla única Sirona.

Reglas nuevas:
- A4 vertical.
- Máximo 15 productos por página.
- PEDIDO y REMITO como copias dentro del mismo PDF (cada copia empieza en página nueva).
- Totales solo en la última página del PEDIDO (no confundir en páginas intermedias).
"""
from __future__ import annotations

from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.platypus import PageBreak, SimpleDocTemplate

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
        bottomMargin=14 * mm,
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
    pages_meta.extend(pm1)

    # Copia 2: Remito (sin totales; solo líneas)
    story.append(PageBreak())
    meta_rem = DocMeta(doc_type="REMITO", copy_label="Remito", **meta_base)
    st2, pm2 = build_story_for_commercial_doc(
        doc=doc,
        styles=styles,
        meta=meta_rem,
        items=items,
        totals=None,
        vencimiento_pago=None,
        observaciones=None,
    )
    story.extend(st2)
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
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
        canvas.setLineWidth(0.6)
        y = doc.bottomMargin - 2.5 * mm
        canvas.line(doc.leftMargin, y, doc.leftMargin + doc.width, y)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.setFont("Helvetica", 8)
        footer = f"Documento no válido como factura. | Generado: {generated} | {pages_str}"
        canvas.drawString(doc.leftMargin, y - 8, footer)
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)

    buf.seek(0)
    safe = f"Pedido_Remito_{numero}"
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{safe}.pdf"'
    return resp
