from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from productos.models import Producto
from personas.models import Proveedor

class FiltrosComprasTests(TestCase):
    def test_filtros_preservan_seleccion_y_escapan_texto(self):
        self.client.force_login(get_user_model().objects.create_user('compras_filtros',is_staff=True))
        p=Producto.objects.create(descripcion='<Producto> & especial',tipo='MED')
        proveedor=Proveedor.objects.create(nombre='<Proveedor>',apellido='Apellido')
        r=self.client.get(reverse('compra_historial'),{'producto':p.pk,'proveedor':proveedor.pk})
        self.assertEqual(r.status_code,200)
        self.assertContains(r,f'<option value="{p.pk}" selected>')
        self.assertContains(r,'&lt;Producto&gt; &amp; especial')
        self.assertContains(r,'&lt;Proveedor&gt;')
        self.assertContains(r,f'<option value="{proveedor.pk}" selected>')
