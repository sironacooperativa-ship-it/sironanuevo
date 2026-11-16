from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from personas.models import Vendedor
from .models import Venta, ArmadoColectivoGuardado


class DestinatarioDespachoTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('despachos', is_staff=True)
        self.client.force_login(self.user)
        self.vendedor = Vendedor.objects.create(nombre='Ana', apellido='Pérez')
        self.venta = Venta.objects.create(vendedor=self.vendedor, fecha_vencimiento_pago=date.today())
        self.url = reverse('venta_actualizar_despacho', args=[self.venta.pk])

    def test_elegir_vendedor_y_mostrar_historial(self):
        self.assertContains(self.client.get(self.url), 'Otro')
        response = self.client.post(self.url, {'estado': 'despachado', 'destinatario': self.vendedor.pk}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.despacho_destinatario, 'Pérez, Ana')
        self.assertTrue(self.venta.despacho_armado)
        self.assertContains(self.client.get(reverse('ventas_historial')), 'Pérez, Ana')

    def test_otro_requiere_nombre_y_no_modifica_estado_si_es_invalido(self):
        for datos in ({}, {'destinatario': 'otro', 'otro': '  '}, {'destinatario': '999999'}, {'destinatario': 'otro', 'otro': 'x' * 221}):
            response = self.client.post(self.url, {'estado': 'despachado', **datos})
            self.assertEqual(response.status_code, 400)
            self.venta.refresh_from_db()
            self.assertFalse(self.venta.despacho_despachado)
        response = self.client.post(self.url, {'estado': 'despachado', 'destinatario': 'otro', 'otro': '  María  '})
        self.assertEqual(response.status_code, 302)
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.despacho_destinatario, 'María')

    def test_completar_antiguo_conserva_fecha_y_revertir_limpia_destinatario(self):
        self.venta.aplicar_estado_despacho(armado=True, despachado=True)
        self.venta.save()
        fecha = self.venta.despacho_despachado_en
        response = self.client.get(reverse('ventas_historial'))
        self.assertContains(response, 'No especificado')
        self.assertContains(response, 'data-destinatario-url')
        self.client.post(self.url, {'estado': 'despachado', 'destinatario': 'otro', 'otro': 'María'})
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.despacho_despachado_en, fecha)
        self.client.post(self.url, {'estado': 'armado'})
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.despacho_destinatario, '')
        self.assertIsNone(self.venta.despacho_despachado_en)
        self.assertEqual(self.venta.despacho_resumen, 'Sin despachar')

    def test_colectivo_valida_antes_de_actualizar_y_conserva_despachados(self):
        armado = ArmadoColectivoGuardado.objects.create()
        armado.ventas.add(self.venta)
        url = reverse('armado_colectivo_marcar_despachados', args=[armado.pk])
        self.assertContains(self.client.get(url), 'Otro')
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        self.venta.refresh_from_db()
        self.assertFalse(self.venta.despacho_despachado)
        response = self.client.post(url, {'destinatario': 'otro', 'otro': 'Carlos'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.despacho_destinatario, 'Carlos')
        self.client.post(url, {'destinatario': 'otro', 'otro': 'María'})
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.despacho_destinatario, 'Carlos')

    def test_requiere_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, {'estado': 'despachado'}).status_code, 302)
