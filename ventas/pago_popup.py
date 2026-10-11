from pathlib import PurePath

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET
from io import BytesIO

from .forms import VentaPagoForm
from .models import Venta, PagoPedidoDetalle, PagoPedidoComprobante
from .servicios import venta_registrar_cobro_caja


def registrar(request, pk=None):
    modal = request.GET.get("modal") == "1" or request.POST.get("modal") == "1"
    raw = [pk] if pk is not None else (request.POST if request.method == "POST" else request.GET).getlist("venta_id")
    ids = sorted({int(v) for v in raw if str(v).isdigit()})
    if not ids:
        raise Http404("Seleccioná al menos un pedido.")
    ventas = list(Venta.objects.filter(pk__in=ids).select_related("vendedor", "pago_movimiento").order_by("pk"))
    if len(ventas) != len(ids) or any(v.estado not in (Venta.Estado.PENDIENTE, Venta.Estado.PAGADA) or v.eliminado_en for v in ventas):
        raise Http404("Pedido no disponible.")
    pagado = all(v.estado == Venta.Estado.PAGADA for v in ventas)
    form = VentaPagoForm(request.POST or None, request.FILES or None, initial={"fecha": timezone.localdate(), "medio_pago": "CASH"})
    status = 200
    if request.method == "POST" and not pagado:
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Recheck after locking: retries and double clicks cannot create two cobros.
                    ventas = list(Venta.objects.filter(pk__in=ids).select_for_update().order_by("pk"))
                    if all(v.estado == Venta.Estado.PAGADA for v in ventas):
                        pagado = True
                    else:
                        if any(v.estado != Venta.Estado.PENDIENTE or v.eliminado_en for v in ventas):
                            raise ValidationError("La selección cambió. Cerrá el popup y revisá los pedidos.")
                        archivo = form.cleaned_data.get("comprobante")
                        adjunto = None
                        if archivo:
                            adjunto = PagoPedidoComprobante.objects.create(nombre=PurePath(archivo.name.replace('\\', '/')).name[:255], tipo=archivo.tipo_validado, contenido=archivo.read())
                        for venta in ventas:
                            movimiento = VentaPagoForm(request.POST).save(commit=False)
                            venta_registrar_cobro_caja(venta=venta, mov=movimiento, user=request.user)
                            PagoPedidoDetalle.objects.create(movimiento=movimiento, detalle=form.cleaned_data["detalle"], comprobante=adjunto)
                        pagado = True
            except ValidationError as error:
                form.add_error(None, error.messages)
                status = 422
        else:
            status = 422
    if pagado:
        ventas = list(Venta.objects.filter(pk__in=ids).select_related("vendedor", "pago_movimiento", "pago_movimiento__detalle_pago_pedido__comprobante").defer("pago_movimiento__detalle_pago_pedido__comprobante__contenido").order_by("pk"))
    return render(request, "ventas/pago_popup.html" if modal else "ventas/pago_pagina.html", {
        "ventas": ventas, "form": form, "pagado": pagado, "modal": modal,
        "total": sum((v.monto_ingreso_caja for v in ventas)),
    }, status=status)


@login_required
@require_GET
def comprobante(request, pk):
    # The receipt belongs to the cash movement; no anonymous public upload URLs.
    adjunto = get_object_or_404(PagoPedidoComprobante, pk=pk)
    return FileResponse(BytesIO(bytes(adjunto.contenido)), as_attachment=True, filename=adjunto.nombre, content_type=adjunto.tipo)
