import hashlib, hmac, json, os, time, uuid, re
from datetime import date
from decimal import Decimal
from django.db import transaction, connection
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from compras.models import Compra
from personas.models import Proveedor
from calendario.models import Evento
from core.app_bridge import accounts

@csrf_exempt
@require_POST
def receive(request):
    try:
        secret=os.environ.get('APP_BRIDGE_SECRET','')
        stamp=request.headers.get('X-Bridge-Time','');signature=request.headers.get('X-Bridge-Signature','')
        if not secret or not re.fullmatch(r'\d{10}',stamp) or abs(time.time()-int(stamp))>60 or len(request.body)>12000:
            return JsonResponse({'error':'Acceso no permitido.'},status=403)
        expected=hmac.new(secret.encode(),stamp.encode()+b'.'+request.body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected):return JsonResponse({'error':'Acceso no permitido.'},status=403)
        data=json.loads(request.body)
        source=uuid.UUID(data['id']);pharmacy=data['pharmacy'];name=data['pharmacyName']
        if pharmacy not in ('anele','farmanele','padua','pontevedra') or not isinstance(name,str) or not 1<=len(name)<=100:raise ValueError()
        number=data['number'];amount=data['amount'];invoice_date=date.fromisoformat(data['date']);due=date.fromisoformat(data['dueDate'])
        if not isinstance(number,str) or not 1<=len(number)<=60 or not re.fullmatch(r'\d{1,10}(\.\d{1,2})?',amount) or Decimal(amount)<=0:raise ValueError()
        if data.get('payer')!='sirona':raise ValueError()
        with transaction.atomic():
            if connection.vendor=='postgresql':
                with connection.cursor() as cursor:cursor.execute('SELECT pg_advisory_xact_lock(721883007)')
            prior=Compra.objects.filter(origen_anele_id=source).first()
            if prior:
                if prior.origen_anele_datos!=data:return JsonResponse({'error':'La factura ya existe con otros datos.'},status=409)
                return JsonResponse({'id':prior.pk,'duplicate':True})
            names=[name.casefold(),('farmacia '+name).casefold()]
            matches=[p for p in Proveedor.objects.filter(habilitado=True) if ' '.join((p.apellido+' '+p.nombre).split()).casefold() in names or ' '.join((p.nombre+' '+p.apellido).split()).casefold() in names]
            if len(matches)>1:return JsonResponse({'error':'Hay más de un proveedor para esa farmacia. Revisá los proveedores en Sirona.'},status=409)
            previous=Compra.objects.filter(origen_anele_datos__pharmacy=pharmacy).select_related('proveedor').first()
            provider=previous.proveedor if previous else (matches[0] if matches else Proveedor.objects.create(nombre=name,apellido='',codigo=''))
            if not provider.habilitado:return JsonResponse({'error':'El proveedor de esa farmacia está deshabilitado en Sirona.'},status=409)
            linked=next((a['sironaId'] for a in accounts() if a['aneleId']==data['actor']),None)
            actor=get_user_model().objects.filter(pk=linked,is_active=True).first() if linked else None
            purchase=Compra.objects.create(modo=Compra.Modo.FACTURA,proveedor=provider,producto=None,fecha_compra=invoice_date,fecha_vencimiento_pedido=due,cantidad=0,costo_unitario=Decimal('0'),monto=Decimal(amount),movimiento_caja=None,creado_por=actor,actualizado_por=actor,origen_anele_id=source,origen_anele_datos=data)
            Evento.objects.create(fecha=due,titulo=f'Pagar factura — {name}'[:255],tipo=Evento.Tipo.COMPRA,descripcion=f'Generada desde Grupo Anele · Factura {number} · {name} · Importe {amount} · Compra #{purchase.pk}. Cargada por {data["actorName"]}.')
            return JsonResponse({'id':purchase.pk,'duplicate':False},status=201)
    except (ValueError,TypeError,KeyError):return JsonResponse({'error':'Revisá los datos de la factura.'},status=400)
