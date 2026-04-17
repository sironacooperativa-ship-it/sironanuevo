from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.comision_agg import comisiones_acumuladas_por_mes
from core.export_utils import parse_export, pdf_response, xlsx_response
from core.money_decimal import format_monto_ars, q2
from core.repoblar_lineas import lineas_iniciales_desde_post, repoblar_campos_cabecera_desde_post
from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_dashboard, parse_fecha_param, rango_periodo

from calendario.models import Evento
from caja.models import MovimientoCaja
from personas.models import Comprador, Vendedor
from productos.models import Producto

from .forms import VentaCabeceraEditForm, VentaPagoForm
from .models import Venta, VentaLinea
from .remito_pdf import remito_venta_pdf_response
from .servicios import crear_venta_confirmada


def _sync_evento_pedido_pendiente(venta: Venta) -> None:
    """Crea, actualiza o elimina el evento de calendario según la fecha de vencimiento del pedido."""
    titulo = f"Pago pendiente — Pedido #{venta.pk}"
    qs = Evento.objects.filter(tipo=Evento.Tipo.PEDIDO, titulo=titulo)
    extra = f" Comprador: {venta.comprador}." if venta.comprador_id else ""
    com_txt = (
        f"Comisión ({venta.comision_porcentaje}%): {format_monto_ars(venta.monto_comision)}."
        if venta.aplica_comision
        else "Sin comisión al vendedor."
    )
    desc = (
        f"Vendedor: {venta.vendedor}. "
        f"Monto neto pedido: {format_monto_ars(venta.neto)}. {com_txt} "
        f"Ingreso en caja al cobrar: {format_monto_ars(venta.monto_ingreso_caja)}.{extra}"
    )
    if venta.fecha_vencimiento_pago is None:
        qs.delete()
        return
    if qs.exists():
        qs.update(fecha=venta.fecha_vencimiento_pago, descripcion=desc)
    else:
        Evento.objects.create(
            fecha=venta.fecha_vencimiento_pago,
            titulo=titulo,
            tipo=Evento.Tipo.PEDIDO,
            descripcion=desc,
        )


def _venta_detalle_queryset():
    return (
        Venta.objects.select_related(
            "vendedor",
            "comprador",
            "pago_movimiento",
            "pago_movimiento__cuenta_bancaria",
            "creado_por",
        )
        .prefetch_related("lineas__producto")
    )


def _productos_payload():
    qs = Producto.objects.filter(habilitado=True).order_by("descripcion", "codigo")
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
        fecha_v = parse_fecha_param(request.POST.get("fecha_vencimiento_pago") or "")
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
            err = "Indicá la fecha de vencimiento del pago."
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
                aplica_comision = request.POST.get("aplica_comision") == "1"
                venta = crear_venta_confirmada(
                    int(vid),
                    fecha_v,
                    descuento,
                    comision_pct,
                    line_specs,
                    comprador_id=comprador_id,
                    creado_por_id=request.user.id,
                    aplica_comision=aplica_comision,
                )
                messages.success(request, f"Venta #{venta.pk} registrada. Orden de pago y evento en calendario.")
                return redirect("ventas_historial")

        if err:
            messages.error(request, err)
        return render(
            request,
            "ventas/nueva.html",
            {
                "vendedores": vendedores,
                "compradores": compradores,
                "productos_catalogo": productos_catalogo,
                "lineas_iniciales": lineas_iniciales_desde_post(request),
                "repoblar": repoblar_campos_cabecera_desde_post(request),
            },
        )

    return render(
        request,
        "ventas/nueva.html",
        {
            "vendedores": vendedores,
            "compradores": compradores,
            "productos_catalogo": productos_catalogo,
            "lineas_iniciales": [],
            "repoblar": None,
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
        "fecha_desde": fecha_filtro_value_iso(request.GET.get("fecha_desde")),
        "fecha_hasta": fecha_filtro_value_iso(request.GET.get("fecha_hasta")),
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
            "Aplica comisión",
            "Comisión %",
            "Monto comisión",
            "Ingreso caja",
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
                    v.fecha_vencimiento_pago.strftime("%d/%m/%Y") if v.fecha_vencimiento_pago else "",
                    str(q2(v.subtotal_lineas)),
                    str(q2(v.descuento_monto)),
                    str(q2(v.neto)),
                    "Sí" if v.aplica_comision else "No",
                    str(v.comision_porcentaje),
                    str(q2(v.monto_comision)),
                    str(q2(v.monto_ingreso_caja)),
                    v.get_estado_display(),
                ]
            )
        if exp == "xlsx":
            return xlsx_response("ventas", [("Ventas", headers, rows)])
        return pdf_response("ventas", "Historial de ventas", [("Ventas", headers, rows)])

    productos = Producto.objects.filter(habilitado=True).order_by("descripcion", "codigo")
    vendedores = Vendedor.objects.order_by("apellido", "nombre", "codigo")
    compradores = Comprador.objects.order_by("apellido", "nombre", "codigo")
    comisiones_por_mes = comisiones_acumuladas_por_mes(ventas)
    return render(
        request,
        "ventas/historial.html",
        {
            "ventas": ventas,
            "filtros": filtros_ctx,
            "productos_filtro": productos,
            "vendedores_filtro": vendedores,
            "compradores_filtro": compradores,
            "comisiones_por_mes": comisiones_por_mes,
        },
    )


@login_required
def venta_detalle(request, pk: int):
    venta = get_object_or_404(_venta_detalle_queryset(), pk=pk)
    if parse_export(request) == "pdf":
        return remito_venta_pdf_response(venta)
    return render(request, "ventas/detalle.html", {"venta": venta})


@login_required
@require_http_methods(["GET", "POST"])
def venta_editar(request, pk: int):
    venta = get_object_or_404(Venta.objects.select_related("vendedor", "comprador"), pk=pk)
    if venta.estado != Venta.Estado.PENDIENTE:
        return render(request, "ventas/editar_bloqueado.html", {"venta": venta})

    if request.method == "POST":
        form = VentaCabeceraEditForm(request.POST, instance=venta)
        if form.is_valid():
            v = form.save(commit=False)
            v.actualizado_por = request.user
            v.save()
            _sync_evento_pedido_pendiente(v)
            messages.success(request, "Pedido actualizado.")
            return redirect("venta_detalle", pk=v.pk)
    else:
        form = VentaCabeceraEditForm(instance=venta)

    return render(request, "ventas/editar.html", {"venta": venta, "form": form})


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
            mov.monto = venta.monto_ingreso_caja
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
            return redirect("venta_detalle", pk=venta.pk)
    else:
        form = VentaPagoForm(
            initial={
                "fecha": datetime.now().strftime("%Y-%m-%d"),
                "medio_pago": MovimientoCaja.MedioPago.EFECTIVO,
            }
        )

    return render(request, "ventas/pago.html", {"venta": venta, "form": form})
