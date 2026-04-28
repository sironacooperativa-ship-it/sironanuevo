"""PDF de lista de precios (membrete SIRONA + tabla). Compartido staff y portal vendedor."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from django.http import FileResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from core.money_decimal import format_monto_ars
from core.pdf_membrete import platypus_membrete

from .models import ListaPrecioItem, ListaPrecios, Producto


def filas_lista_precios(lista: ListaPrecios) -> list[tuple[Producto, Decimal]]:
    # Farmacia/PDF: solo productos marcados en lista (igual que export y ficha).
    if lista.es_farmacia:
        qs = Producto.objects.filter(habilitado=True, en_lista_precios=True).order_by(
            "tipo", "descripcion", "codigo"
        )
        return [(p, p.precio_venta) for p in qs]
    items = (
        ListaPrecioItem.objects.filter(lista=lista, producto__habilitado=True)
        .select_related("producto")
        .order_by("producto__tipo", "producto__descripcion", "producto__codigo")
    )
    return [(i.producto, i.precio_venta) for i in items]


def lista_precios_pdf_file_response(*, lista: ListaPrecios) -> FileResponse:
    titulo = f"Lista de precios — {lista.nombre}"
    filas = filas_lista_precios(lista)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    story = platypus_membrete(titulo, doc.width, styles)

    headers = ["Código", "Tipo", "Descripción", "Precio"]
    data = [headers]
    for p, precio in filas:
        desc = p.descripcion
        if len(desc) > 95:
            desc = desc[:92] + "..."
        data.append([p.codigo, p.get_tipo_display(), desc, format_monto_ars(precio)])

    if len(data) == 1:
        data.append(["—", "—", "—", "—"])

    tw = doc.width
    col_w = [tw * 0.15, tw * 0.18, tw * 0.45, tw * 0.22]
    t = Table(data, colWidths=col_w, repeatRows=1)
    # Minimalista (sin "dashboard"): solo tabla limpia con encabezado sutil.
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#CBD5E1")),
                ("LINEABOVE", (0, 0), (-1, 0), 0.75, colors.HexColor("#CBD5E1")),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ALIGN", (0, 1), (0, -1), "LEFT"),
                ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    story.append(t)
    doc.build(story)
    buffer.seek(0)

    fecha = timezone.localtime().strftime("%d-%m-%Y")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in titulo)[:60]
    filename = f"{safe}_{fecha}.pdf"
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type="application/pdf")
