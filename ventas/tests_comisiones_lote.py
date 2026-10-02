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
    def test_filtro_sin_pagar_excluye_pagadas_otro_vendedor_y_cliente_pendiente(self):
        response=self.client.get(reverse('ventas_comisiones'),{'vendedor':self.vendedor.pk,'estado_comision':'sin_pagar'})
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
