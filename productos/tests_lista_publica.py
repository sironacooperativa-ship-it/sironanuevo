from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from .models import ListaPrecios, Producto

class ListaPublicaTests(TestCase):
    def test_publica_actualizada_sin_datos_privados_ni_escritura(self):
        ListaPrecios.objects.create(nombre='Farmacia', es_farmacia=True)
        p = Producto.objects.create(descripcion='<Producto>', precio_venta=Decimal('1234'), costo=Decimal('987'), habilitado=True, en_lista_precios=True)
        Producto.objects.create(descripcion='OCULTO', habilitado=False, en_lista_precios=True)
        Producto.objects.create(descripcion='FUERA DE LISTA', habilitado=True, en_lista_precios=False)
        url = reverse('lista_precios_public_farmacia')
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '&lt;Producto&gt;')
        self.assertNotContains(r, 'OCULTO')
        self.assertNotContains(r, 'FUERA DE LISTA')
        self.assertNotContains(r, '987')
        self.assertIn('no-store', r['Cache-Control'])
        self.assertEqual(self.client.post(url, {}).status_code, 405)
        Producto.objects.filter(pk=p.pk).update(precio_venta=Decimal('5678'))
        from core.money_decimal import format_monto_ars
        self.assertEqual(self.client.get(url).context['filas'][0]['precio'], format_monto_ars(Decimal('5678')))
        pdf=self.client.get(url, {'formato':'pdf'})
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(b''.join(pdf.streaming_content).startswith(b'%PDF'))
