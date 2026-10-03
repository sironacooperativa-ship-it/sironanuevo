import hashlib,hmac,json,os,time,uuid
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from urllib.request import Request,urlopen
from urllib.error import URLError,HTTPError
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction,connection
from django.http import JsonResponse
from django.shortcuts import render,get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from core import app_bridge
from core.money_decimal import redondear_precio_mostrador_ars
from .models import Producto,CotizacionAneleRevision,CotizacionAneleVinculo
from .cotizacion_match import compatible,labs_for,source_key,normal,profile

def access(request):
    if not request.user.is_active or getattr(getattr(request.user,'perfil_acceso',None),'solo_vendedor',False) or request.session.get('modo_vendedor'):
        raise PermissionDenied('No tenés acceso a costos.')

def quotation(user,quote_id=None):
    if not app_bridge.enabled(user):raise ValueError('Tu usuario no tiene habilitada la conexión con Anele.')
    data={'sironaId':user.pk}
    if quote_id:data['quoteId']=quote_id
    body=json.dumps(data,separators=(',',':')).encode();stamp=str(int(time.time()))
    signature=hmac.new(os.environ['APP_BRIDGE_SECRET'].encode(),stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
    request=Request(app_bridge.ANELE+'/api/sirona-prices',data=body,headers={'Content-Type':'application/json','X-Bridge-Time':stamp,'X-Bridge-Signature':signature},method='POST')
    try:
        with urlopen(request,timeout=20) as response:
            payload=response.read(2000001)
        if len(payload)>2000000:raise ValueError('La cotización excede el tamaño permitido.')
        q=json.loads(payload)
        if not isinstance(q.get('quotes'),list) or len(q['quotes'])>2000 or not q.get('digest'):raise ValueError('Cotización inválida.')
        return q
    except HTTPError as e:
        raise ValueError('Anele no pudo entregar la cotización. Verificá tu conexión y acceso a Cotizaciones.') from e
    except (URLError,TimeoutError,json.JSONDecodeError) as e:
        raise ValueError('No se pudo conectar con Anele. Intentá nuevamente.') from e

def product_data(p):
    return {'id':str(p.pk),'name':p.descripcion,'lab':p.laboratorio,'code':p.codigo,'cost':float(p.costo),'price':float(p.precio_venta),'margin':float(p.porcentaje_ganancia),'stock':p.stock,'enabled':p.habilitado,'priceList':p.en_lista_precios,'version':p.actualizado_en.isoformat()}

@login_required
def costs(request):
    access(request)
    return render(request,'productos/costos.html',{'productos':Producto.objects.order_by('descripcion','codigo'),'anele_enabled':app_bridge.enabled(request.user)})

@login_required
def metadata(request):
    access(request)
    key=f'anele-price-metadata:{request.user.pk}'
    q=cache.get(key)
    try:
        if not q:q=quotation(request.user);cache.set(key,q,30)
        return JsonResponse({'date':q['date'],'number':q['number'],'state':q['state']})
    except ValueError as e:return JsonResponse({'error':str(e)},status=503)

@login_required
def review(request):
    access(request)
    try:
        q=quotation(request.user,request.GET.get('quote') or None)
        products=[product_data(p) for p in Producto.objects.order_by('descripcion','pk')]
        rev=CotizacionAneleRevision.objects.create(usuario=request.user,datos={'quotation':q,'products':products})
        links=dict(CotizacionAneleVinculo.objects.values_list('clave','producto_id'))
        data={'snapshot':q['date'],'source':q['number'],'quoteState':f'{q["number"]}: '+('Cotización aprobada' if q['confirmed'] else 'Cotización en proceso'),'products':products,'quotes':[{**r,'cost':float(r['cost']) if r['cost'] else None} for r in q['quotes']],'links':{r['id']:str(links[source_key(r)]) for r in q['quotes'] if source_key(r) in links},'revision':str(rev.pk),'applyUrl':reverse('productos_cotizacion_aplicar'),'confirmed':q['confirmed'],'mode':'add' if request.GET.get('mode')=='add' and q['confirmed'] else 'update'}
        return render(request,'productos/cotizacion_anele.html',{'sync_data':data})
    except ValueError as e:
        return render(request,'productos/cotizacion_anele.html',{'sync_error':str(e)},status=503)

def number(value,label,maximum='9999999999.99',minimum='0'):
    if isinstance(value,bool):raise ValueError(f'{label} inválido.')
    try:n=Decimal(str(value))
    except InvalidOperation:raise ValueError(f'{label} inválido.')
    if not n.is_finite() or n<Decimal(minimum) or n>Decimal(maximum):raise ValueError(f'{label} inválido.')
    return n.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)

@login_required
@require_POST
def apply(request):
    access(request)
    try:
        if len(request.body)>400000:raise ValueError('Solicitud demasiado grande.')
        body=json.loads(request.body)
        if not isinstance(body,dict):raise ValueError('Solicitud inválida.')
        entries=body.get('entries');mode=body.get('mode')
        if mode not in ('update','add') or not isinstance(entries,list) or not 1<=len(entries)<=2000 or any(not isinstance(e,dict) for e in entries):raise ValueError('Seleccioná productos válidos.')
        revision_id=uuid.UUID(str(body.get('revision')))
        rev=CotizacionAneleRevision.objects.filter(pk=revision_id,usuario=request.user).first()
        if rev is None:return JsonResponse({'error':'Revisión inexistente.'},status=404)
        fingerprint=hashlib.sha256(json.dumps({'mode':mode,'entries':entries},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if rev.aplicado_en:
            if rev.resultado.get('fingerprint')!=fingerprint:raise ValueError('Esta revisión ya fue aplicada. Abrí una nueva revisión.')
            return JsonResponse(rev.resultado)
        if timezone.now()-rev.creado_en>timezone.timedelta(hours=2):raise ValueError('La revisión venció. Volvé a abrir la cotización.')
        old=rev.datos['quotation'];fresh=quotation(request.user,old['id'])
        if fresh['digest']!=old['digest']:raise ValueError('La cotización cambió en Anele. Volvé a revisarla antes de confirmar.')
        if mode=='add' and not old['confirmed']:raise ValueError('Primero aprobá la cotización en Anele para agregar productos.')
        quotes={q['id']:q for q in old['quotes']};snapshots={p['id']:p for p in rev.datos['products']};labs=labs_for(rev.datos['products'])
        changes=[];used=set();quote_used=set()
        with transaction.atomic():
            if connection.vendor=='postgresql':
                with connection.cursor() as cursor:cursor.execute('SELECT pg_advisory_xact_lock(721883008)')
            rev=CotizacionAneleRevision.objects.select_for_update().get(pk=rev.pk)
            if rev.aplicado_en:
                if rev.resultado.get('fingerprint')!=fingerprint:raise ValueError('Esta revisión ya fue aplicada.')
                return JsonResponse(rev.resultado)
            for e in entries:
                q=quotes.get(e.get('quoteId'))
                if not q or e.get('confirmed') is not True or q['id'] in quote_used:raise ValueError('Confirmá cada correspondencia una sola vez.')
                quote_used.add(q['id']);cost=number(q['cost'],'Costo',minimum='.01');price=number(e.get('price'),'Precio de venta')
                product_id=str(e.get('productId') or '')
                if product_id:
                    previous=snapshots.get(product_id)
                    if not previous or product_id in used:raise ValueError('Producto inexistente o seleccionado dos veces.')
                    used.add(product_id);p=Producto.objects.select_for_update().filter(pk=product_id).first()
                    current=product_data(p) if p else None
                    if not current or any(current[k]!=previous[k] for k in ('version','name','lab','cost','price','margin','stock','enabled','priceList')):raise ValueError('Un producto cambió en Sirona durante la revisión. Volvé a revisar los precios.')
                    if not compatible(q,product_data(p),labs):raise ValueError('La dosis, presentación o laboratorio no coinciden.')
                    before=product_data(p);created=False
                else:
                    if mode!='add':raise ValueError('Actualizar costos no agrega productos.')
                    name=str(e.get('name') or '').strip();lab=str(e.get('lab') or '').strip()
                    if not 1<=len(name)<=255 or not 2<=len(lab)<=120:raise ValueError('Completá descripción y laboratorio para el alta.')
                    candidate={'name':name,'lab':lab};parsed=profile(candidate,labs)
                    if not parsed['dose'] or parsed['pack'] is None or not compatible(q,candidate,labs):raise ValueError('Completá dosis y envase, conservando el producto de la cotización.')
                    if CotizacionAneleVinculo.objects.filter(clave=source_key(q)).exists() or any(normal(p.descripcion)==normal(name) and normal(p.laboratorio)==normal(lab) for p in Producto.objects.all()):raise ValueError('El producto ya está cargado o vinculado. Elegilo para actualizarlo.')
                    p=Producto(descripcion=name,laboratorio=lab,tipo=Producto.Tipo.MEDICAMENTOS,stock=0,en_lista_precios=e.get('priceList') is True);before=None;created=True
                pct=number(e.get('margin',30),'Margen','9999.99','-100')
                automatic=redondear_precio_mostrador_ars(cost*(1+pct/100))==price
                p.costo=cost;p.porcentaje_ganancia=pct if automatic else ((price/cost-1)*100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                p.precio_venta=price;p.precio_venta_editado=not automatic
                # Cost updates preserve enabled state, stock and price-list membership.
                if not created:
                    Producto.objects.filter(pk=p.pk).update(costo=p.costo,porcentaje_ganancia=p.porcentaje_ganancia,precio_venta=p.precio_venta,precio_venta_editado=p.precio_venta_editado,precio_actualizado_en=timezone.now(),actualizado_en=timezone.now())
                    p.refresh_from_db()
                else:p.save()
                CotizacionAneleVinculo.objects.update_or_create(clave=source_key(q),defaults={'producto':p})
                changes.append({'quote':q['name'],'product':p.descripcion,'id':str(p.pk),'new':created,'before':before,'after':product_data(p)})
            rev.aplicado_en=timezone.now();rev.resultado={'fingerprint':fingerprint,'changes':changes,'products':[product_data(p) for p in Producto.objects.order_by('descripcion','pk')],'revision':str(rev.pk)};rev.save(update_fields=['aplicado_en','resultado'])
        cache.delete(f'anele-price-metadata:{request.user.pk}')
        return JsonResponse(rev.resultado)
    except (ValueError,TypeError,KeyError,InvalidOperation) as e:return JsonResponse({'error':str(e) or 'Revisá los datos.'},status=409)
