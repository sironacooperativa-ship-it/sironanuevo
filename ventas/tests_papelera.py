from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caja.models import MovimientoCaja
from bancos.models import CuentaBancaria, MovimientoCuentaBancaria
from calendario.models import Evento
from personas.models import Vendedor
from productos.models import Producto
from presupuestos.models import Presupuesto, PresupuestoLinea
from .models import Venta, VentaLinea, ComisionLiquidacionPago, ArmadoColectivoGuardado
from .servicios import cambiar_papelera_venta, enviar_venta_a_papelera


class PapeleraTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user('admin_papelera', is_staff=True)
        self.user = get_user_model().objects.create_user('vendedor_papelera')
        self.vendedor = Vendedor.objects.create(nombre='Ana', apellido='Prueba', usuario=self.user)
        self.otro = Vendedor.objects.create(nombre='Otro', apellido='Vendedor')
        self.producto = Producto.objects.create(codigo='T00001', descripcion='Prueba', tipo='OT', stock=8)
        self.venta = Venta.objects.create(vendedor=self.vendedor, subtotal_lineas=Decimal('100'), fecha_vencimiento_pago=date.today())
        VentaLinea.objects.create(venta=self.venta, producto=self.producto, cantidad=2, precio_unitario=50, subtotal=100)
        self.evento = Evento.objects.create(fecha=date.today(), tipo=Evento.Tipo.PEDIDO, titulo=f'Pago pendiente — Pedido #{self.venta.pk}', realizado=True, descripcion='Texto original')
        self.presupuesto = Presupuesto.objects.create(vendedor=self.vendedor, estado=Presupuesto.Estado.APROBADO, venta=self.venta)
        self.client.force_login(self.admin)

    def test_venta_eliminar_y_restaurar_conserva_identidad_lineas_y_presupuesto(self):
        response = self.client.post(reverse('venta_eliminar', args=[self.venta.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Venta.objects.filter(pk=self.venta.pk).exists())
        self.assertEqual(Venta.all_objects.get(pk=self.venta.pk).lineas.count(), 1)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 10)
        self.presupuesto.refresh_from_db()
        self.assertEqual(self.presupuesto.venta_id, self.venta.pk)
        self.assertEqual(self.presupuesto.estado, Presupuesto.Estado.APROBADO)
        self.assertFalse(Evento.objects.filter(pk=self.evento.pk).exists())
        response = self.client.post(reverse('venta_restaurar', args=[self.venta.pk]))
        self.assertEqual(response.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 8)
        self.assertTrue(Venta.objects.filter(pk=self.venta.pk).exists())
        self.evento.refresh_from_db()
        self.assertTrue(self.evento.realizado)
        self.assertEqual(self.evento.descripcion, 'Texto original')
        self.assertTrue(Evento.objects.filter(pk=self.evento.pk).exists())

    def test_venta_pagada_conserva_y_restablece_movimiento_original(self):
        pago = MovimientoCaja.objects.create(fecha=date.today(), operacion='Cobro original', tipo='IN', monto=100, venta=self.venta, vendedor=self.vendedor)
        self.venta.estado = Venta.Estado.PAGADA
        self.venta.pago_movimiento = pago
        self.venta.neto_cobro = 100
        self.venta.save()
        enviar_venta_a_papelera(self.venta)
        self.assertFalse(MovimientoCaja.objects.filter(pk=pago.pk).exists())
        self.assertTrue(MovimientoCaja.all_objects.filter(pk=pago.pk).exists())
        cambiar_papelera_venta(self.venta.pk, restaurar=True)
        v = Venta.objects.get(pk=self.venta.pk)
        self.assertEqual(v.pago_movimiento_id, pago.pk)
        self.assertEqual(v.estado, Venta.Estado.PAGADA)
        self.assertEqual(v.neto_cobro, 100)
        self.assertEqual(MovimientoCaja.objects.filter(venta=v).count(), 1)

    def test_stock_insuficiente_no_restaurar_y_no_modificar_datos(self):
        enviar_venta_a_papelera(self.venta)
        Producto.objects.filter(pk=self.producto.pk).update(stock=1)
        with self.assertRaises(ValidationError):
            cambiar_papelera_venta(self.venta.pk, restaurar=True)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 1)
        self.assertFalse(Venta.objects.filter(pk=self.venta.pk).exists())
        self.assertFalse(Evento.objects.filter(pk=self.evento.pk).exists())

    def test_pago_transferencia_restaura_saldo_banco_sin_duplicar_movimiento(self):
        cuenta = CuentaBancaria.objects.create(banco='Banco', cuenta='Prueba', saldo_inicial=25)
        pago = MovimientoCaja.objects.create(fecha=date.today(), operacion='Cobro', tipo='IN', monto=100, venta=self.venta, medio_pago='TRF', banco='Banco', cuenta_bancaria=cuenta)
        self.venta.estado = Venta.Estado.PAGADA
        self.venta.pago_movimiento = pago
        self.venta.save()
        movimiento = MovimientoCuentaBancaria.objects.get(movimiento_caja=pago)
        self.assertEqual(CuentaBancaria.con_saldo_actual()[0].saldo_actual, 125)
        enviar_venta_a_papelera(self.venta)
        self.assertEqual(CuentaBancaria.con_saldo_actual()[0].saldo_actual, 25)
        self.assertTrue(MovimientoCuentaBancaria.all_objects.filter(pk=movimiento.pk).exists())
        cambiar_papelera_venta(self.venta.pk, restaurar=True)
        self.assertEqual(CuentaBancaria.con_saldo_actual()[0].saldo_actual, 125)
        self.assertEqual(MovimientoCuentaBancaria.objects.get(movimiento_caja=pago).pk, movimiento.pk)

    def test_acciones_repetidas_no_duplican_stock(self):
        enviar_venta_a_papelera(self.venta)
        enviar_venta_a_papelera(self.venta)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 10)
        cambiar_papelera_venta(self.venta.pk, restaurar=True)
        cambiar_papelera_venta(self.venta.pk, restaurar=True)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 8)

    def test_presupuesto_con_lineas_recuperable_y_post_obligatorio(self):
        p = Presupuesto.objects.create(vendedor=self.vendedor, subtotal_lineas=100)
        PresupuestoLinea.objects.create(presupuesto=p, producto=self.producto, cantidad=2, precio_unitario=50, subtotal=100)
        self.assertEqual(self.client.get(reverse('presupuesto_eliminar', args=[p.pk])).status_code, 405)
        self.client.post(reverse('presupuesto_eliminar', args=[p.pk]))
        self.assertFalse(Presupuesto.objects.filter(pk=p.pk).exists())
        self.assertEqual(Presupuesto.all_objects.get(pk=p.pk).lineas.count(), 1)
        self.assertEqual(self.client.get(reverse('presupuesto_restaurar', args=[p.pk])).status_code, 405)
        self.client.post(reverse('presupuesto_restaurar', args=[p.pk]))
        self.assertEqual(Presupuesto.objects.get(pk=p.pk).lineas.count(), 1)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 8)

    def test_vendedor_solo_recupera_sus_presupuestos_pendientes(self):
        propio = Presupuesto.all_objects.create(vendedor=self.vendedor, eliminado_en=timezone.now())
        ajeno = Presupuesto.all_objects.create(vendedor=self.otro, eliminado_en=timezone.now())
        self.client.force_login(self.user)
        self.client.post(reverse('vendedor_presupuesto_restaurar', args=[propio.pk]))
        self.assertTrue(Presupuesto.objects.filter(pk=propio.pk).exists())
        self.assertEqual(self.client.post(reverse('vendedor_presupuesto_restaurar', args=[ajeno.pk])).status_code, 404)
        self.assertFalse(Presupuesto.objects.filter(pk=ajeno.pk).exists())
        enviar_venta_a_papelera(self.venta)
        self.assertEqual(self.client.post(reverse('venta_restaurar', args=[self.venta.pk])).status_code, 302)
        self.assertFalse(Venta.objects.filter(pk=self.venta.pk).exists())

    def test_papeleras_muestran_registros_y_boton_restaurar(self):
        enviar_venta_a_papelera(self.venta)
        response = self.client.get(reverse('venta_papelera'))
        self.assertContains(response, 'Papelera de ventas')
        self.assertContains(response, reverse('venta_restaurar', args=[self.venta.pk]))
        self.client.post(reverse('presupuesto_eliminar', args=[self.presupuesto.pk]))
        response = self.client.get(reverse('presupuesto_papelera'))
        self.assertContains(response, reverse('presupuesto_restaurar', args=[self.presupuesto.pk]))

    def test_no_eliminar_despachados_ni_comisiones_liquidadas(self):
        self.venta.despacho_despachado = True
        self.venta.save()
        with self.assertRaises(ValidationError):
            enviar_venta_a_papelera(self.venta)
        self.venta.despacho_despachado = False
        self.venta.comision_liquidacion_pago = ComisionLiquidacionPago.objects.create(vendedor=self.vendedor, total=5)
        self.venta.save()
        with self.assertRaises(ValidationError):
            enviar_venta_a_papelera(self.venta)
        self.assertTrue(Venta.objects.filter(pk=self.venta.pk).exists())
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 8)

    def test_armado_conserva_vinculo_y_queda_para_revision(self):
        armado = ArmadoColectivoGuardado.objects.create(nombre='Prueba')
        armado.ventas.add(self.venta)
        enviar_venta_a_papelera(self.venta)
        armado.refresh_from_db()
        self.assertTrue(armado.requiere_revision)
        self.assertEqual(armado.ventas.count(), 0)
        cambiar_papelera_venta(self.venta.pk, restaurar=True)
        self.assertEqual(armado.ventas.count(), 1)
