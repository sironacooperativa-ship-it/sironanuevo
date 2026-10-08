from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from personas.models import Vendedor
from caja.models import MovimientoCaja
from .models import Venta, ComisionLiquidacionPago

class ComisionesLoteTests(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_user('admin_comisiones_test',is_staff=True)
        self.client.force_login(self.admin)
        self.vendedor=Vendedor.objects.create(nombre='Ana',apellido='Comisiones')
        self.otro=Vendedor.objects.create(nombre='Otro',apellido='Vendedor')
        self.a=self.venta(self.vendedor,1000)
        self.b=self.venta(self.vendedor,2000)
        self.other=self.venta(self.otro,3000)
        self.sin_cobrar=self.venta(self.vendedor,4000,estado='PEN')
        self.liq=ComisionLiquidacionPago.objects.create(vendedor=self.vendedor,total=10)
        self.pagada=self.venta(self.vendedor,200,comision_liquidacion_pago=self.liq)
    def venta(self,vendedor,neto,**kwargs):
        return Venta.objects.create(vendedor=vendedor,estado=kwargs.pop('estado','PAG'),subtotal_lineas=Decimal(neto),aplica_comision=True,comision_porcentaje=Decimal(5),**kwargs)
    def pagar(self,ids,**extra):
        return self.client.post(reverse('ventas_comision_liquidacion_pagar'),{'vendedor':self.vendedor.pk,'liquidar_modo':'seleccion','venta_id':ids,**extra})
    def test_filtro_liquidables_excluye_pagadas_otro_vendedor_y_cliente_pendiente(self):
        response=self.client.get(reverse('ventas_comisiones'),{'vendedor':self.vendedor.pk,'estado_comision':'liquidables'})
        self.assertEqual(response.status_code,200)
        pedidos=response.context['pendiente_liquidar_global'][0]['ventas_liquidables']
        self.assertEqual({v.pk for v in pedidos},{self.a.pk,self.b.pk})
        detalle=[v for m in response.context['meses_detalle'] for b in m['por_vendedor'] for v in b['pedidos']]
        self.assertEqual({v.pk for v in detalle},{self.a.pk,self.b.pk})
        self.assertContains(response,'Pagar seleccionadas')
    def test_pdf_respeta_filtros_no_registra_pagos(self):
        response=self.client.get(reverse('ventas_comisiones'),{'vendedor':self.vendedor.pk,'estado_comision':'sin_pagar','export':'pdf'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual(ComisionLiquidacionPago.objects.count(),1)
        self.assertEqual(MovimientoCaja.objects.count(),0)
    def test_pago_seleccion_no_incluye_desmarcadas_y_no_duplica(self):
        response=self.pagar([self.a.pk])
        self.assertEqual(response.status_code,302)
        self.a.refresh_from_db();self.b.refresh_from_db()
        self.assertIsNotNone(self.a.comision_liquidacion_pago_id)
        self.assertIsNone(self.b.comision_liquidacion_pago_id)
        liq=self.a.comision_liquidacion_pago
        self.assertEqual(liq.total,Decimal('50.00'))
        self.assertEqual(liq.movimiento_caja.monto,Decimal('50.00'))
        self.assertEqual(liq.movimiento_caja.tipo,MovimientoCaja.Tipo.EGRESO)
        self.pagar([self.a.pk])
        self.assertEqual(MovimientoCaja.objects.count(),1)
    def test_pedido_ajeno_o_cliente_pendiente_rechaza_lote_entero(self):
        for wrong in [self.other,self.sin_cobrar,self.pagada]:
            self.pagar([self.a.pk,wrong.pk])
            self.assertEqual(MovimientoCaja.objects.count(),0)
            self.a.refresh_from_db();self.assertIsNone(self.a.comision_liquidacion_pago_id)
    def test_fechas_post_se_aplican_al_pago(self):
        ayer=timezone.now()-timedelta(days=5)
        Venta.objects.filter(pk=self.a.pk).update(creado_en=ayer)
        self.pagar([self.a.pk,self.b.pk],fecha_desde=timezone.localdate().isoformat())
        self.assertEqual(MovimientoCaja.objects.count(),0)
        self.pagar([self.b.pk],fecha_desde=timezone.localdate().isoformat())
        self.b.refresh_from_db();self.a.refresh_from_db()
        self.assertIsNotNone(self.b.comision_liquidacion_pago_id)
        self.assertIsNone(self.a.comision_liquidacion_pago_id)
    def test_casillas_vacias_no_registra_pago(self):
        self.pagar([])
        self.assertEqual(MovimientoCaja.objects.count(),0)

    def detalle_ids(self,response):
        return {v.pk for m in response.context['meses_detalle'] for b in m['por_vendedor'] for v in b['pedidos']}
    def test_impagas_independiente_de_cobro_pedido(self):
        response=self.client.get(reverse('ventas_comisiones'),{'vendedor':self.vendedor.pk,'estado_comision':'sin_pagar'})
        self.assertEqual(self.detalle_ids(response),{self.a.pk,self.b.pk,self.sin_cobrar.pk})
        self.assertContains(response,'Impaga al vendedor')
        self.assertContains(response,'Pago pedido')
        self.assertContains(response,'Pago comisión')
    def test_pagadas_segun_liquidacion_no_estado_pedido(self):
        Venta.objects.filter(pk=self.pagada.pk).update(estado='PEN')
        response=self.client.get(reverse('ventas_comisiones'),{'vendedor':self.vendedor.pk,'estado_comision':'pagadas'})
        self.assertEqual(self.detalle_ids(response),{self.pagada.pk})
        self.assertEqual(response.context['pendiente_liquidar_global'],[])
        self.assertContains(response,'Pagada al vendedor')
    def test_cobrar_pedido_no_paga_comision(self):
        from .servicios import venta_registrar_cobro_caja
        mov=MovimientoCaja(fecha=timezone.localdate(),medio_pago=MovimientoCaja.MedioPago.EFECTIVO)
        venta_registrar_cobro_caja(venta=self.sin_cobrar,mov=mov,user=self.admin)
        self.sin_cobrar.refresh_from_db()
        self.assertEqual(self.sin_cobrar.estado,'PAG')
        self.assertFalse(self.sin_cobrar.comision_pagada)
        self.assertEqual(ComisionLiquidacionPago.objects.count(),1)
        response=self.client.get(reverse('venta_detalle',args=[self.sin_cobrar.pk]))
        self.assertContains(response,'Pedido cobrado')
        self.assertContains(response,'Impaga al vendedor')
    def test_pagar_comision_no_cambia_cobro_pedido(self):
        estado=self.a.estado;mov=self.a.pago_movimiento_id
        self.pagar([self.a.pk]);self.a.refresh_from_db()
        self.assertEqual(self.a.estado,estado)
        self.assertEqual(self.a.pago_movimiento_id,mov)
        self.assertTrue(self.a.comision_pagada)
    def test_fechas_personalizadas_prevalecen_periodo_rapido(self):
        antiguo=timezone.now()-timedelta(days=70)
        Venta.objects.filter(pk=self.a.pk).update(creado_en=antiguo)
        fecha=timezone.localtime(antiguo).date().isoformat()
        params={'vendedor':self.vendedor.pk,'estado_comision':'sin_pagar','periodo':'mes','fecha_desde':fecha,'fecha_hasta':fecha}
        response=self.client.get(reverse('ventas_comisiones'),params)
        self.assertEqual(self.detalle_ids(response),{self.a.pk})
        self.assertEqual(response.context['f']['periodo'],'')
        self.pagar([self.a.pk],**{k:v for k,v in params.items() if k!='vendedor'})
        self.a.refresh_from_db();self.assertTrue(self.a.comision_pagada)
    def test_historial_respeta_vendedor_periodo_y_estado(self):
        antiguo=timezone.now()-timedelta(days=70)
        antigua=self.venta(self.vendedor,1000,comision_liquidacion_pago=self.liq)
        Venta.objects.filter(pk=antigua.pk).update(creado_en=antiguo)
        params={'vendedor':self.vendedor.pk,'estado_comision':'pagadas','fecha_desde':timezone.localdate().isoformat()}
        response=self.client.get(reverse('ventas_comisiones_historial'),params)
        filas=response.context['filas']
        self.assertEqual(len(filas),1)
        self.assertEqual(filas[0]['total_liquidado'],Decimal('10.00'))
        self.assertEqual({v.pk for item in filas[0]['liquidaciones'] for v in item['ventas']},{self.pagada.pk})
        self.assertEqual(filas[0]['pendientes'],[])
        params['estado_comision']='sin_pagar'
        response=self.client.get(reverse('ventas_comisiones_historial'),params)
        self.assertEqual(response.context['filas'][0]['liquidaciones'],[])
        self.assertEqual({v.pk for v in response.context['filas'][0]['pendientes']},{self.a.pk,self.b.pk,self.sin_cobrar.pk})
    def test_formulario_mensual_solo_paga_seleccionadas(self):
        response=self.client.get(reverse('ventas_comisiones'))
        self.assertNotContains(response,'value="todos"')
        self.assertContains(response,'name="liquidar_modo" value="seleccion"')
    def test_pdf_impagas_incluye_cliente_pendiente_sin_pagar(self):
        response=self.client.get(reverse('ventas_comisiones'),{'vendedor':self.vendedor.pk,'estado_comision':'sin_pagar','export':'pdf'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual(MovimientoCaja.objects.count(),0)
