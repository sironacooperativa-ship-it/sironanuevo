"""Membrete común para PDFs: logo SIRONA, nombre del documento y fecha/hora de emisión."""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from django.contrib.staticfiles import finders
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle


def emission_datetime_str() -> str:
    """Fecha y hora local en que se emite el PDF: dd/mm/aaaa hh:mm."""
    return timezone.localtime().strftime("%d/%m/%Y %H:%M")


def platypus_membrete(doc_title: str, page_width: float, styles: Any) -> list[Any]:
    """
    Bloque inicial para SimpleDocTemplate: logo + título + «Emitido: …».
    `page_width` debe ser el ancho útil (p. ej. `doc.width`).
    """
    stamp = emission_datetime_str()
    logo_path = finders.find("img/sirona-logo.png")

    logo_w = 44 * mm
    gap = 5 * mm
    text_w = max(page_width - logo_w - gap, 80)

    if logo_path:
        logo = RLImage(logo_path, width=logo_w - 2 * mm, height=12 * mm)
    else:
        from reportlab.platypus import Spacer as RLSpacer

        logo = RLSpacer(logo_w, 12 * mm)

    p_title = Paragraph(
        f'<para><font size="14"><b>{escape(doc_title)}</b></font></para>',
        styles["Normal"],
    )
    p_stamp = Paragraph(
        f'<font size="9" color="#555555">Emitido: {escape(stamp)}</font>',
        styles["Normal"],
    )
    text_stack = Table([[p_title], [p_stamp]], colWidths=[text_w])
    text_stack.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    row = Table([[logo, text_stack]], colWidths=[logo_w, text_w])
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -1), 0.75, colors.HexColor("#cccccc")),
            ]
        )
    )
    return [row, Spacer(1, 7 * mm)]
