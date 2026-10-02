from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from compras.models import Compra
from personas.models import Proveedor
from .models import ArqueoCaja, MovimientoCaja
from .saldos import actualizar_saldo_caja
from .views import _saldo_caja_al, _saldos_libro_por_medio, _resumen_caja_dashboard


class ActualizarSaldoTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user('saldo_admin', is_staff=True)
        self.client.force_login(self.usuario)
        self.hoy = timezone.localdate()
        self.anterior = MovimientoCaja.objects.create(fecha=self.hoy, operacion='Ingreso anterior', tipo='IN', monto=800)

    def actualizar(self, saldo='5.000,00'):
        return self.client.post(reverse('caja_actualizar_saldo'), {'saldo_actual': saldo, 'observaciones': 'Inicio de carga'})

    def test_formulario_y_menu_completos_no_modifican_saldo_al_abrir(self):
        response = self.client.get(reverse('caja_actualizar_saldo'))
        self.assertContains(response, 'Saldo real disponible en caja')
        self.assertContains(response, 'Guardar saldo actual')
        self.assertContains(response, reverse('caja_actualizar_saldo'), count=2)
        self.assertEqual(ArqueoCaja.objects.count(), 0)
        self.assertEqual(_saldo_caja_al(self.hoy), 800)

    def test_saldo_reemplaza_acumulado_y_conserva_historial(self):
        response = self.actualizar()
        self.assertRedirects(response, reverse('caja_list'))
        self.assertEqual(_saldo_caja_al(self.hoy), 5000)
        self.assertTrue(MovimientoCaja.objects.filter(pk=self.anterior.pk).exists())
        corte = MovimientoCaja.objects.get(es_arqueo=True)
        self.assertEqual(corte.fecha, self.hoy)
        self.assertEqual(corte.creado_por, self.usuario)
        self.assertEqual(corte.delta, 0)
        self.assertEqual(corte.arqueo.observaciones, 'Inicio de carga')
        self.assertEqual(_saldos_libro_por_medio(self.hoy)['CASH'], 5000)
        self.assertEqual(_resumen_caja_dashboard(self.hoy)['ingresos_mes'], 800)

    def test_ingreso_gasto_y_compra_desde_el_nuevo_saldo(self):
        self.actualizar()
        response = self.client.post(reverse('caja_create'), {
            'fecha': self.hoy.isoformat(), 'operacion': 'Gasto nuevo', 'tipo': 'OUT', 'monto': '300', 'medio_pago': 'CASH',
        })
        self.assertEqual(response.status_code, 302)
        MovimientoCaja.objects.create(fecha=self.hoy, operacion='Ingreso nuevo', tipo='IN', monto=100)
        proveedor = Proveedor.objects.create(nombre='Proveedor', apellido='Prueba')
        response = self.client.post(reverse('compra_registrar'), {
            'nombre_producto': 'Compra prueba', 'tipo_producto': 'OT', 'proveedor': proveedor.pk,
            'fecha_compra': self.hoy.isoformat(), 'cantidad': 2, 'costo_unitario': '200', 'monto': '400', 'medio_pago': 'CASH',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Compra.objects.count(), 1)
        self.assertEqual(_saldo_caja_al(self.hoy), 4400)
        self.assertEqual(_saldos_libro_por_medio(self.hoy)['total'], 4400)
        self.assertContains(self.client.get(reverse('caja_list')), '$ 4.400,00')

    def test_cero_es_valido(self):
        self.actualizar('0')
        self.assertEqual(_saldo_caja_al(self.hoy), 0)
        self.assertEqual(ArqueoCaja.objects.count(), 1)

    def test_invalidos_no_crean_corte(self):
        for monto in ['', '-1', 'NaN', 'Infinity', 'texto', '1000000000000', '1,234']:
            with self.subTest(monto=monto):
                self.assertEqual(self.actualizar(monto).status_code, 200)
                self.assertEqual(ArqueoCaja.objects.count(), 0)
                self.assertEqual(_saldo_caja_al(self.hoy), 800)

    def test_segunda_actualizacion_usa_ultimo_saldo_y_fechas_anteriores_no_afectan(self):
        self.actualizar()
        MovimientoCaja.objects.create(fecha=self.hoy, operacion='Egreso', tipo='OUT', monto=200)
        self.actualizar('2.000,00')
        MovimientoCaja.objects.create(fecha=self.hoy - timedelta(days=1), operacion='Gasto viejo cargado después', tipo='OUT', monto=700)
        MovimientoCaja.objects.create(fecha=self.hoy, operacion='Egreso posterior', tipo='OUT', monto=50)
        self.assertEqual(_saldo_caja_al(self.hoy), 1950)
        self.assertEqual(ArqueoCaja.objects.count(), 2)
        self.assertEqual(_saldo_caja_al(self.hoy - timedelta(days=1)), -700)

    def test_requiere_login(self):
        self.client.logout()
        self.assertEqual(self.actualizar().status_code, 302)
        self.assertFalse(MovimientoCaja.objects.filter(es_arqueo=True).exists())

    def test_saldo_real_se_conserva_al_filtrar_egresos(self):
        self.actualizar()
        MovimientoCaja.objects.create(fecha=self.hoy, operacion='Gasto uno', tipo='OUT', monto=300)
        MovimientoCaja.objects.create(fecha=self.hoy, operacion='Ingreso', tipo='IN', monto=100)
        MovimientoCaja.objects.create(fecha=self.hoy, operacion='Gasto dos', tipo='OUT', monto=50)
        response = self.client.get(reverse('caja_list'), {'tipo': 'OUT'})
        self.assertEqual([r['saldo'] for r in response.context['rows']], [Decimal('4750'), Decimal('4700')])
