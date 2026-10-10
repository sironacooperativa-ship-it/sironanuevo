from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.test.utils import CaptureQueriesContext
from django.db import connection
from .models import Producto, ListaPrecios
from .stock_cero import consumir_prompt_stock_cero


class RendimientoTests(TestCase):
    def test_paginacion_conserva_productos_y_exportacion_completa(self):
        import io
        from openpyxl import load_workbook
        from .views import _retorno_params_desde_post
        user=get_user_model().objects.create_user('paginacion',is_staff=True)
        self.client.force_login(user)
        for i in range(61):
            Producto.objects.create(descripcion=f'Producto pagina {i}',stock=3,en_lista_precios=True)
        url=reverse('productos_list')
        first=self.client.get(url,{'lista':'all'})
        second=self.client.get(url,{'lista':'all','page':'2'})
        ids=[p.pk for p in first.context['productos']]+[p.pk for p in second.context['productos']]
        self.assertEqual(len(first.context['productos']),50)
        self.assertEqual(len(second.context['productos']),11)
        self.assertEqual(set(ids),set(Producto.objects.values_list('pk',flat=True)))
        for value,expected in [('25',25),('100',61),('999999',50),('abc',50)]:
            response=self.client.get(url,{'lista':'all','page_size':value})
            self.assertEqual(len(response.context['productos']),expected)
        export=self.client.get(url,{'lista':'all','page_size':'25','page':'2','export':'xlsx'})
        workbook=load_workbook(io.BytesIO(export.content),read_only=True)
        self.assertEqual(sum(1 for _ in workbook.active.rows),62)
        request=RequestFactory().post('/',{'retorno_query':'lista=all&page=2&page_size=25'})
        self.assertEqual(_retorno_params_desde_post(request)['page_size'],'25')

    def test_sesion_sin_prompt_no_se_modifica(self):
        request=RequestFactory().get('/')
        request.session=SessionStore()
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(consumir_prompt_stock_cero(request),[])
        self.assertFalse(request.session.modified)
        self.assertEqual(len(queries),0)

    def test_prompt_se_consume_solo_en_get(self):
        p=Producto.objects.create(descripcion='Prueba cero',stock=0)
        request=RequestFactory().post('/')
        request.session=SessionStore();request.session['stock_cero_prompt']=[p.pk]
        self.assertEqual(consumir_prompt_stock_cero(request)[0]['id'],p.pk)
        self.assertIn('stock_cero_prompt',request.session)
        request.method='GET'
        self.assertEqual(consumir_prompt_stock_cero(request)[0]['id'],p.pk)
        self.assertNotIn('stock_cero_prompt',request.session)
        self.assertEqual(consumir_prompt_stock_cero(request),[])

    def test_productos_sin_redireccion_conserva_lista_y_exportacion(self):
        user=get_user_model().objects.create_user('rendimiento',is_staff=True)
        self.client.force_login(user)
        farmacia=ListaPrecios.objects.filter(es_farmacia=True).order_by('id').first()
        if farmacia is None:
            farmacia=ListaPrecios.objects.create(nombre='Farmacia',es_farmacia=True)
        p=Producto.objects.create(descripcion='Producto prueba',stock=3,en_lista_precios=True)
        response=self.client.get(reverse('productos_list'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['lista_modo'],'farmacia')
        self.assertEqual(response.context['lista'],str(farmacia.pk))
        response=self.client.get(reverse('productos_list'),{'lista':'all'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['lista_modo'],'all')
        response=self.client.get(reverse('productos_list'),{'export':'xlsx'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'PK'))

    def test_html_comprimido_conserva_contenido(self):
        import gzip
        user=get_user_model().objects.create_user('rendimiento_gzip',is_staff=True)
        self.client.force_login(user)
        response=self.client.get(reverse('productos_list'),{'lista':'all'},HTTP_ACCEPT_ENCODING='gzip')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Encoding'],'gzip')
        self.assertIn(b'Productos',gzip.decompress(response.content))
