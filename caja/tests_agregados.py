from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from .models import MovimientoCaja, ArqueoCaja
from .views import _saldos_libro_por_medio

class SaldosAgregadosTests(TestCase):
    def test_agregado_equivale_al_libro_con_fechas_cortes_y_medios(self):
        hoy = timezone.localdate()
        medios = [code for code, _ in MovimientoCaja.MedioPago.choices]
        def mov(fecha, tipo, monto, medio, **extra):
            return MovimientoCaja.objects.create(fecha=fecha, tipo=tipo, monto=monto, medio_pago=medio, operacion='Prueba', **extra)
        def verificar():
            qs=MovimientoCaja.objects.filter(fecha__lte=hoy)
            ultimo=qs.filter(es_arqueo=True).order_by('-fecha','-pk').first()
            esperado={m:Decimal('0') for m in medios}
            filas=list(qs.order_by('fecha','pk'))
            if ultimo:
                a=getattr(ultimo,'arqueo',None)
                if a:
                    for m,campo in zip(medios,['saldo_efectivo','saldo_transferencia','saldo_mercadopago','saldo_cheque','saldo_otro']):
                        esperado[m]=getattr(a,campo)
                else: esperado['OTH']=ultimo.saldo_arqueo
                filas=[m for m in filas if (m.fecha,m.pk)>(ultimo.fecha,ultimo.pk)]
            for m in filas:
                if not m.es_arqueo: esperado[m.medio_pago]+=m.delta
            actual=_saldos_libro_por_medio(hoy)
            for m in medios:self.assertEqual(actual[m],esperado[m],m)
            self.assertEqual(actual['total'],sum(esperado.values()))
        for i,m in enumerate(medios):
            mov(hoy,'IN',Decimal('100.13')+i,m)
            mov(hoy,'OUT',Decimal('17.51')+i,m)
            mov(hoy+timedelta(days=1),'IN',99999,m)
        mov(hoy,'ARQ',1000,medios[0])
        verificar()
        corte=mov(hoy,'ARQ',0,medios[0],es_arqueo=True,saldo_arqueo=150)
        ArqueoCaja.objects.create(fecha=hoy,movimiento=corte,saldo_efectivo=10,saldo_transferencia=20,saldo_mercadopago=30,saldo_cheque=40,saldo_otro=50)
        for m in medios:
            mov(hoy,'IN',Decimal('3.31'),m)
            mov(hoy-timedelta(days=1),'OUT',99999,m)
        verificar()
        mov(hoy,'ARQ',0,medios[0],es_arqueo=True,saldo_arqueo=77)
        mov(hoy,'OUT',Decimal('2.25'),medios[0])
        verificar()
