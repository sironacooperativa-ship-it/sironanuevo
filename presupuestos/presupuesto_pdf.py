"""PDF de presupuesto (ReportLab): dos hojas — Remito y Duplicado."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.utils import timezone as dj_tz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.money_decimal import format_monto_ars
from core.pdf_membrete import platypus_membrete

from .models import Presupuesto


def _money(v) -> str:
    return format_monto_ars(v)


def _numero_doc(presupuesto) -> str:
    return str(presupuesto.pk).zfill(8)


def _titulo_membrete(presupuesto, copia_label: str) -> str:
    ndoc = _numero_doc(presupuesto)
    if presupuesto.estado == Presupuesto.Estado.APROBADO:
        return f"Orden de compra N.º {ndoc} — Copia {copia_label}"
    return f"Presupuesto N.º {ndoc} — Copia {copia_label}"


def _append_copia_presupuesto_pdf(story, presupuesto, doc, styles, copia_label: str) -> None:
    """Una hoja completa (mismo contenido; copia Remito / Duplicado)."""
    story.extend(platypus_membrete(_titulo_membrete(presupuesto, copia_label), doc.width, styles))
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            f"Emitido: {presupuesto.creado_en.strftime('%d/%m/%Y %H:%M')}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 6 * mm))

    vend = presupuesto.vendedor
    v_block = (
        f"<b>Vendedor</b><br/>"
        f"Código: {escape(str(vend.codigo))}<br/>"
        f"{escape(vend.apellido)}, {escape(vend.nombre)}<br/>"
    )
    if vend.telefono:
        v_block += f"Tel.: {escape(vend.telefono)}<br/>"
    if vend.mail:
        v_block += f"Email: {escape(vend.mail)}<br/>"
    if vend.direccion:
        v_block += f"Dir.: {escape(vend.direccion)}<br/>"
    story.append(Paragraph(v_block, styles["Normal"]))
    story.append(Spacer(1, 4 * mm))

    if presupuesto.comprador_id:
        c = presupuesto.comprador
        c_block = (
            f"<b>Cliente / Comprador</b><br/>"
            f"Código: {escape(str(c.codigo))}<br/>"
            f"{escape(c.apellido)}, {escape(c.nombre)}<br/>"
        )
        if c.telefono:
            c_block += f"Tel.: {escape(c.telefono)}<br/>"
        if c.mail:
            c_block += f"Email: {escape(c.mail)}<br/>"
        if c.direccion:
            c_block += f"Dir.: {escape(c.direccion)}<br/>"
        story.append(Paragraph(c_block, styles["Normal"]))
    else:
        story.append(Paragraph("<b>Cliente / Comprador:</b> — sin asignar", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    lineas = list(presupuesto.lineas.all())
    data = [["N.º", "Código", "Descripción", "Cant.", "P. unit.", "Subtotal"]]
    for n_item, ln in enumerate(lineas, start=1):
        desc = ln.texto_descripcion
        if len(desc) > 72:
            desc = desc[:69] + "…"
        data.append(
            [
                str(n_item),
                escape(str(ln.texto_codigo)),
                escape(desc),
                str(ln.cantidad),
                _money(ln.precio_unitario),
                _money(ln.subtotal),
            ]
        )
    if len(data) == 1:
        data.append(["—", "—", "Sin líneas", "", "", ""])

    tw = doc.width
    col_w = [tw * 0.06, tw * 0.11, tw * 0.33, tw * 0.08, tw * 0.18, tw * 0.24]
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0097B2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    tot_data = [
        ["Subtotal líneas", _money(presupuesto.subtotal_lineas)],
        ["Descuento", _money(presupuesto.descuento_monto)],
        ["Neto", _money(presupuesto.neto)],
        [
            "Vencimiento pago"
            + (
                ""
                if presupuesto.estado == Presupuesto.Estado.APROBADO
                else " (si se confirma como pedido)"
            ),
            presupuesto.fecha_vencimiento_pago.strftime("%d/%m/%Y")
            if presupuesto.fecha_vencimiento_pago
            else "Sin indicar",
        ],
        ["Estado", escape(presupuesto.get_estado_display())],
    ]
    tw_tot = doc.width
    tt = Table(tot_data, colWidths=[tw_tot * 0.55, tw_tot * 0.45])
    tt.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 2), (1, 2), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
                ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#f0f9fb")),
            ]
        )
    )
    story.append(tt)

    venta = getattr(presupuesto, "venta", None)
    pagado = (
        venta is not None
        and venta.estado == "PAG"
        and getattr(venta, "pago_movimiento", None) is not None
    )

    if presupuesto.venta_id:
        story.append(Spacer(1, 4 * mm))
        story.append(
            Paragraph(
                f"<b>Pedido generado:</b> #{presupuesto.venta_id}",
                styles["Normal"],
            )
        )

    if pagado:
        mov = venta.pago_movimiento
        pago_dt = (
            dj_tz.localtime(mov.creado_en).strftime("%d/%m/%Y %H:%M")
            if mov.creado_en
            else "—"
        )
        usr = mov.creado_por.get_username() if mov.creado_por_id else "—"
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(
                f"<b><font color=\"#198754\">PAGADO</font></b><br/>"
                f"<font size=\"9\">Fecha imputación: {escape(pago_dt)}<br/>"
                f"Usuario: {escape(usr)}</font>",
                styles["Normal"],
            )
        )


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
    story: list = []
    _append_copia_presupuesto_pdf(story, presupuesto, doc, styles, "Remito")
    story.append(PageBreak())
    _append_copia_presupuesto_pdf(story, presupuesto, doc, styles, "Duplicado")

    doc.build(story)
    buf.seek(0)
    ndoc = _numero_doc(presupuesto)
    pref = "Orden_compra" if presupuesto.estado == Presupuesto.Estado.APROBADO else "Presupuesto"
    safe = f"{pref}_{ndoc}"
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{safe}.pdf"'
    return resp
