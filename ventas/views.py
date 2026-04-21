from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.authz import staff_required
from core.comision_agg import comisiones_acumuladas_por_mes
from core.export_utils import parse_export, pdf_response, xlsx_response
from core.money_decimal import COMISION_PORCENTAJE_DEFECTO, format_monto_ars, q2
from core.repoblar_lineas import lineas_iniciales_desde_post, repoblar_campos_cabecera_desde_post
from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_dashboard, parse_fecha_param, rango_periodo

from calendario.models import Evento
from caja.models import MovimientoCaja
from personas.models import Comprador, Vendedor
from productos.listas_precios_views import (
    producto_listas_extra_context,
    sync_producto_listas_extras_from_post,
)
from productos.models import ListaPrecios, Producto

from .forms import VentaCabeceraEditForm, VentaPagoForm
from .models import Venta, VentaLinea
from .remito_pdf import remito_venta_pdf_response
from .servicios import crear_venta_confirmada, eliminar_venta_admin


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


def _lista_farmacia_o_primera() -> ListaPrecios | None:
    return (
        ListaPrecios.objects.filter(es_farmacia=True).order_by("id").first()
        or ListaPrecios.objects.order_by("id").first()
    )


def _lista_precios_desde_post(request) -> ListaPrecios | None:
    raw = (request.POST.get("lista_precios") or "").strip()
    if raw.isdigit():
        lista = ListaPrecios.objects.filter(pk=int(raw)).first()
        if lista:
            return lista
    return _lista_farmacia_o_primera()


def _precio_producto_para_lista(lista: ListaPrecios, prod: Producto) -> Decimal:
    p = lista.precio_para(prod)
    if p is not None:
        return q2(Decimal(str(p)))
    return q2(prod.precio_venta)


def _productos_payload_lista(lista: ListaPrecios):
    qs = Producto.objects.filter(habilitado=True).order_by("descripcion", "codigo")
    return [
        {
            "id": p.id,
            "codigo": p.codigo,
            "descripcion": p.descripcion,
            "precio": str(_precio_producto_para_lista(lista, p)),
            "stock": p.stock,
        }
        for p in qs
    ]


@login_required
@require_http_methods(["GET"])
def venta_catalogo_precios(request):
    lid = (request.GET.get("lista") or "").strip()
    if not lid.isdigit():
        return JsonResponse({"error": "Lista no válida"}, status=400)
    lista = ListaPrecios.objects.filter(pk=int(lid)).first()
    if lista is None:
        return JsonResponse({"error": "Lista no encontrada"}, status=404)
    return JsonResponse({"productos": _productos_payload_lista(lista)})


@login_required
@require_http_methods(["GET", "POST"])
def venta_nueva(request):
    vendedores = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    compradores = Comprador.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    listas_precio = list(ListaPrecios.objects.all().order_by("-es_farmacia", "nombre"))
    lista_default = _lista_farmacia_o_primera()
    productos_catalogo = _productos_payload_lista(lista_default) if lista_default else []

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
            comision_pct = Decimal(
                str(request.POST.get("comision_porcentaje") or str(COMISION_PORCENTAJE_DEFECTO)).replace(
                    ",", "."
                )
            )
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
            lista_venta = _lista_precios_desde_post(request)
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
                if lista_venta is not None:
                    pu = _precio_producto_para_lista(lista_venta, prod)
                else:
                    pu = q2(prod.precio_venta)
                st = (pu * qty).quantize(Decimal("0.01"))
                subtotal += st
                line_specs.append((prod, qty, pu, st, prod.codigo, prod.descripcion))

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
        lista_rep = _lista_precios_desde_post(request)
        cat_rep = _productos_payload_lista(lista_rep) if lista_rep else []
        return render(
            request,
            "ventas/nueva.html",
            {
                "vendedores": vendedores,
                "compradores": compradores,
                "listas_precio": listas_precio,
                "productos_catalogo": cat_rep,
                "lineas_iniciales": lineas_iniciales_desde_post(request),
                "repoblar": repoblar_campos_cabecera_desde_post(request),
                "comision_default": COMISION_PORCENTAJE_DEFECTO,
            },
        )

    return render(
        request,
        "ventas/nueva.html",
        {
            "vendedores": vendedores,
            "compradores": compradores,
            "listas_precio": listas_precio,
            "productos_catalogo": productos_catalogo,
            "lineas_iniciales": [],
            "repoblar": None,
            "comision_default": COMISION_PORCENTAJE_DEFECTO,
        },
    )


def _filtrar_ventas_queryset(request):
    periodo = (request.GET.get("periodo") or "").strip()
    if periodo in ("7d", "30d", "mes", "mes_ant"):
        fecha_desde, fecha_hasta = rango_periodo(periodo)
    else:
        fecha_desde = parse_fecha_dashboard(request.GET.get("fecha_desde"))
        fecha_hasta = parse_fecha_dashboard(request.GET.get("fecha_hasta"))

    # Nota: para el historial no necesitamos las líneas; evitamos prefetch para bajar memoria/tiempo.
    qs = Venta.objects.select_related("vendedor", "comprador", "pago_movimiento").order_by("-creado_en", "-id")
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


def _parse_ym(raw: str) -> tuple[int, int] | None:
    s = (raw or "").strip()
    if len(s) != 7 or s[4] != "-":
        return None
    y, m = s.split("-", 1)
    if not (y.isdigit() and m.isdigit()):
        return None
    yi = int(y)
    mi = int(m)
    if yi < 2000 or yi > 2100 or mi < 1 or mi > 12:
        return None
    return yi, mi


@login_required
@require_http_methods(["GET"])
def venta_comisiones(request):
    """
    Vista de comisiones: filtros por mes (YYYY-MM) o desde/hasta (fecha registro).
    Muestra acumulado mensual y desglose por vendedor (solo totales > 0).
    """
    ventas, _ = _filtrar_ventas_queryset(request)

    mes = (request.GET.get("mes") or "").strip()
    ym = _parse_ym(mes) if mes else None
    if ym:
        y, m = ym
        ventas = ventas.filter(creado_en__year=y, creado_en__month=m)

    # Solo ventas con comisión aplicada y comisión > 0.
    ventas_com = ventas.filter(aplica_comision=True, comision_porcentaje__gt=0)

    comisiones_por_mes = comisiones_acumuladas_por_mes(ventas_com)

    por_vendedor = (
        ventas_com.values("vendedor_id", "vendedor__codigo", "vendedor__apellido", "vendedor__nombre")
        .annotate(total=Coalesce(Sum("monto_comision"), Value(Decimal("0.00"))))
        .order_by("-total", "vendedor__apellido", "vendedor__nombre")
    )
    por_vendedor = [r for r in por_vendedor if (r.get("total") or Decimal("0.00")) > 0]

    # Opciones de meses: meses con comisiones en el conjunto (sin filtro de mes).
    meses_opciones = []
    seen = set()
    for row in comisiones_acumuladas_por_mes(
        _filtrar_ventas_queryset(request)[0].filter(aplica_comision=True, comision_porcentaje__gt=0)
    ):
        key = f"{row['anio']}-{int(row['mes']):02d}"
        if key in seen:
            continue
        seen.add(key)
        meses_opciones.append({"key": key, "label": f"{row['mes_nombre'].capitalize()} {row['anio']}"})

    return render(
        request,
        "ventas/comisiones.html",
        {
            "f": {
                "mes": mes,
                "fecha_desde": fecha_filtro_value_iso(request.GET.get("fecha_desde")),
                "fecha_hasta": fecha_filtro_value_iso(request.GET.get("fecha_hasta")),
                "periodo": (request.GET.get("periodo") or "").strip(),
            },
            "meses_opciones": meses_opciones,
            "comisiones_por_mes": comisiones_por_mes,
            "comisiones_por_vendedor": por_vendedor,
        },
    )


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

    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(ventas, 80)
    page_obj = paginator.get_page(page or 1)
    ventas_page = list(page_obj)

    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    querystring = qcopy.urlencode()

    productos = Producto.objects.filter(habilitado=True).order_by("descripcion", "codigo")
    vendedores = Vendedor.objects.order_by("apellido", "nombre", "codigo")
    compradores = Comprador.objects.order_by("apellido", "nombre", "codigo")
    return render(
        request,
        "ventas/historial.html",
        {
            "ventas": ventas_page,
            "filtros": filtros_ctx,
            "productos_filtro": productos,
            "vendedores_filtro": vendedores,
            "compradores_filtro": compradores,
            "page_obj": page_obj,
            "querystring": querystring,
        },
    )


@login_required
@staff_required
@require_http_methods(["POST"])
def venta_eliminar(request, pk: int):
    venta = get_object_or_404(Venta, pk=pk)
    nid = venta.pk
    try:
        eliminar_venta_admin(venta)
    except Exception as exc:
        detalle = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
        messages.error(request, "No se pudo eliminar el pedido." + detalle)
        return redirect("ventas_historial")
    messages.success(request, f"Pedido #{nid} eliminado (stock y caja/calendario revertidos si correspondía).")
    return redirect("ventas_historial")


@login_required
def venta_detalle(request, pk: int):
    venta = get_object_or_404(_venta_detalle_queryset(), pk=pk)
    if parse_export(request) == "pdf":
        return remito_venta_pdf_response(venta)
    productos_pedido_listas: list[dict] = []
    seen_pids: set[int] = set()
    for ln in venta.lineas.select_related("producto").order_by("id"):
        if ln.producto_id in seen_pids:
            continue
        seen_pids.add(ln.producto_id)
        productos_pedido_listas.append(
            {"producto": ln.producto, **producto_listas_extra_context(ln.producto)}
        )
    lista_farmacia = ListaPrecios.objects.filter(es_farmacia=True).order_by("id").first()
    return render(
        request,
        "ventas/detalle.html",
        {
            "venta": venta,
            "productos_pedido_listas": productos_pedido_listas,
            "lista_farmacia": lista_farmacia,
        },
    )


@staff_required
@require_http_methods(["POST"])
def venta_producto_listas_precio(request, pk: int, producto_pk: int):
    """Desde la ficha del pedido: activa Farmacia (PDF) y asocia el producto a listas de rubro."""
    venta = get_object_or_404(Venta, pk=pk)
    if not VentaLinea.objects.filter(venta_id=venta.pk, producto_id=producto_pk).exists():
        messages.error(request, "Este producto no forma parte del pedido.")
        return redirect("venta_detalle", pk=pk)
    producto = get_object_or_404(Producto, pk=producto_pk)
    if request.POST.get("listas_extra_present") != "1":
        messages.error(request, "Solicitud inválida.")
        return redirect("venta_detalle", pk=pk)
    with transaction.atomic():
        producto.en_lista_precios = True
        producto.save(update_fields=["en_lista_precios"])
        sync_producto_listas_extras_from_post(request, producto)
    messages.success(
        request,
        f"Listas actualizadas para {producto.codigo}: Farmacia (PDF) activada; rubros según lo marcado.",
    )
    return redirect("venta_detalle", pk=pk)


@login_required
@require_http_methods(["GET", "POST"])
def venta_editar(request, pk: int):
    venta = get_object_or_404(Venta.objects.select_related("vendedor", "comprador"), pk=pk)
    if venta.estado != Venta.Estado.PENDIENTE:
        return render(request, "ventas/editar_bloqueado.html", {"venta": venta})

    if request.method == "POST":
        # No permitir líneas ni montos de cabecera por POST fuera del formulario acotado.
        if request.POST.getlist("linea_producto") or request.POST.getlist("linea_cantidad"):
            messages.error(
                request,
                "No se pueden modificar productos, cantidades ni precios del pedido al editar la cabecera.",
            )
            return redirect("venta_editar", pk=pk)
        if (request.POST.get("descuento_monto") or "").strip():
            messages.error(request, "El descuento del pedido no se puede cambiar desde la edición.")
            return redirect("venta_editar", pk=pk)
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
