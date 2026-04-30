"""PDF de presupuesto (ReportLab): plantilla única Sirona, copias Remito y Duplicado."""
from __future__ import annotations

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, SimpleDocTemplate

from core.money_decimal import format_monto_ars
from core.pdf_membrete import emission_datetime_str
from core.sirona_docs_pdf import (
    DocMeta,
    LineItem,
    PartyInfo,
    Totals,
    build_story_for_commercial_doc,
    money,
)

from .models import Presupuesto


def _money(v) -> str:
    # Back-compat: mantiene firma local usada en otros lugares.
    return format_monto_ars(v)


def _numero_doc(presupuesto) -> str:
    return str(presupuesto.pk).zfill(8)


def _titulo_membrete(presupuesto, copia_label: str) -> str:
    ndoc = _numero_doc(presupuesto)
    if presupuesto.estado == Presupuesto.Estado.APROBADO:
        return f"Orden de compra N.º {ndoc} — Copia {copia_label}"
    return f"Presupuesto N.º {ndoc} — Copia {copia_label}"


def _append_copia_presupuesto_pdf(story, presupuesto, doc, styles, copia_label: str):
    """Una hoja completa (mismo contenido; copia Remito / Duplicado)."""
    ndoc = _numero_doc(presupuesto)
    doc_type = "ORDEN DE COMPRA" if presupuesto.estado == Presupuesto.Estado.APROBADO else "PRESUPUESTO"
    vend = presupuesto.vendedor
    cliente = None
    if presupuesto.comprador_id:
        c = presupuesto.comprador
        cliente = PartyInfo(
            codigo=str(c.codigo),
            nombre=f"{c.apellido}, {c.nombre}",
            direccion=(c.direccion or "").strip(),
        )
    meta = DocMeta(
        doc_type=doc_type,
        doc_number=ndoc,
        copy_label=copia_label,
        fecha_emision=presupuesto.creado_en.strftime("%d/%m/%Y %H:%M"),
        estado=presupuesto.get_estado_display(),
        vendedor=PartyInfo(codigo=str(vend.codigo), nombre=f"{vend.apellido}, {vend.nombre}"),
        cliente=cliente,
    )

    lineas = list(presupuesto.lineas.all())
    items: list[LineItem] = []
    for n_item, ln in enumerate(lineas, start=1):
        items.append(
            LineItem(
                numero=n_item,
                codigo=str(ln.texto_codigo),
                descripcion=str(ln.texto_descripcion or ""),
                cantidad=str(ln.cantidad),
                precio_unitario=money(ln.precio_unitario),
                subtotal=money(ln.subtotal),
            )
        )

    totals = Totals(
        subtotal_lineas=money(presupuesto.subtotal_lineas),
        descuento=(money(presupuesto.descuento_monto) if presupuesto.descuento_monto and presupuesto.descuento_monto > 0 else None),
        envio=(money(presupuesto.envio) if getattr(presupuesto, "envio", None) and presupuesto.envio > 0 else None),
        total_neto=money(presupuesto.neto),
    )
    venc = presupuesto.fecha_vencimiento_pago.strftime("%d/%m/%Y") if presupuesto.fecha_vencimiento_pago else None
    copy_story, copy_pages_meta = build_story_for_commercial_doc(
        doc=doc,
        styles=styles,
        meta=meta,
        items=items,
        totals=totals,
        vencimiento_pago=venc,
        observaciones=None,
    )

    story.extend(copy_story)
    return copy_pages_meta


def presupuesto_pdf_response(presupuesto) -> HttpResponse:
    """PDF en dos páginas A4: copia Remito y copia Duplicado (mismo contenido)."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
    )
    styles = getSampleStyleSheet()
    story: list[Any] = []
    pages_meta: list[Any] = []
    pages_meta.extend(_append_copia_presupuesto_pdf(story, presupuesto, doc, styles, "Remito"))
    story.append(PageBreak())
    pages_meta.extend(_append_copia_presupuesto_pdf(story, presupuesto, doc, styles, "Duplicado"))

    generated = emission_datetime_str()

    def on_page(canvas, _doc):
        # Pie en 1 línea, con paginación por copia.
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
    ndoc = _numero_doc(presupuesto)
    safe = f"presupuesto ({ndoc})"
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{safe}.pdf"'
    return resp
