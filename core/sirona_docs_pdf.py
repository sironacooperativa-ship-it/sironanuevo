"""
Plantilla única de documentos comerciales Sirona (ReportLab/Platypus).

Objetivo:
- Mismo formato para Presupuestos / Pedidos / Remitos / Ventas / Duplicados.
- Header compacto en columnas.
- Tabla compacta con wrapping de Descripción (sin superposición).
- Máximo 15 productos por página.
- Totales solo en la última página (por copia).
- Pie en 1 línea: disclaimer | generado | página X de Y (por copia).

Importante: NO toca cálculos ni lógica de negocio. Solo presentación/paginación.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Iterable, Sequence
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .money_decimal import format_monto_ars
from .pdf_membrete import emission_datetime_str, proportional_logo


MAX_ITEMS_PER_PAGE = 15


@dataclass(frozen=True)
class PartyInfo:
    codigo: str
    nombre: str
    direccion: str = ""


@dataclass(frozen=True)
class DocMeta:
    doc_type: str  # PRESUPUESTO / REMITO / PEDIDO / VENTA / DUPLICADO ...
    doc_number: str  # ya formateado (ej. 00000026)
    copy_label: str  # Remito / Duplicado / Original / Pedido ...
    fecha_emision: str  # dd/mm/aaaa hh:mm
    estado: str  # display
    vendedor: PartyInfo
    cliente: PartyInfo | None


@dataclass(frozen=True)
class LineItem:
    numero: int
    codigo: str
    marca: str
    descripcion: str
    cantidad: str
    precio_unitario: str
    subtotal: str


@dataclass(frozen=True)
class Totals:
    subtotal_lineas: str
    descuento: str | None  # None si 0 o no corresponde
    total_neto: str
    envio: str | None = None  # None si 0 o no corresponde


@dataclass(frozen=True)
class PageMeta:
    copy_label: str
    page_in_copy: int
    pages_in_copy: int
    doc_line: str


def _chunked(seq: Sequence[Any], size: int) -> list[list[Any]]:
    return [list(seq[i : i + size]) for i in range(0, len(seq), size)] or [[]]


def _sirona_header(*, meta: DocMeta, doc_width: float, styles, is_continuation: bool) -> list[Any]:
    """
    Header compacto:
    - arriba: logo + marca (izq) | doc type + N° + Copia (+ continuidad si aplica) (der)
    - abajo: 3 columnas (Doc | Vendedor | Cliente)
    """
    # Mantener logo nítido y proporcional. Alto levemente mayor sin romper header compacto.
    logo = proportional_logo(max_w=30 * mm, max_h=14 * mm)
    left_stack_rows: list[list[Any]] = []
    if logo is not None:
        left_stack_rows.append([logo])
    left_stack_rows.append(
        [
            Paragraph(
                '<para leading="11">'
                '<font size="10"><b>SIRONA Cooperativa</b></font><br/>'
                '<font size="8" color="#64748b">Sistema de Gestión</font>'
                "</para>",
                styles["Normal"],
            )
        ]
    )
    left_stack = Table(left_stack_rows, colWidths=[doc_width * 0.55])
    left_stack.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    cont = '<br/><font size="8" color="#64748b">Continuación</font>' if is_continuation else ""
    right = Paragraph(
        f'<para align="right" leading="11">'
        f'<font size="10" color="#007aff"><b>{escape(meta.doc_type.upper())}</b></font><br/>'
        f'<font size="10"><b>N.º {escape(meta.doc_number)}</b></font><br/>'
        f'<font size="8" color="#64748b">Copia: {escape(meta.copy_label)}</font>'
        f"{cont}"
        f"</para>",
        styles["Normal"],
    )

    top = Table([[left_stack, right]], colWidths=[doc_width * 0.60, doc_width * 0.40])
    top.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
            ]
        )
    )

    def kv(label: str, value: str) -> str:
        return f'<font size="7" color="#64748b"><b>{escape(label)}</b></font><br/><font size="8">{escape(value)}</font>'

    doc_col = Paragraph(
        "<para leading=\"10\">"
        + kv("DATOS DEL DOCUMENTO", "")
        + "<br/>"
        + kv("Número", meta.doc_number)
        + "<br/>"
        + kv("Fecha emisión", meta.fecha_emision)
        + "<br/>"
        + kv("Estado", meta.estado)
        + "<br/>"
        + kv("Copia", meta.copy_label)
        + "</para>",
        styles["Normal"],
    )

    vend = meta.vendedor
    vend_col = Paragraph(
        "<para leading=\"10\">"
        + kv("VENDEDOR", "")
        + "<br/>"
        + kv("Código", vend.codigo)
        + "<br/>"
        + kv("Nombre", vend.nombre)
        + "</para>",
        styles["Normal"],
    )

    if meta.cliente is None:
        cli_col = Paragraph("<para leading=\"10\">" + kv("CLIENTE / COMPRADOR", "—") + "</para>", styles["Normal"])
    else:
        c = meta.cliente
        extra_addr = f"<br/>{kv('Dirección', c.direccion)}" if (c.direccion or "").strip() else ""
        cli_col = Paragraph(
            "<para leading=\"10\">"
            + kv("CLIENTE / COMPRADOR", "")
            + "<br/>"
            + kv("Código", c.codigo)
            + "<br/>"
            + kv("Nombre", c.nombre)
            + extra_addr
            + "</para>",
            styles["Normal"],
        )

    cols = Table([[doc_col, vend_col, cli_col]], colWidths=[doc_width * 0.34, doc_width * 0.33, doc_width * 0.33])
    cols.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    return [top, cols, Spacer(1, 4 * mm)]


def _line_table(*, items: Sequence[LineItem], doc_width: float, styles) -> Table:
    base = ParagraphStyle(
        "sirona_doc_base",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
    )
    desc_style = ParagraphStyle(
        "sirona_doc_desc",
        parent=base,
        leading=10,
        wordWrap="CJK",
    )

    # Limitar a 2 líneas aprox (sin romper layout): truncado defensivo.
    def clamp_desc(s: str) -> str:
        ss = (s or "").strip()
        if len(ss) <= 120:
            return ss
        return ss[:117] + "…"

    data: list[list[Any]] = [["N.º", "Código", "Marca", "Descripción", "Cant.", "P. unit.", "Subtotal"]]
    for it in items:
        data.append(
            [
                Paragraph(escape(str(it.numero)), base),
                Paragraph(escape(it.codigo), base),
                Paragraph(escape((it.marca or "").strip() or "—"), base),
                Paragraph(escape(clamp_desc(it.descripcion)), desc_style),
                Paragraph(escape(it.cantidad), base),
                Paragraph(escape(it.precio_unitario), base),
                Paragraph(escape(it.subtotal), base),
            ]
        )
    if len(data) == 1:
        data.append(["—", "—", "—", "Sin líneas", "", "", ""])

    col_w = [
        doc_width * 0.05,
        doc_width * 0.10,
        doc_width * 0.12,
        doc_width * 0.35,
        doc_width * 0.07,
        doc_width * 0.14,
        doc_width * 0.14,
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
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (4, 1), (4, -1), "CENTER"),
                ("ALIGN", (5, 1), (6, -1), "RIGHT"),
            ]
        )
    )
    return t


def _totals_box(*, totals: Totals, doc_width: float) -> Table:
    rows: list[list[str]] = [["Subtotal líneas", totals.subtotal_lineas]]
    if totals.descuento:
        rows.append(["Descuento", totals.descuento])
    if totals.envio:
        rows.append(["Envío", totals.envio])
    rows.append(["TOTAL NETO", totals.total_neto])

    t = Table(rows, colWidths=[doc_width * 0.56, doc_width * 0.44], hAlign="RIGHT")
    total_row = len(rows) - 1
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, total_row), (-1, total_row), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0, total_row), (-1, total_row), colors.HexColor("#eff6ff")),
                ("TEXTCOLOR", (0, total_row), (-1, total_row), colors.HexColor("#007aff")),
            ]
        )
    )
    return t


def build_story_for_commercial_doc(
    *,
    doc: SimpleDocTemplate,
    styles,
    meta: DocMeta,
    items: Sequence[LineItem],
    totals: Totals | None,
    vencimiento_pago: str | None = None,
    observaciones: str | None = None,
) -> tuple[list[Any], list[PageMeta]]:
    """
    Devuelve: (story, pages_meta)
    - story: platypus story ya paginada (15 items por página)
    - pages_meta: mapeo 1:1 con páginas físicas para footer/paginación por copia
    """
    chunks = _chunked(list(items), MAX_ITEMS_PER_PAGE)
    pages_in_copy = max(len(chunks), 1)
    pages_meta: list[PageMeta] = []
    story: list[Any] = []

    for idx, chunk in enumerate(chunks, start=1):
        is_last = idx == pages_in_copy
        is_cont = idx > 1
        pages_meta.append(
            PageMeta(
                copy_label=meta.copy_label,
                page_in_copy=idx,
                pages_in_copy=pages_in_copy,
                doc_line=f"{meta.doc_type.upper()} N.º {meta.doc_number} — Copia {meta.copy_label}",
            )
        )
        story.extend(_sirona_header(meta=meta, doc_width=doc.width, styles=styles, is_continuation=is_cont))
        story.append(_line_table(items=chunk, doc_width=doc.width, styles=styles))

        # Vencimiento/observaciones solo si hay contenido y SOLO en última página.
        if is_last:
            extra_blocks: list[Any] = []
            if vencimiento_pago:
                extra_blocks.append(
                    Paragraph(
                        f'<para leading="10"><font size="8" color="#64748b"><b>Vencimiento de pago:</b> {escape(vencimiento_pago)}</font></para>',
                        styles["Normal"],
                    )
                )
            if observaciones:
                obs = (observaciones or "").strip()
                if obs:
                    extra_blocks.append(
                        Paragraph(
                            f'<para leading="10"><font size="8" color="#64748b"><b>Observaciones:</b> {escape(obs)}</font></para>',
                            styles["Normal"],
                        )
                    )
            if extra_blocks:
                story.append(Spacer(1, 3 * mm))
                story.extend(extra_blocks)

            if totals is not None:
                story.append(Spacer(1, 5 * mm))
                story.append(_totals_box(totals=totals, doc_width=doc.width * 0.52))
        else:
            # Continuación discreta sin ocupar demasiado.
            story.append(Spacer(1, 3 * mm))
            story.append(
                Paragraph(
                    '<para align="right" leading="10"><font size="8" color="#64748b">Continúa en página siguiente</font></para>',
                    styles["Normal"],
                )
            )

        if idx != pages_in_copy:
            from reportlab.platypus import PageBreak

            story.append(PageBreak())

    return story, pages_meta


def pages_count_for_items(n_items: int) -> int:
    return max(int(ceil(max(n_items, 1) / float(MAX_ITEMS_PER_PAGE))), 1)


def money(v) -> str:
    return format_monto_ars(v)

