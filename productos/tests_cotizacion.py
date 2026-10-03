import json
from unittest.mock import patch
from django.test import TestCase,override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from decimal import Decimal
from .models import Producto,CotizacionAneleRevision,CotizacionAneleVinculo
from .cotizacion_views import product_data
from .cotizacion_match import compatible,labs_for

@override_settings(SIRONA_LOGOUT_ON_TAB_CLOSE=False)
class CotizacionTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('cotiadmin',password='test',is_staff=True)
        self.client.force_login(self.user)
        self.p=Producto.objects.create(descripcion='IBUPROFENO 800 MG X 10 COMP',laboratorio='SAVANT',tipo='MED',costo=100,stock=12,porcentaje_ganancia=30,en_lista_precios=False)
        self.q={'id':'q1','name':'IBUPROFENO 800 X 10 COMP','description':'','lab':'SAVANT','cost':'150.00','branch':'anele','quantity':'500','priceBasis':'Precio aprobado'}
        self.quote={'id':'quote','number':'COT-2026-1','date':'2026-10-03','state':'vigente','confirmed':True,'quotes':[self.q],'digest':'x'*64}
        self.rev=CotizacionAneleRevision.objects.create(usuario=self.user,datos={'quotation':self.quote,'products':[product_data(self.p)]})
        self.entry={'quoteId':'q1','productId':str(self.p.pk),'price':195,'margin':30,'confirmed':True}
    def post(self,entries=None,mode='update'):
        with patch('productos.cotizacion_views.quotation',return_value=self.quote):return self.client.post(reverse('productos_cotizacion_aplicar'),json.dumps({'revision':str(self.rev.pk),'mode':mode,'entries':entries if entries is not None else [self.entry]}),content_type='application/json')
    def test_update_preserves_stock_state_and_lists(self):
        r=self.post();self.assertEqual(r.status_code,200,r.content);self.p.refresh_from_db()
        self.assertEqual(self.p.costo,Decimal('150'));self.assertEqual(self.p.precio_venta,Decimal('195'));self.assertEqual(self.p.stock,12);self.assertFalse(self.p.en_lista_precios);self.assertFalse(self.p.precio_venta_editado);self.assertEqual(Producto.objects.count(),1)
        self.rev.refresh_from_db();self.assertIsNotNone(self.rev.aplicado_en);self.assertEqual(self.rev.resultado['changes'][0]['before']['cost'],100);self.assertEqual(CotizacionAneleVinculo.objects.count(),1)
    def test_idempotent_double_submit(self):
        self.assertEqual(self.post().status_code,200);self.assertEqual(self.post().status_code,200);self.assertEqual(CotizacionAneleRevision.objects.filter(aplicado_en__isnull=False).count(),1)
        self.assertEqual(self.post([{**self.entry,'price':200}]).status_code,409)
    def test_unconfirmed_row_rejected(self):self.assertEqual(self.post([{**self.entry,'confirmed':False}]).status_code,409)
    def test_update_never_creates(self):self.assertEqual(self.post([{**self.entry,'productId':'','name':'IBUPROFENO 800 MG X 10 COMP','lab':'SAVANT'}]).status_code,409);self.assertEqual(Producto.objects.count(),1)
    def test_duplicate_targets_rollback(self):
        q={**self.q,'id':'q2'};self.quote['quotes'].append(q);self.rev.datos['quotation']=self.quote;self.rev.save()
        self.assertEqual(self.post([self.entry,{**self.entry,'quoteId':'q2'}]).status_code,409);self.p.refresh_from_db();self.assertEqual(self.p.costo,100)
    def test_changed_product_rejected(self):
        self.p.stock=13;self.p.save();self.assertEqual(self.post().status_code,409)
    def test_changed_quote_rejected(self):
        self.quote['digest']='changed';self.assertEqual(self.post().status_code,409)
    def test_source_dose_mismatch_rejected(self):
        self.quote['quotes'][0]['name']='IBUPROFENO 400 X 10 COMP';self.rev.datos['quotation']=self.quote;self.rev.save();self.assertEqual(self.post().status_code,409)
    def test_price_edit_updates_margin(self):
        r=self.post([{**self.entry,'price':210,'margin':30}]);self.assertEqual(r.status_code,200,r.content);self.p.refresh_from_db();self.assertEqual(self.p.porcentaje_ganancia,40);self.assertTrue(self.p.precio_venta_editado)
    def test_negative_or_nonfinite_price_rejected(self):
        for price in [-1,'NaN','Infinity']:self.assertEqual(self.post([{**self.entry,'price':price}]).status_code,409)
    def test_add_is_explicit_and_starts_without_stock(self):
        self.quote['quotes'][0]['name']='PARACETAMOL 500';self.rev.datos['quotation']=self.quote;self.rev.save()
        r=self.post([{**self.entry,'productId':'','name':'PARACETAMOL 500 MG X 10 COMP','lab':'SAVANT','priceList':True}],mode='add');self.assertEqual(r.status_code,200,r.content)
        new=Producto.objects.exclude(pk=self.p.pk).get();self.assertEqual(new.stock,0);self.assertTrue(new.en_lista_precios)
    def test_add_requires_approved_quote(self):
        self.quote['confirmed']=False;self.rev.datos['quotation']=self.quote;self.rev.save();self.assertEqual(self.post(mode='add').status_code,409)
    def test_other_user_cannot_apply_revision(self):
        other=get_user_model().objects.create_user('other',password='test',is_staff=True);self.client.force_login(other);self.assertEqual(self.post().status_code,404)
    def test_view_and_costs_render(self):
        with patch('productos.cotizacion_views.quotation',return_value=self.quote):r=self.client.get(reverse('productos_cotizacion_anele'))
        self.assertEqual(r.status_code,200,r.content);self.assertContains(r,'sync-data');self.assertContains(r,'cotizacion-anele.js');self.assertContains(self.client.get(reverse('productos_costos')),'Actualizar precios')
    def test_match_variants_dose_count_lab_and_form(self):
        p=product_data(self.p);labs=labs_for([p]);self.assertTrue(compatible(self.q,p,labs))
        for row in [{**self.q,'name':'IBUPROFENO 400 X 10 COMP'},{**self.q,'name':'IBUPROFENO 800 X 20 COMP'},{**self.q,'lab':'VALMAX'},{**self.q,'name':'IBUPROFENO 800 X 10 CAPSULAS'}]:self.assertFalse(compatible(row,p,labs))
