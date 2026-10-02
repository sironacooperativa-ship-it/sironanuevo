"""Detalle de comisiones filtradas, sin registrar una liquidación."""
from io import BytesIO
from xml.sax.saxutils import escape
from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from core.pdf_membrete import platypus_membrete
from core.money_decimal import q2, format_monto_ars


def comisiones_detalle_pdf_response(ventas, filtros, params):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12*mm,
                           rightMargin=12*mm, topMargin=10*mm, bottomMargin=14*mm)
    styles = getSampleStyleSheet()
    cell = ParagraphStyle('comision_detalle', parent=styles['Normal'], fontSize=8, leading=11)
    head = ParagraphStyle('comision_cabecera', parent=cell, fontName='Helvetica-Bold', textColor=colors.white)
    p = lambda value: Paragraph(escape(str(value)), cell)
    story = list(platypus_membrete('Detalle de comisiones', doc.width, styles))
    estados = {'sin_pagar': 'Sin pagar al vendedor (pedidos cobrados)', 'pagadas': 'Pagadas al vendedor'}
    info = estados.get(params.get('estado_comision'), 'Todas las comisiones')
    vendedor = (ventas[0].vendedor if ventas else 'ID ' + str(filtros['vendedor'])) if filtros.get('vendedor') else 'Todos'
    story += [Paragraph(escape(f'Vendedor: {vendedor} | {info}'), styles['Normal'])]
    periodo = {'7d':'Últimos 7 días', '30d':'Últimos 30 días', 'mes':'Mes actual', 'mes_ant':'Mes anterior'}.get(params.get('periodo'), 'Personalizado / todos')
    fechas = f"Desde: {filtros.get('fecha_desde') or '-'} | Hasta: {filtros.get('fecha_hasta') or '-'}"
    story += [Paragraph(escape(f'Período: {periodo} | {fechas}'), styles['Normal']), Spacer(1, 8)]
    headers = ['Pedido', 'Fecha', 'Vendedor', 'Comprador', 'Neto', '%', 'Comisión', 'Estado comisión']
    data = [[Paragraph(escape(h), head) for h in headers]]
    for v in ventas:
        estado = 'Pagada al vendedor' if v.comision_liquidacion_pago_id else ('Sin pagar al vendedor' if v.estado == 'PAG' else 'Cliente aún no pagó')
        data.append([p(f'#{v.pk}'), p(timezone.localtime(v.creado_en).strftime('%d/%m/%Y')),
                     p(v.vendedor), p(v.comprador or '-'), p(format_monto_ars(v.neto)),
                     p(v.comision_porcentaje), p(format_monto_ars(v.monto_comision)), p(estado)])
    if ventas:
        weights = [0.055, 0.085, 0.18, 0.21, 0.12, 0.045, 0.12, 0.185]
        table = Table(data, colWidths=[doc.width*w for w in weights], repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0097B2')),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f0f9fb')]),
            ('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#0097B2')),
            ('GRID',(0,1),(-1,-1),.25,colors.HexColor('#dddddd')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),
            ('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),6),
            ('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        story.append(table)
    else:
        story.append(Paragraph('No hay comisiones con estos filtros.', styles['Normal']))
    total = q2(sum(v.monto_comision for v in ventas))
    story += [Spacer(1,10), Paragraph(escape(f'{len(ventas)} pedidos | Total comisiones: {format_monto_ars(total)}'), styles['Heading3'])]
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica',8)
        canvas.drawString(12*mm,8*mm,'Detalle informativo - no constituye constancia de pago')
        canvas.drawRightString(landscape(A4)[0]-12*mm,8*mm,f'Página {document.page}')
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    response = HttpResponse(buf.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="comisiones_detalle.pdf"'
    return response
