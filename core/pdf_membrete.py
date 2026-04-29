"""Membrete común para PDFs: logo SIRONA, nombre del documento y fecha/hora de emisión."""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from django.contrib.staticfiles import finders
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle


def emission_datetime_str() -> str:
    """Fecha y hora local en que se emite el PDF: dd/mm/aaaa hh:mm."""
    return timezone.localtime().strftime("%d/%m/%Y %H:%M")


def proportional_logo(*, max_w: float, max_h: float) -> RLImage | None:
    """
    Logo Sirona con proporción real (sin deformar).
    Escala dentro de la caja (max_w × max_h) manteniendo aspect ratio.
    """
    logo_path = finders.find("img/sirona-logo.png")
    if not logo_path:
        return None
    try:
        # "proportional": width/height act as bounding box, aspect ratio preserved.
        # This prevents any accidental stretching even if callers pass max_w/max_h.
        im = RLImage(logo_path, width=max_w, height=max_h, kind="proportional")
        im.hAlign = "LEFT"
        return im
    except Exception:
        return None


def platypus_membrete(doc_title: str, page_width: float, styles: Any) -> list[Any]:
    """
    Bloque inicial para SimpleDocTemplate: logo + título + «Emitido: …».
    `page_width` debe ser el ancho útil (p. ej. `doc.width`).
    """
    stamp = emission_datetime_str()

    logo_w = 44 * mm
    gap = 5 * mm
    text_w = max(page_width - logo_w - gap, 80)

    # Alto objetivo ~40–60px visual: 18mm ≈ 51pt @72dpi
    logo = proportional_logo(max_w=logo_w - 2 * mm, max_h=18 * mm)
    if logo is None:
        from reportlab.platypus import Spacer as RLSpacer

        logo = RLSpacer(logo_w, 18 * mm)

    p_title = Paragraph(
        f'<para leading="16"><font size="14"><b>{escape(doc_title)}</b></font></para>',
        styles["Normal"],
    )
    p_stamp = Paragraph(
        f'<para leading="12"><font size="9" color="#555555">Emitido: {escape(stamp)}</font></para>',
        styles["Normal"],
    )
    text_stack = Table([[p_title], [p_stamp]], colWidths=[text_w])
    text_stack.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
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
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, -1), 0.75, colors.HexColor("#cccccc")),
            ]
        )
    )
    # Separación extra para que la tabla no quede pegada al membrete.
    return [row, Spacer(1, 10 * mm)]
