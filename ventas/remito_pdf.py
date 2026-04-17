"""PDF tipo remito / comprobante de pedido (ReportLab)."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.money_decimal import format_monto_ars
from core.pdf_membrete import platypus_membrete


def _money(v) -> str:
    return format_monto_ars(v)


def _numero_remito(venta) -> str:
    """Número correlativo de remito (mismo criterio que el pedido, 8 dígitos)."""
    return str(venta.pk).zfill(8)


def remito_venta_pdf_response(venta) -> HttpResponse:
    """Genera un PDF con membrete Sirona y datos del pedido."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    story = []
    story.extend(platypus_membrete("Remito / comprobante de pedido", doc.width, styles))
    story.append(Spacer(1, 2 * mm))
    nrem = _numero_remito(venta)
    story.append(
        Paragraph(
            f"<b>Remito N.º {escape(nrem)}</b> &nbsp;·&nbsp; "
            f"Pedido #{venta.pk} &nbsp;·&nbsp; "
            f"Registro: {venta.creado_en.strftime('%d/%m/%Y %H:%M')}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 6 * mm))

    vend = venta.vendedor
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

    if venta.comprador_id:
        c = venta.comprador
        c_block = (
            f"<b>Comprador</b><br/>"
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
        story.append(Paragraph("<b>Comprador:</b> — sin asignar", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    lineas = list(venta.lineas.all())
    data = [["N.º", "Código", "Descripción", "Cant.", "P. unit.", "Subtotal"]]
    for n_item, ln in enumerate(lineas, start=1):
        data.append(
            [
                str(n_item),
                escape(str(ln.producto.codigo)),
                escape(ln.producto.descripcion[:80]),
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
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    tot_data = [
        ["Subtotal líneas", _money(venta.subtotal_lineas)],
        ["Descuento", _money(venta.descuento_monto)],
        ["Neto (orden de pago)", _money(venta.neto)],
    ]
    if venta.aplica_comision:
        tot_data.append([f"Comisión vendedor ({venta.comision_porcentaje} %)", _money(venta.monto_comision)])
    else:
        tot_data.append(["Comisión vendedor", "No aplica"])
    tot_data.append(["Ingreso en caja al cobrar", _money(venta.monto_ingreso_caja)])
    tot_data.append(
        [
            "Vencimiento pago (orden)",
            venta.fecha_vencimiento_pago.strftime("%d/%m/%Y") if venta.fecha_vencimiento_pago else "Sin indicar",
        ]
    )
    tt = Table(tot_data, colWidths=[tw * 0.55, tw * 0.45])
    nrows = len(tot_data)
    ing_row = nrows - 2
    neto_row = 2
    tt.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, neto_row), (1, neto_row), "Helvetica-Bold"),
                ("FONTNAME", (0, ing_row), (1, ing_row), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
                ("BACKGROUND", (0, neto_row), (-1, neto_row), colors.HexColor("#f0f9fb")),
                ("BACKGROUND", (0, ing_row), (-1, ing_row), colors.HexColor("#e8f8f0")),
            ]
        )
    )
    story.append(tt)
    story.append(Spacer(1, 6 * mm))

    if venta.estado == "PAG" and venta.pago_movimiento_id:
        mov = venta.pago_movimiento
        pay_lines = [
            "<b>Estado: PAGADA</b>",
            f"Fecha de cobro: {mov.fecha.strftime('%d/%m/%Y')}",
            f"Medio de pago: {escape(mov.get_medio_pago_display())}",
            f"Monto registrado: {_money(mov.monto)}",
        ]
        if mov.banco:
            pay_lines.append(f"Banco / texto: {escape(mov.banco)}")
        if mov.cuenta_bancaria_id:
            pay_lines.append(
                f"Cuenta: {escape(mov.cuenta_bancaria.banco)} — {escape(mov.cuenta_bancaria.cuenta)}"
            )
        if mov.numero_cheque:
            pay_lines.append(f"N.º cheque: {escape(mov.numero_cheque)}")
        if mov.fecha_vencimiento_cheque:
            pay_lines.append(f"Venc. cheque: {mov.fecha_vencimiento_cheque.strftime('%d/%m/%Y')}")
        pay_lines.append(f"Movimiento caja #{mov.pk}")
        story.append(Paragraph("<br/>".join(pay_lines), styles["Normal"]))
    else:
        if venta.fecha_vencimiento_pago:
            pend_txt = f"Fecha límite según orden: {venta.fecha_vencimiento_pago.strftime('%d/%m/%Y')}"
        else:
            pend_txt = "Sin fecha límite de pago indicada en la orden."
        story.append(
            Paragraph(
                f"<b>Estado: PENDIENTE DE PAGO</b><br/>{escape(pend_txt)}",
                styles["Normal"],
            )
        )

    doc.build(story)
    buf.seek(0)
    safe = f"Remito_{nrem}"
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{safe}.pdf"'
    return resp
