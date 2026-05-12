"""PDF constancia de liquidación de comisiones — mismo lenguaje visual que pedidos/remitos (Sirona / ReportLab)."""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from io import BytesIO
from typing import Sequence
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.money_decimal import q2
from core.pdf_membrete import emission_datetime_str
from core.sirona_docs_pdf import (
    MAX_ITEMS_PER_PAGE,
    DocMeta,
    PageMeta,
    PartyInfo,
    _chunked,
    _sirona_header,
    money,
)


_MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _local_dt(dt):
    if dt is None:
        return None
    return timezone.localtime(dt) if timezone.is_aware(dt) else dt


def _group_sales(sales: Sequence, agrupar_periodo: str) -> list[tuple[str, list]]:
    """Devuelve [(etiqueta_grupo, [ventas...]), ...] en orden cronológico."""
    if agrupar_periodo not in ("mes", "semana"):
        return [("", sorted(sales, key=lambda s: (_local_dt(s.creado_en) or s.creado_en, s.pk)))]

    buckets: OrderedDict[tuple, dict] = OrderedDict()
    ordered = sorted(sales, key=lambda s: (_local_dt(s.creado_en) or s.creado_en, s.pk))
    for s in ordered:
        dt = _local_dt(s.creado_en) or s.creado_en
        if agrupar_periodo == "mes":
            k = (dt.year, dt.month)
            label = f"{_MESES[dt.month - 1].capitalize()} {dt.year}"
        else:
            iso = dt.isocalendar()
            k = (iso.year, iso.week)
            label = f"Semana ISO {iso.week} — {iso.year}"
        if k not in buckets:
            buckets[k] = {"label": label, "items": []}
        buckets[k]["items"].append(s)
    return [(b["label"], b["items"]) for b in buckets.values()]


def _comision_table(chunk, doc_width: float, styles) -> Table:
    base = ParagraphStyle(
        "sirona_com_base",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
    )
    desc_style = ParagraphStyle(
        "sirona_com_desc",
        parent=base,
        leading=10,
        wordWrap="CJK",
    )

    def clamp(s: str, n: int = 72) -> str:
        ss = (s or "").strip()
        return ss if len(ss) <= n else ss[: n - 1] + "…"

    headers = ["Pedido", "Fecha", "Cliente", "Neto", "% com.", "Comisión"]
    data: list[list] = [[Paragraph(f"<b>{escape(h)}</b>", base) for h in headers]]
    for s in chunk:
        cli = "—"
        if getattr(s, "comprador_id", None):
            c = s.comprador
            cli = clamp(f"{c.apellido}, {c.nombre}")
        dt = _local_dt(s.creado_en) or s.creado_en
        data.append(
            [
                Paragraph(escape(str(s.pk)), base),
                Paragraph(escape(dt.strftime("%d/%m/%Y %H:%M")), base),
                Paragraph(escape(cli), desc_style),
                Paragraph(escape(money(s.neto)), base),
                Paragraph(escape(f"{s.comision_porcentaje}"), base),
                Paragraph(escape(money(s.monto_comision)), base),
            ]
        )
    if len(data) == 1:
        data.append([Paragraph("—", base)] * 6)

    col_w = [
        doc_width * 0.10,
        doc_width * 0.16,
        doc_width * 0.30,
        doc_width * 0.14,
        doc_width * 0.10,
        doc_width * 0.20,
    ]
    t = Table(data, colWidths=col_w, repeatRows=1, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eff6ff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 7.2),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#cbd5e1")),
                ("GRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("ALIGN", (3, 1), (5, -1), "RIGHT"),
            ]
        )
    )
    return t


def _totals_comision(doc_width: float, total: Decimal, n_pedidos: int) -> Table:
    rows = [
        ["Pedidos incluidos", str(n_pedidos)],
        ["Total liquidado", money(total)],
    ]
    t = Table(rows, colWidths=[doc_width * 0.56, doc_width * 0.44], hAlign="RIGHT")
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#eff6ff")),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#007aff")),
            ]
        )
    )
    return t


def comision_constancia_pdf_response(liq, sales: Sequence, *, agrupar_periodo: str = "ninguno") -> HttpResponse:
    """Genera PDF A4 vertical, cabecera tipo pedido y detalle de comisiones (opcionalmente agrupado por mes o semana ISO)."""
    sales = list(sales)
    if not sales:
        raise ValueError("sales vacío")

    vend = liq.vendedor
    creado = _local_dt(liq.creado_en) if liq.creado_en else None
    fecha_liq = liq.fecha_liquidacion or (creado.date() if creado else timezone.localdate())

    meta = DocMeta(
        doc_type="LIQUIDACIÓN",
        doc_number=str(liq.pk).zfill(8),
        copy_label="Comisiones",
        fecha_emision=creado.strftime("%d/%m/%Y %H:%M") if creado else fecha_liq.strftime("%d/%m/%Y"),
        estado="Liquidada",
        vendedor=PartyInfo(codigo=str(vend.codigo), nombre=f"{vend.apellido}, {vend.nombre}"),
        cliente=None,
    )

    groups = _group_sales(sales, agrupar_periodo)
    tasks: list[tuple[str | None, list]] = []
    for group_label, items in groups:
        for i, chunk in enumerate(_chunked(items, MAX_ITEMS_PER_PAGE)):
            label = group_label if (group_label and i == 0) else None
            tasks.append((label, chunk))

    sub = Decimal("0.00")
    for s in sales:
        sub = q2(sub + s.monto_comision)

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
    story: list = []
    n_pages = len(tasks)
    pages_meta: list[PageMeta] = []
    for idx, (show_label, chunk) in enumerate(tasks, start=1):
        pages_meta.append(
            PageMeta(
                copy_label=meta.copy_label,
                page_in_copy=idx,
                pages_in_copy=n_pages,
                doc_line=f"{meta.doc_type.upper()} N.º {meta.doc_number} — {meta.copy_label}",
            )
        )
        story.extend(_sirona_header(meta=meta, doc_width=doc.width, styles=styles, is_continuation=idx > 1))
        if show_label:
            story.append(
                Paragraph(
                    f'<para leading="11"><font size="9" color="#0f172a"><b>{escape(show_label)}</b></font></para>',
                    styles["Normal"],
                )
            )
            story.append(Spacer(1, 2 * mm))
        story.append(_comision_table(chunk, doc.width, styles))
        if idx < n_pages:
            story.append(PageBreak())

    story.append(Spacer(1, 5 * mm))
    story.append(_totals_comision(doc.width, sub, len(sales)))

    extras = []
    extras.append(
        Paragraph(
            f'<para leading="10"><font size="8" color="#64748b"><b>Fecha liquidación:</b> {escape(fecha_liq.strftime("%d/%m/%Y"))}'
            f' · <b>Mov. caja:</b> {escape("#" + str(liq.movimiento_caja_id)) if liq.movimiento_caja_id else "—"}'
            f' · <b>Agrupación PDF:</b> {escape({"ninguno": "Sin agrupar", "mes": "Por mes calendario", "semana": "Por semana ISO"}.get(agrupar_periodo, agrupar_periodo))}'
            "</font></para>",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.extend(extras)

    generated = emission_datetime_str()

    def on_page(canvas, _doc):
        pnum = canvas.getPageNumber()
        pm = pages_meta[pnum - 1] if 1 <= pnum <= len(pages_meta) else None
        pages_str = (
            f"Página {pm.page_in_copy} de {pm.pages_in_copy}" if pm is not None else f"Página {pnum}"
        )
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
        canvas.setLineWidth(0.6)
        y = _doc.bottomMargin - 2.5 * mm
        canvas.line(_doc.leftMargin, y, _doc.leftMargin + _doc.width, y)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.setFont("Helvetica", 8)
        footer = f"Constancia de liquidación de comisiones. | Generado: {generated} | {pages_str}"
        canvas.drawString(_doc.leftMargin, y - 8, footer)
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    buf.seek(0)
    safe = f"Liquidacion_comisiones_{liq.pk}"
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{safe}.pdf"'
    return resp
