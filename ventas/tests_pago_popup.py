from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from personas.models import Vendedor
from caja.models import MovimientoCaja
from .models import Venta, PagoPedidoComprobante, PagoPedidoDetalle
from productos.models import Producto


class PagoPopupTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('pago_test',is_staff=True)
        self.client.force_login(self.user)
        self.vendedor=Vendedor.objects.create(nombre='Ana',apellido='Prueba')
        self.venta=Venta.objects.create(vendedor=self.vendedor,estado='PEN',subtotal_lineas=Decimal('1000'),aplica_comision=True,comision_porcentaje=5)
        self.url=reverse('venta_registrar_pago',args=[self.venta.pk])

    def pago(self,**datos):
        return self.client.post(self.url,{'modal':'1','fecha':'2026-10-11','medio_pago':'TRF',**datos})

    def test_transferencia_opcional_independiente_comision_y_sin_pdf_automatico(self):
        r=self.pago()
        self.assertEqual(r.status_code,200)
        self.assertContains(r,'Ver / imprimir PDF')
        self.assertNotContains(r,'iframe')
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.estado,'PAG')
        self.assertIsNone(self.venta.comision_liquidacion_pago_id)
        self.assertEqual(MovimientoCaja.objects.count(),1)
        self.pago()
        self.assertEqual(MovimientoCaja.objects.count(),1)

    def test_detalle_comprobante_persistente_descarga_protegida(self):
        archivo=SimpleUploadedFile('comprobante.pdf',b'%PDF-1.4\nprueba',content_type='application/pdf')
        r=self.pago(detalle='Banco de prueba',comprobante=archivo)
        self.assertEqual(r.status_code,200)
        datos=PagoPedidoDetalle.objects.get()
        self.assertEqual(datos.detalle,'Banco de prueba')
        url=reverse('venta_pago_comprobante',args=[datos.comprobante_id])
        response=self.client.get(url)
        self.assertEqual(b''.join(response.streaming_content),b'%PDF-1.4\nprueba')
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code,302)

    def test_invalidos_no_crean_cobros(self):
        for datos in [{'medio_pago':'CHQ'},{'fecha':'no es fecha'},{'comprobante':SimpleUploadedFile('a.pdf',b'no pdf')}]:
            self.assertEqual(self.pago(**datos).status_code,422)
            self.assertEqual(MovimientoCaja.objects.count(),0)

    def test_lote_atomico_y_un_solo_archivo(self):
        otra=Venta.objects.create(vendedor=self.vendedor,estado='PEN',subtotal_lineas=200)
        data={'modal':'1','fecha':'2026-10-11','medio_pago':'TRF','venta_id':[self.venta.pk,otra.pk]}
        url=reverse('venta_registrar_pago_masivo')
        from .servicios import venta_registrar_cobro_caja
        calls=[]
        def fallo(**kwargs):
            calls.append(1)
            if len(calls)>1:raise ValidationError('Prueba de rollback')
            return venta_registrar_cobro_caja(**kwargs)
        with patch('ventas.pago_popup.venta_registrar_cobro_caja',side_effect=fallo):
            self.assertEqual(self.client.post(url,data).status_code,422)
        self.assertEqual(MovimientoCaja.objects.count(),0)
        self.venta.refresh_from_db();self.assertEqual(self.venta.estado,'PEN')
        data['comprobante']=SimpleUploadedFile('a.pdf',b'%PDF-1.4\nprueba')
        self.assertEqual(self.client.post(url,data).status_code,200)
        self.assertEqual(MovimientoCaja.objects.count(),2)
        self.assertEqual(PagoPedidoComprobante.objects.count(),1)

    def test_popup_get_no_modifica_datos(self):
        r=self.client.get(self.url,{'modal':'1'})
        self.assertContains(r,'Confirmar pago')
        self.assertNotContains(r,'<!DOCTYPE')
        self.assertEqual(MovimientoCaja.objects.count(),0)

    def test_historial_filtros_conserva_seleccion_y_escapa_etiquetas(self):
        producto=Producto.objects.create(codigo='XSS001',descripcion='<script>prueba</script> & "Ácido"',costo=10,stock=1,tipo='MED')
        r=self.client.get(reverse('ventas_historial'),{'producto':producto.pk,'vendedor':self.vendedor.pk})
        self.assertEqual(r.status_code,200)
        self.assertContains(r,f'<option value="{producto.pk}" selected>')
        self.assertContains(r,'&lt;script&gt;')
        self.assertNotContains(r,'<script>prueba')
        self.assertContains(r,f'<option value="{self.vendedor.pk}" selected>')
