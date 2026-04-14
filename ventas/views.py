from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.export_utils import parse_export, pdf_response, xlsx_response
from core.fecha_filtros import parse_fecha_dashboard, rango_periodo

from calendario.models import Evento
from caja.models import MovimientoCaja
from personas.models import Comprador, Vendedor
from productos.models import Producto

from .forms import VentaPagoForm
from .models import Venta, VentaLinea
from .servicios import crear_venta_confirmada


def _parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _productos_payload():
    qs = Producto.objects.filter(habilitado=True).order_by("codigo")
    return [
        {
            "id": p.id,
            "codigo": p.codigo,
            "descripcion": p.descripcion,
            "precio": str(p.precio_venta),
            "stock": p.stock,
        }
        for p in qs
    ]


@login_required
@require_http_methods(["GET", "POST"])
def venta_nueva(request):
    vendedores = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    compradores = Comprador.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    productos_catalogo = _productos_payload()

    if request.method == "POST":
        err = None
        vid = request.POST.get("vendedor")
        cid_raw = (request.POST.get("comprador") or "").strip()
        comprador_id = None
        if cid_raw:
            try:
                comprador_id = int(cid_raw)
                if not Comprador.objects.filter(pk=comprador_id).exists():
                    comprador_id = None
                    err = "El comprador seleccionado no existe."
            except ValueError:
                err = "Comprador no válido."
                comprador_id = None
        fecha_v = _parse_date(request.POST.get("fecha_vencimiento_pago") or "")
        try:
            descuento = Decimal(str(request.POST.get("descuento_monto") or "0").replace(",", "."))
        except InvalidOperation:
            descuento = None
        try:
            comision_pct = Decimal(str(request.POST.get("comision_porcentaje") or "4").replace(",", "."))
        except InvalidOperation:
            comision_pct = None

        pids = request.POST.getlist("linea_producto")
        qtys = request.POST.getlist("linea_cantidad")

        if err is None and not vid:
            err = "Elegí un vendedor."
        elif err is None and not fecha_v:
            err = "Indicá la fecha de vencimiento del pago (dd/mm/aa)."
        elif err is None and (descuento is None or descuento < 0):
            err = "El descuento no es válido."
        elif err is None and (comision_pct is None or comision_pct < 0):
            err = "El porcentaje de comisión no es válido."
        elif err is None:
            line_specs = []
            subtotal = Decimal("0.00")
            for pid, qraw in zip(pids, qtys):
                pid = (pid or "").strip()
                qraw = (qraw or "").strip()
                if not pid and not qraw:
                    continue
                if not pid:
                    err = "Hay una línea sin producto."
                    break
                try:
                    qty = int(qraw)
                except ValueError:
                    err = "Las cantidades deben ser números enteros."
                    break
                if qty <= 0:
                    err = "La cantidad debe ser mayor a cero."
                    break
                try:
                    prod = Producto.objects.get(pk=int(pid), habilitado=True)
                except (ValueError, Producto.DoesNotExist):
                    err = "Un producto seleccionado no existe o está deshabilitado."
                    break
                if prod.stock < qty:
                    err = f"Stock insuficiente para {prod.codigo} (disponible: {prod.stock})."
                    break
                pu = prod.precio_venta
                st = (pu * qty).quantize(Decimal("0.01"))
                subtotal += st
                line_specs.append((prod, qty, pu, st))

            if err is None and not line_specs:
                err = "Agregá al menos un producto a la venta."

            if err is None:
                if descuento > subtotal:
                    err = "El descuento no puede superar el subtotal de las líneas."

            if err is None:
                venta = crear_venta_confirmada(
                    int(vid),
                    fecha_v,
                    descuento,
                    comision_pct,
                    line_specs,
                    comprador_id=comprador_id,
                    creado_por_id=request.user.id,
                )
                messages.success(request, f"Venta #{venta.pk} registrada. Orden de pago y evento en calendario.")
                return redirect("ventas_historial")

        messages.error(request, err)
        return render(
            request,
            "ventas/nueva.html",
            {
                "vendedores": vendedores,
                "compradores": compradores,
                "productos_catalogo": productos_catalogo,
            },
        )

    return render(
        request,
        "ventas/nueva.html",
        {
            "vendedores": vendedores,
            "compradores": compradores,
            "productos_catalogo": productos_catalogo,
        },
    )


def _filtrar_ventas_queryset(request):
    periodo = (request.GET.get("periodo") or "").strip()
    if periodo in ("7d", "30d", "mes", "mes_ant"):
        fecha_desde, fecha_hasta = rango_periodo(periodo)
    else:
        fecha_desde = parse_fecha_dashboard(request.GET.get("fecha_desde"))
        fecha_hasta = parse_fecha_dashboard(request.GET.get("fecha_hasta"))

    qs = (
        Venta.objects.select_related("vendedor", "comprador", "pago_movimiento")
        .prefetch_related("lineas__producto")
        .order_by("-creado_en", "-id")
    )
    if fecha_desde:
        qs = qs.filter(creado_en__date__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(creado_en__date__lte=fecha_hasta)

    vid = (request.GET.get("vendedor") or "").strip()
    if vid.isdigit():
        qs = qs.filter(vendedor_id=int(vid))

    cid = (request.GET.get("comprador") or "").strip()
    if cid.isdigit():
        qs = qs.filter(comprador_id=int(cid))

    pid = (request.GET.get("producto") or "").strip()
    if pid.isdigit():
        qs = qs.filter(lineas__producto_id=int(pid)).distinct()

    return qs, {
        "periodo": periodo,
        "fecha_desde": (request.GET.get("fecha_desde") or "").strip(),
        "fecha_hasta": (request.GET.get("fecha_hasta") or "").strip(),
        "vendedor": vid,
        "comprador": cid,
        "producto": pid,
    }


@login_required
def venta_historial(request):
    ventas, filtros_ctx = _filtrar_ventas_queryset(request)
    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = [
            "Pedido",
            "Fecha registro",
            "Vendedor",
            "Comprador",
            "Venc. pago",
            "Subtotal líneas",
            "Descuento",
            "Neto",
            "Comisión %",
            "Monto comisión",
            "Estado",
        ]
        rows = []
        for v in ventas:
            rows.append(
                [
                    v.pk,
                    v.creado_en.strftime("%d/%m/%Y %H:%M"),
                    str(v.vendedor),
                    str(v.comprador) if v.comprador_id else "",
                    v.fecha_vencimiento_pago.strftime("%d/%m/%Y"),
                    str(v.subtotal_lineas),
                    str(v.descuento_monto),
                    str(v.neto),
                    str(v.comision_porcentaje),
                    str(v.monto_comision),
                    v.get_estado_display(),
                ]
            )
        if exp == "xlsx":
            return xlsx_response("ventas", [("Ventas", headers, rows)])
        return pdf_response("ventas", "Historial de ventas", [("Ventas", headers, rows)])

    productos = Producto.objects.filter(habilitado=True).order_by("codigo")
    vendedores = Vendedor.objects.order_by("apellido", "nombre", "codigo")
    compradores = Comprador.objects.order_by("apellido", "nombre", "codigo")
    return render(
        request,
        "ventas/historial.html",
        {
            "ventas": ventas,
            "filtros": filtros_ctx,
            "productos_filtro": productos,
            "vendedores_filtro": vendedores,
            "compradores_filtro": compradores,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def venta_registrar_pago(request, pk: int):
    venta = get_object_or_404(
        Venta.objects.select_related("vendedor", "comprador", "pago_movimiento"), pk=pk
    )
    if venta.estado != Venta.Estado.PENDIENTE:
        messages.warning(request, "Esta venta ya fue marcada como pagada.")
        return redirect("ventas_historial")

    if request.method == "POST":
        form = VentaPagoForm(request.POST)
        if form.is_valid():
            mov = form.save(commit=False)
            mov.tipo = MovimientoCaja.Tipo.INGRESO
            mov.monto = venta.neto
            mov.operacion = f"Cobro pedido #{venta.pk}"
            mov.vendedor = venta.vendedor
            mov.venta = venta
            mov.creado_por = request.user
            mov.actualizado_por = request.user
            try:
                mov.full_clean()
            except ValidationError as e:
                if getattr(e, "error_dict", None):
                    for msgs in e.error_dict.values():
                        for m in msgs:
                            messages.error(request, str(m))
                else:
                    for m in e.messages:
                        messages.error(request, str(m))
                return render(
                    request,
                    "ventas/pago.html",
                    {"venta": venta, "form": form},
                )
            with transaction.atomic():
                mov.save()
                venta.estado = Venta.Estado.PAGADA
                venta.pago_movimiento = mov
                venta.actualizado_por = request.user
                venta.save(update_fields=["estado", "pago_movimiento", "actualizado_por"])
            messages.success(request, "Pago registrado en caja.")
            return redirect("ventas_historial")
    else:
        form = VentaPagoForm(
            initial={
                "fecha": datetime.now().strftime("%d/%m/%y"),
                "medio_pago": MovimientoCaja.MedioPago.EFECTIVO,
            }
        )

    return render(request, "ventas/pago.html", {"venta": venta, "form": form})
