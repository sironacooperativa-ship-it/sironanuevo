from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import zip_longest

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Prefetch
from django.db.utils import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_http_methods

from core.authz import is_staff_user, staff_required
from core.export_utils import parse_export, pdf_response, xlsx_response
from core.money_decimal import (
    COMISION_PORCENTAJE_DEFECTO,
    format_monto_ars,
    parse_decimal_from_input,
    q2,
)
from core.repoblar_lineas import lineas_iniciales_desde_post, repoblar_campos_cabecera_desde_post
from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_dashboard, parse_fecha_param, rango_periodo

from caja.models import MovimientoCaja
from personas.models import Comprador, Vendedor
from productos.catalogo_json import (
    productos_payload_para_lineas,
    productos_payload_para_lista,
    productos_payload_todos,
)
from productos.stock_cero import encolar_prompt_stock_cero, ids_que_quedaron_en_cero, snapshot_stock
from productos.listas_precios_views import sync_producto_listas_extras_from_post
from productos.models import ListaPrecios, Producto

from .forms import VentaCabeceraEditForm, VentaPagoForm
from .models import ComisionLiquidacionPago, Venta, VentaLinea
from .comision_constancia_pdf_sirona import comision_constancia_pdf_response
from .despacho_servicios import (
    DESPACHO_HISTORIAL_DIAS,
    archivar_lineas_pedido_despachado,
    venta_despacho_json_payload,
    ventas_despachos_activos_queryset,
    ventas_despachos_historial_queryset,
)
from .remito_pdf import remito_venta_pdf_response
from .servicios import (
    crear_venta_confirmada,
    eliminar_venta_admin,
    merge_stock_confirmacion_venta_locked,
    parse_stock_venta_json_from_post,
    sincronizar_productos_lista_elegida_en_venta,
    sync_evento_pedido_pendiente,
    venta_aplicar_snapshot_ganancia_cobro,
    venta_costo_mercaderia_actual,
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


def _productos_queryset_para_lista(lista: ListaPrecios):
    """
    Productos que se muestran/permiten seleccionar para una lista.
    - Farmacia: solo los marcados `en_lista_precios` (lista PDF).
    - Rubro: solo los que tengan precio configurado en `ListaPrecioItem` para esa lista.
    """
    qs = Producto.objects.filter(habilitado=True)
    if lista.es_farmacia:
        return qs.filter(en_lista_precios=True)
    return qs.filter(items_lista_precio__lista_id=lista.pk).distinct()


def _productos_payload_lista(lista: ListaPrecios):
    return productos_payload_para_lista(lista)


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
@require_http_methods(["GET"])
def venta_catalogo_completo(request):
    """Catálogo completo (edición de pedido): se carga por AJAX para no bloquear el HTML inicial."""
    return JsonResponse({"productos": productos_payload_todos()})


@login_required
@require_http_methods(["GET", "POST"])
def venta_nueva(request):
    vendedores = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    compradores = Comprador.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    listas_precio = list(ListaPrecios.objects.all().order_by("-es_farmacia", "nombre"))
    lista_default = _lista_farmacia_o_primera()
    productos_catalogo: list[dict] = []

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
            if lista_venta is None:
                err = "No hay listas de precio disponibles. Creá al menos una en Productos → Listas de precio."
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
                    prod_id = int(pid)
                except (ValueError, Producto.DoesNotExist):
                    err = "Producto no válido."
                    break
                if lista_venta is not None:
                    prod = (
                        _productos_queryset_para_lista(lista_venta)
                        .filter(pk=prod_id)
                        .first()
                    )
                    if prod is None:
                        err = "Un producto seleccionado no pertenece a la lista de precios elegida."
                        break
                else:
                    prod = Producto.objects.filter(pk=prod_id, habilitado=True).first()
                    if prod is None:
                        err = "Un producto seleccionado no existe o está deshabilitado."
                        break
                pu = _precio_producto_para_lista(lista_venta, prod) if lista_venta else q2(prod.precio_venta)
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
                try:
                    stock_conf = parse_stock_venta_json_from_post(request.POST)
                except ValidationError as exc:
                    err = "; ".join(getattr(exc, "messages", [str(exc)]))
                    stock_conf = None
                if err is None:
                    pids_venta = [int(spec[0].pk) for spec in line_specs]
                    prev_snap_venta = snapshot_stock(pids_venta)
                    try:
                        venta = crear_venta_confirmada(
                            int(vid),
                            fecha_v,
                            descuento,
                            comision_pct,
                            line_specs,
                            comprador_id=comprador_id,
                            creado_por_id=request.user.id,
                            aplica_comision=aplica_comision,
                            stock_confirmacion=stock_conf,
                        )
                    except ValidationError as exc:
                        err = "; ".join(getattr(exc, "messages", [str(exc)]))
                        venta = None
                    if err is None:
                        sincronizar_productos_lista_elegida_en_venta(lista_venta, line_specs)
                        if not stock_conf:
                            nuevos_cero = ids_que_quedaron_en_cero(prev_snap_venta, pids_venta)
                            if nuevos_cero:
                                encolar_prompt_stock_cero(request, nuevos_cero)
                        messages.success(request, f"Venta #{venta.pk} registrada. Orden de pago y evento en calendario.")
                        return redirect("ventas_historial")

        if err:
            messages.error(request, err)
        lista_rep = _lista_precios_desde_post(request)
        cat_rep = productos_payload_para_lineas(lineas_iniciales_desde_post(request))
        repoblar = repoblar_campos_cabecera_desde_post(request)
        return render(
            request,
            "ventas/nueva.html",
            {
                "vendedores": vendedores,
                "compradores": compradores,
                "listas_precio": listas_precio,
                "productos_catalogo": cat_rep,
                "lineas_iniciales": lineas_iniciales_desde_post(request),
                "repoblar": repoblar,
                "comision_default": COMISION_PORCENTAJE_DEFECTO,
                "lista_default": lista_default,
                "vendedor_default_aplica_comision": Vendedor.aplica_comision_por_defecto_para(
                    repoblar.get("vendedor_id")
                ),
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
            "lista_default": lista_default,
            "vendedor_default_aplica_comision": True,
        },
    )


def _ventas_lista_base_queryset(request):
    """
    Listado de ventas con filtros de período / vendedor / comprador / producto.
    No aplica filtro por estado (lo agrega `_filtrar_ventas_queryset`).
    """
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

    filtros = {
        "periodo": periodo,
        "fecha_desde": fecha_filtro_value_iso(request.GET.get("fecha_desde")),
        "fecha_hasta": fecha_filtro_value_iso(request.GET.get("fecha_hasta")),
        "vendedor": vid,
        "comprador": cid,
        "producto": pid,
    }
    return qs, filtros


def _venta_historial_querystring_pestana(request, pestana: str) -> str:
    q = request.GET.copy()
    q["pestana"] = pestana
    q.pop("page", None)
    q.pop("estado", None)
    return q.urlencode()


_MES_NOMBRE_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _venta_costo_neto_ganancia_historial(v: Venta) -> tuple[Decimal, Decimal, Decimal]:
    """
    Costo, neto y ganancia para listados.
    Pedidos pagados: solo valores congelados (al cobrar o rellenados en migración 0012); no se recalcula con costos vivos.
    Pendientes: costo según costo actual del producto.
    """
    if v.estado == Venta.Estado.PAGADA and v.ganancia_cobro is not None:
        return (
            q2(v.costo_mercaderia_cobro or Decimal("0.00")),
            q2(v.neto_cobro if v.neto_cobro is not None else v.neto),
            q2(v.ganancia_cobro),
        )
    if v.estado == Venta.Estado.PAGADA:
        # Sin snapshot (p. ej. antes de aplicar migración 0012): una vez alineado con costos del maestro vigente al cobrar histórico.
        cm = venta_costo_mercaderia_actual(v)
        net = q2(v.neto)
        return cm, net, q2(net - cm)
    cm = venta_costo_mercaderia_actual(v)
    net = q2(v.neto)
    return cm, net, q2(net - cm)


def _historial_ganancia_meses_desde_ventas(ventas_list: list[Venta]) -> tuple[list[dict[str, object]], dict[str, object]]:
    """
    Agrupa pedidos por mes calendario (fecha local de registro), con costo de mercadería y ganancia por fila.
    Pedidos pagados: costo y ganancia congelados (al cobrar o al migrar datos históricos); pendientes: estimación con costo actual del producto.
    """
    nest: dict[tuple[int, int], list[Venta]] = defaultdict(list)
    for v in ventas_list:
        t = timezone.localtime(v.creado_en)
        nest[(t.year, t.month)].append(v)

    meses_detalle: list[dict[str, object]] = []
    sum_costo = sum_neto = sum_gan = Decimal("0.00")
    for y, m in sorted(nest.keys(), reverse=True):
        lst = nest[(y, m)]
        lst.sort(key=lambda x: (x.creado_en, x.pk), reverse=True)
        filas: list[dict[str, object]] = []
        mc_mes = Decimal("0.00")
        nc_mes = Decimal("0.00")
        gc_mes = Decimal("0.00")
        for v in lst:
            cm, net, gn = _venta_costo_neto_ganancia_historial(v)
            filas.append({"venta": v, "costo_mercaderia": cm, "neto": net, "ganancia": gn})
            mc_mes = q2(mc_mes + cm)
            nc_mes = q2(nc_mes + net)
            gc_mes = q2(gc_mes + gn)
        meses_detalle.append(
            {
                "label": f"{_MES_NOMBRE_ES[m - 1].capitalize()} {y}",
                "filas": filas,
                "total_mes_costo": mc_mes,
                "total_mes_neto": nc_mes,
                "total_mes_ganancia": gc_mes,
                "n_pedidos": len(filas),
            }
        )
        sum_costo = q2(sum_costo + mc_mes)
        sum_neto = q2(sum_neto + nc_mes)
        sum_gan = q2(sum_gan + gc_mes)

    totales = {
        "costo": sum_costo,
        "neto": sum_neto,
        "ganancia": sum_gan,
        "n_pedidos": len(ventas_list),
    }
    return meses_detalle, totales


def _filtrar_ventas_queryset(request, *, historial_pestana: bool = False):
    qs, filtros = _ventas_lista_base_queryset(request)
    pestana = ""
    estado = ""

    if historial_pestana:
        pestana_raw = (request.GET.get("pestana") or "").strip().lower()
        estado_legacy = (request.GET.get("estado") or "").strip().upper()
        if pestana_raw == "pagos":
            pestana = "pagos"
            qs = qs.filter(estado=Venta.Estado.PAGADA)
        elif pestana_raw == "a_pagar":
            pestana = "a_pagar"
            qs = qs.filter(estado=Venta.Estado.PENDIENTE)
        elif pestana_raw == "ganancia":
            pestana = "ganancia"
            qs = qs.filter(estado__in=[Venta.Estado.PENDIENTE, Venta.Estado.PAGADA])
        elif estado_legacy == "PAG":
            pestana = "pagos"
            qs = qs.filter(estado=Venta.Estado.PAGADA)
        elif estado_legacy == "PEN":
            pestana = "a_pagar"
            qs = qs.filter(estado=Venta.Estado.PENDIENTE)
        else:
            pestana = "a_pagar"
            qs = qs.filter(estado=Venta.Estado.PENDIENTE)
        filtros["pestana"] = pestana
        filtros["estado"] = ""
    else:
        estado_raw = (request.GET.get("estado") or "").strip().upper()
        estado = estado_raw if estado_raw in {c for c, _ in Venta.Estado.choices} else ""
        if estado:
            qs = qs.filter(estado=estado)
        filtros["estado"] = estado
        filtros["pestana"] = ""

    return qs, filtros


@login_required
@require_http_methods(["GET"])
def venta_comisiones(request):
    """
    Comisiones por pedido (pagadas en verde, pendientes en negro), agrupadas por mes calendario del pedido.
    La liquidación puede incluir todas las comisiones pendientes del vendedor (pedidos pagos, filtros actuales)
    o solo las pedidos marcados; la constancia PDF replica el estilo de pedidos Sirona.
    """
    ventas_qs, filtros_base = _comisiones_ventas_base_queryset(request)
    ventas_list = list(ventas_qs.order_by("-creado_en", "-id"))

    nest: dict[tuple[int, int], dict[int, list[Venta]]] = defaultdict(lambda: defaultdict(list))
    for v in ventas_list:
        t = v.creado_en
        nest[(t.year, t.month)][int(v.vendedor_id)].append(v)

    _meses_es = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    meses_detalle: list[dict[str, object]] = []
    for y, m in sorted(nest.keys(), reverse=True):
        por_vid = nest[(y, m)]
        pedidos_mes_total = q2(sum(x.monto_comision for ls in por_vid.values() for x in ls))
        por_vendedor: list[dict[str, object]] = []
        for vid in sorted(
            por_vid.keys(),
            key=lambda i: (
                (por_vid[i][0].vendedor.apellido or "").lower(),
                (por_vid[i][0].vendedor.nombre or "").lower(),
            ),
        ):
            lst = sorted(por_vid[vid], key=lambda s: (-s.pk,))
            ven = lst[0].vendedor
            por_vendedor.append(
                {
                    "vendedor": ven,
                    "pedidos": lst,
                    "subtotal_mes_vendedor": q2(sum(s.monto_comision for s in lst)),
                }
            )
        meses_detalle.append(
            {
                "label": f"{_meses_es[m - 1].capitalize()} {y}",
                "total_mes": pedidos_mes_total,
                "por_vendedor": por_vendedor,
            }
        )

    base_liq, _ = _ventas_lista_base_queryset(request)
    liq_base_qs = base_liq.filter(
        estado=Venta.Estado.PAGADA,
        aplica_comision=True,
        comision_porcentaje__gt=0,
        comision_liquidacion_pago_id__isnull=True,
    ).select_related("vendedor", "comprador")

    by_vid: dict[int, list[Venta]] = defaultdict(list)
    for v in liq_base_qs.order_by("-creado_en", "-id"):
        by_vid[int(v.vendedor_id)].append(v)

    pendiente_liquidar_global: list[dict[str, object]] = []
    for vid, ventas_liquidables in sorted(
        by_vid.items(),
        key=lambda kv: (-q2(sum(s.monto_comision for s in kv[1])), kv[0]),
    ):
        total = q2(sum(s.monto_comision for s in ventas_liquidables))
        if total <= 0:
            continue
        ven = ventas_liquidables[0].vendedor
        pendiente_liquidar_global.append(
            {
                "vendedor_id": vid,
                "vendedor__codigo": ven.codigo,
                "vendedor__apellido": ven.apellido,
                "vendedor__nombre": ven.nombre,
                "pendiente": total,
                "ventas_liquidables": ventas_liquidables,
            }
        )

    return render(
        request,
        "ventas/comisiones.html",
        {
            "f": {
                "fecha_desde": fecha_filtro_value_iso(request.GET.get("fecha_desde")),
                "fecha_hasta": fecha_filtro_value_iso(request.GET.get("fecha_hasta")),
                "periodo": (request.GET.get("periodo") or "").strip(),
                "estado": (request.GET.get("estado") or "").strip().upper(),
                "vendedor": (filtros_base.get("vendedor") or "").strip(),
            },
            "filtros_base": filtros_base,
            "meses_detalle": meses_detalle,
            "pendiente_liquidar_global": pendiente_liquidar_global,
            "vendedores_opciones": Vendedor.objects.filter(habilitado=True).order_by(
                "apellido", "nombre", "codigo"
            ),
        },
    )


def _comisiones_ventas_base_queryset(request):
    """Pedidos con comisión aplicable, con filtros de listado (fechas, vendedor, etc.) sin pestaña historial."""
    qs, filtros = _ventas_lista_base_queryset(request)
    estado = (request.GET.get("estado") or "").strip().upper()
    if estado in (Venta.Estado.PENDIENTE, Venta.Estado.PAGADA):
        qs = qs.filter(estado=estado)
    return (
        qs.filter(aplica_comision=True, comision_porcentaje__gt=0).select_related(
            "vendedor", "comision_liquidacion_pago"
        ),
        filtros,
    )


def _ventas_comision_liquidables_vendedor(request, vid: int):
    ventas, _ = _ventas_lista_base_queryset(request)
    return ventas.filter(
        vendedor_id=vid,
        estado=Venta.Estado.PAGADA,
        aplica_comision=True,
        comision_porcentaje__gt=0,
        comision_liquidacion_pago_id__isnull=True,
    )


@login_required
@require_http_methods(["GET"])
def comision_constancia_pdf(request, pk: int):
    liq = get_object_or_404(
        ComisionLiquidacionPago.objects.select_related("vendedor", "movimiento_caja", "creado_por"),
        pk=pk,
    )
    agrupar = (request.GET.get("agrupar_periodo") or "ninguno").strip().lower()
    if agrupar not in ("ninguno", "mes", "semana"):
        agrupar = "ninguno"
    ventas_qs = (
        Venta.objects.filter(comision_liquidacion_pago_id=liq.pk)
        .select_related("vendedor", "comprador")
        .order_by("creado_en", "id")
    )
    sales = list(ventas_qs)
    if not sales:
        messages.warning(request, "No hay pedidos asociados a esta liquidación.")
        return redirect("ventas_comisiones_historial")

    return comision_constancia_pdf_response(liq, sales, agrupar_periodo=agrupar)


@login_required
@require_http_methods(["POST"])
def comision_liquidacion_pagar(request):
    vid_raw = (request.POST.get("vendedor") or "").strip()
    redir = reverse("ventas_comisiones")
    if not vid_raw.isdigit():
        messages.error(request, "Datos inválidos para el pago de comisiones.")
        return redirect(redir)
    vid = int(vid_raw)

    agrupar = (request.POST.get("agrupar_periodo") or "ninguno").strip().lower()
    if agrupar not in ("ninguno", "mes", "semana"):
        agrupar = "ninguno"

    modo = (request.POST.get("liquidar_modo") or "").strip().lower()
    if modo not in ("todos", "seleccion"):
        modo = "todos" if not request.POST.getlist("venta_id") else "seleccion"

    try:
        with transaction.atomic():
            qs = (
                _ventas_comision_liquidables_vendedor(request, vid)
                .select_related("vendedor", "comprador")
                .order_by("creado_en", "id")
            )
            try:
                qs = qs.select_for_update(of=("self",))
            except TypeError:
                qs = qs.select_for_update()

            if modo == "seleccion":
                wanted = {int(x) for x in request.POST.getlist("venta_id") if str(x).strip().isdigit()}
                if not wanted:
                    messages.error(
                        request,
                        "Elegí “Liquidar todas” o marcá al menos un pedido pagado con comisión pendiente.",
                    )
                    return redirect(redir)
                ventas_list = list(qs.filter(pk__in=wanted))
                got = {v.pk for v in ventas_list}
                if got != wanted:
                    messages.error(
                        request,
                        "Algunos pedidos no se pueden liquidar: deben ser pagos, con comisión aplicable y aún sin liquidar.",
                    )
                    return redirect(redir)
            else:
                ventas_list = list(qs)

            if not ventas_list:
                messages.warning(request, "No hay comisiones pagadas pendientes de liquidar para ese vendedor.")
                return redirect(redir)
            total = q2(sum(v.monto_comision for v in ventas_list))
            if total <= 0:
                messages.warning(request, "El total a pagar es cero.")
                return redirect(redir)

            vend = ventas_list[0].vendedor
            hoy = timezone.localdate()
            liq = ComisionLiquidacionPago.objects.create(
                vendedor=vend,
                anio=None,
                mes=None,
                fecha_liquidacion=hoy,
                total=total,
                creado_por=request.user,
            )
            mov = MovimientoCaja(
                fecha=hoy,
                operacion=f"Pago comisiones {vend.apellido}, {vend.nombre} — {len(ventas_list)} pedidos (liq. #{liq.pk})",
                tipo=MovimientoCaja.Tipo.EGRESO,
                monto=total,
                medio_pago=MovimientoCaja.MedioPago.EFECTIVO,
                vendedor=vend,
                creado_por=request.user,
                actualizado_por=request.user,
            )
            mov.full_clean()
            mov.save()
            liq.movimiento_caja = mov
            liq.save(update_fields=["movimiento_caja"])
            for v in ventas_list:
                v.comision_liquidacion_pago = liq
                v.save(update_fields=["comision_liquidacion_pago"])
        messages.success(request, f"Pago de comisiones registrado en caja: {format_monto_ars(total)}.")
        base = reverse("ventas_comision_constancia_pdf", kwargs={"pk": liq.pk})
        return redirect(f"{base}?{urlencode({'agrupar_periodo': agrupar})}")
    except ValidationError as e:
        if getattr(e, "error_dict", None):
            for msgs in e.error_dict.values():
                for merr in msgs:
                    messages.error(request, str(merr))
        else:
            for merr in e.messages:
                messages.error(request, str(merr))
    except Exception as exc:
        det = f" {exc}" if getattr(request.user, "is_staff", False) else ""
        messages.error(request, "No se pudo registrar el pago." + det)

    return redirect(redir)


@login_required
@require_http_methods(["GET"])
def venta_comisiones_historial(request):
    liq_qs = ComisionLiquidacionPago.objects.select_related("vendedor", "movimiento_caja").order_by(
        "-creado_en", "-id"
    )
    vid_f = (request.GET.get("vendedor") or "").strip()
    if vid_f.isdigit():
        liq_qs = liq_qs.filter(vendedor_id=int(vid_f))
    liquidaciones = list(liq_qs[:500])
    liq_ids = [x.pk for x in liquidaciones]
    ventas_por_liq: dict[int, list[Venta]] = defaultdict(list)
    if liq_ids:
        for v in (
            Venta.objects.filter(comision_liquidacion_pago_id__in=liq_ids)
            .select_related("vendedor")
            .order_by("comision_liquidacion_pago_id", "id")
        ):
            ventas_por_liq[int(v.comision_liquidacion_pago_id)].append(v)

    base_liq, _ = _ventas_lista_base_queryset(request)
    pendientes = list(
        base_liq.filter(
            estado=Venta.Estado.PAGADA,
            aplica_comision=True,
            comision_porcentaje__gt=0,
            comision_liquidacion_pago_id__isnull=True,
        )
        .select_related("vendedor")
        .order_by("vendedor__apellido", "vendedor__nombre", "-id")
    )

    por_vendedor_hist: dict[int, dict[str, object]] = {}
    for liq in liquidaciones:
        vid = int(liq.vendedor_id)
        bucket = por_vendedor_hist.get(vid)
        if not bucket:
            bucket = {
                "vendedor": liq.vendedor,
                "liquidaciones": [],
                "total_liquidado": Decimal("0.00"),
            }
            por_vendedor_hist[vid] = bucket
        ventas_li = ventas_por_liq.get(liq.pk, [])
        bucket["liquidaciones"].append({"liq": liq, "ventas": ventas_li})
        bucket["total_liquidado"] = q2(bucket["total_liquidado"] + liq.total)

    por_vendedor_pend: dict[int, list[Venta]] = defaultdict(list)
    for v in pendientes:
        por_vendedor_pend[int(v.vendedor_id)].append(v)

    vendedores_ids = sorted(set(por_vendedor_hist.keys()) | set(por_vendedor_pend.keys()))
    filas: list[dict[str, object]] = []
    for vid in vendedores_ids:
        hist = por_vendedor_hist.get(vid)
        pend_ls = por_vendedor_pend.get(vid, [])
        ven = (hist["vendedor"] if hist else (pend_ls[0].vendedor if pend_ls else None))
        if not ven:
            continue
        filas.append(
            {
                "vendedor": ven,
                "liquidaciones": (hist["liquidaciones"] if hist else []),
                "total_liquidado": q2(hist["total_liquidado"]) if hist else Decimal("0.00"),
                "pendientes": pend_ls,
                "total_pendiente_liquidar": q2(sum(x.monto_comision for x in pend_ls)),
            }
        )
    filas.sort(key=lambda r: (r["vendedor"].apellido or "", r["vendedor"].nombre or ""))

    return render(
        request,
        "ventas/comisiones_historial.html",
        {
            "filas": filas,
            "f": {"vendedor": vid_f},
            "vendedores_opciones": Vendedor.objects.filter(habilitado=True).order_by(
                "apellido", "nombre", "codigo"
            ),
        },
    )


@login_required
def venta_historial(request):
    ventas, filtros_ctx = _filtrar_ventas_queryset(request, historial_pestana=True)
    base_qs, _ = _ventas_lista_base_queryset(request)
    n_ventas_a_pagar = base_qs.filter(estado=Venta.Estado.PENDIENTE).count()
    n_ventas_pagos = base_qs.filter(estado=Venta.Estado.PAGADA).count()
    n_ventas_ganancia = n_ventas_a_pagar + n_ventas_pagos

    pestana = filtros_ctx.get("pestana") or ""
    exp = parse_export(request)

    if exp in ("xlsx", "pdf") and pestana == "ganancia":
        ventas_g = list(
            ventas.order_by("-creado_en", "-id").prefetch_related(
                Prefetch("lineas", queryset=VentaLinea.objects.select_related("producto"))
            )
        )
        meses_detalle, totales = _historial_ganancia_meses_desde_ventas(ventas_g)
        headers = [
            "Pedido",
            "Fecha registro",
            "Vendedor",
            "Comprador",
            "Estado",
            "Costo mercadería",
            "Neto",
            "Ganancia",
        ]
        if exp == "xlsx":
            h_x = ["Mes calendario", *headers]
            rows_x: list[list[object]] = []
            for mes in meses_detalle:
                for fila in mes["filas"]:
                    v = fila["venta"]
                    rows_x.append(
                        [
                            mes["label"],
                            v.pk,
                            timezone.localtime(v.creado_en).strftime("%d/%m/%Y %H:%M"),
                            str(v.vendedor),
                            str(v.comprador) if v.comprador_id else "",
                            v.get_estado_display(),
                            str(q2(fila["costo_mercaderia"])),
                            str(q2(fila["neto"])),
                            str(q2(fila["ganancia"])),
                        ]
                    )
            res_h = ["Mes calendario", "Pedidos", "Costo mercadería", "Neto", "Ganancia"]
            res_rows: list[list[object]] = []
            for mes in meses_detalle:
                res_rows.append(
                    [
                        mes["label"],
                        mes["n_pedidos"],
                        str(q2(mes["total_mes_costo"])),
                        str(q2(mes["total_mes_neto"])),
                        str(q2(mes["total_mes_ganancia"])),
                    ]
                )
            res_rows.append(
                [
                    "TOTAL",
                    totales["n_pedidos"],
                    str(q2(totales["costo"])),
                    str(q2(totales["neto"])),
                    str(q2(totales["ganancia"])),
                ]
            )
            return xlsx_response(
                "ganancia_pedidos",
                [
                    ("Detalle", h_x, rows_x),
                    ("Resumen mensual", res_h, res_rows),
                ],
            )

        sections: list[tuple[str, list[str], list[list[object]]]] = []
        for mes in meses_detalle:
            rows_m: list[list[object]] = []
            for fila in mes["filas"]:
                v = fila["venta"]
                rows_m.append(
                    [
                        v.pk,
                        timezone.localtime(v.creado_en).strftime("%d/%m/%Y %H:%M"),
                        str(v.vendedor),
                        str(v.comprador) if v.comprador_id else "",
                        v.get_estado_display(),
                        str(q2(fila["costo_mercaderia"])),
                        str(q2(fila["neto"])),
                        str(q2(fila["ganancia"])),
                    ]
                )
            sections.append((str(mes["label"]), headers, rows_m))
        res_h2 = ["Mes calendario", "Pedidos", "Costo mercadería", "Neto", "Ganancia"]
        res_rows2: list[list[object]] = []
        for mes in meses_detalle:
            res_rows2.append(
                [
                    mes["label"],
                    str(mes["n_pedidos"]),
                    str(q2(mes["total_mes_costo"])),
                    str(q2(mes["total_mes_neto"])),
                    str(q2(mes["total_mes_ganancia"])),
                ]
            )
        res_rows2.append(
            [
                "TOTAL",
                str(totales["n_pedidos"]),
                str(q2(totales["costo"])),
                str(q2(totales["neto"])),
                str(q2(totales["ganancia"])),
            ]
        )
        sections.append(("Resumen por mes", res_h2, res_rows2))
        return pdf_response(
            "ganancia_pedidos",
            "Ganancia por pedido",
            sections,
            body_fontsize=8,
        )

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
            "Comisión en pedido",
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
                    "Sí" if v.comision_descontada_en_pedido else "No",
                    str(v.comision_porcentaje),
                    str(q2(v.monto_comision)),
                    str(q2(v.monto_ingreso_caja)),
                    v.get_estado_display(),
                ]
            )
        if exp == "xlsx":
            return xlsx_response("ventas", [("Ventas", headers, rows)])
        return pdf_response("ventas", "Historial de ventas", [("Ventas", headers, rows)])

    meses_ganancia: list[dict[str, object]] = []
    totales_ganancia: dict[str, object] | None = None
    page_obj = None
    ventas_page: list[Venta] = []

    if pestana == "ganancia":
        ventas_g = list(
            ventas.order_by("-creado_en", "-id").prefetch_related(
                Prefetch("lineas", queryset=VentaLinea.objects.select_related("producto"))
            )
        )
        meses_ganancia, totales_ganancia = _historial_ganancia_meses_desde_ventas(ventas_g)
    else:
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
            "meses_ganancia": meses_ganancia,
            "totales_ganancia": totales_ganancia,
            "filtros": filtros_ctx,
            "productos_filtro": productos,
            "vendedores_filtro": vendedores,
            "compradores_filtro": compradores,
            "page_obj": page_obj,
            "querystring": querystring,
            "n_ventas_a_pagar": n_ventas_a_pagar,
            "n_ventas_pagos": n_ventas_pagos,
            "n_ventas_ganancia": n_ventas_ganancia,
            "querystring_a_pagar": _venta_historial_querystring_pestana(request, "a_pagar"),
            "querystring_pagos": _venta_historial_querystring_pestana(request, "pagos"),
            "querystring_ganancia": _venta_historial_querystring_pestana(request, "ganancia"),
        },
    )


@login_required
@require_http_methods(["POST"])
def venta_eliminar(request, pk: int):
    if not is_staff_user(request.user):
        messages.error(request, "Solo administradores (staff) pueden eliminar pedidos.")
        return redirect("ventas_historial")

    def _redirect_despues():
        next_url = (request.POST.get("next") or "").strip()
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect("ventas_historial")

    venta = get_object_or_404(Venta, pk=pk)
    if venta.despacho_despachado:
        messages.error(
            request,
            f"El pedido #{venta.pk} está archivado (despachado) y no se puede eliminar desde acá.",
        )
        return _redirect_despues()
    nid = venta.pk
    try:
        eliminar_venta_admin(venta)
    except ValidationError as exc:
        messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        return _redirect_despues()
    except IntegrityError as exc:
        detalle = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
        messages.error(
            request,
            "No se pudo eliminar el pedido porque tiene datos vinculados en el sistema." + detalle,
        )
        return _redirect_despues()
    except Exception as exc:
        detalle = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
        messages.error(request, "No se pudo eliminar el pedido." + detalle)
        return _redirect_despues()
    messages.success(request, f"Pedido #{nid} eliminado (stock y caja/calendario revertidos si correspondía).")
    return _redirect_despues()


@login_required
@xframe_options_sameorigin
def venta_detalle(request, pk: int):
    venta = get_object_or_404(_venta_detalle_queryset(), pk=pk)
    if parse_export(request) == "pdf":
        resp = remito_venta_pdf_response(venta)
        if (request.GET.get("inline") or "").strip() == "1":
            try:
                cd = resp.get("Content-Disposition", "")
                if cd:
                    resp["Content-Disposition"] = cd.replace("attachment", "inline", 1)
            except Exception:
                pass
        return resp
    return render(
        request,
        "ventas/detalle.html",
        {
            "venta": venta,
        },
    )


@staff_required
@require_http_methods(["POST"])
def venta_producto_listas_precio(request, pk: int, producto_pk: int):
    """Desde la ficha del pedido: Farmacia (PDF) y listas de rubro según POST (no se fuerza Farmacia)."""
    venta = get_object_or_404(Venta, pk=pk)
    if not VentaLinea.objects.filter(venta_id=venta.pk, producto_id=producto_pk).exists():
        messages.error(request, "Este producto no forma parte del pedido.")
        return redirect("venta_detalle", pk=pk)
    producto = get_object_or_404(Producto, pk=producto_pk)
    if request.POST.get("listas_extra_present") != "1":
        messages.error(request, "Solicitud inválida.")
        return redirect("venta_detalle", pk=pk)
    en_farmacia = request.POST.get("en_lista_farmacia") == "1"
    with transaction.atomic():
        producto.en_lista_precios = en_farmacia
        producto.save(update_fields=["en_lista_precios"])
        sync_producto_listas_extras_from_post(request, producto)
    if en_farmacia:
        msg = f"Listas actualizadas para {producto.codigo}: Farmacia (PDF) activada; rubros según lo marcado."
    else:
        msg = f"Listas actualizadas para {producto.codigo}: Farmacia (PDF) desactivada; rubros según lo marcado."
    messages.success(request, msg)
    return redirect("venta_detalle", pk=pk)


@login_required
@require_http_methods(["GET", "POST"])
def venta_editar(request, pk: int):
    venta = get_object_or_404(Venta.objects.select_related("vendedor", "comprador"), pk=pk)
    if venta.despacho_despachado:
        return render(
            request,
            "ventas/editar_bloqueado.html",
            {
                "venta": venta,
                "motivo": "despachado",
            },
        )
    pedido_pagado = venta.estado == Venta.Estado.PAGADA
    if venta.estado not in (Venta.Estado.PENDIENTE, Venta.Estado.PAGADA):
        return render(request, "ventas/editar_bloqueado.html", {"venta": venta})

    vendedores = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    compradores = Comprador.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")

    lineas_qs = list(venta.lineas.select_related("producto").all())
    lineas_iniciales = [
        {
            "producto_id": ln.producto_id,
            "cantidad": ln.cantidad,
            "precio_unitario": str(ln.precio_unitario),
            "codigo": ln.texto_codigo,
            "descripcion": ln.texto_descripcion,
            "stock": int(getattr(ln.producto, "stock", 0) or 0) if ln.producto_id else 0,
        }
        for ln in lineas_qs
    ]
    productos_catalogo = productos_payload_para_lineas(lineas_iniciales)
    repoblar = {
        "vendedor_id": venta.vendedor_id,
        "comprador_id": venta.comprador_id,
        "fecha_vencimiento_pago": venta.fecha_vencimiento_pago.strftime("%Y-%m-%d")
        if venta.fecha_vencimiento_pago
        else "",
        "descuento_monto": str(venta.descuento_monto or 0),
        "comision_porcentaje": str(venta.comision_porcentaje or 0),
        "aplica_comision": bool(venta.aplica_comision),
    }

    if request.method == "POST":
        if venta.comision_liquidacion_pago_id:
            messages.error(
                request,
                "Este pedido ya está incluido en una liquidación de comisión pagada; no se puede editar desde acá.",
            )
            return redirect("venta_detalle", pk=venta.pk)
        # Validación completa (similar a presupuestos): comprador opcional, vencimiento opcional, líneas editables.
        err = None
        vid_raw = (request.POST.get("vendedor") or "").strip()
        if not vid_raw.isdigit():
            err = "Elegí un vendedor."
            vid = None
        else:
            vid = int(vid_raw)
            v_ok = Vendedor.objects.filter(pk=vid, habilitado=True).exists()
            if not v_ok and vid == venta.vendedor_id and Vendedor.objects.filter(pk=vid).exists():
                v_ok = True
            if not v_ok:
                err = "El vendedor seleccionado no existe o no está habilitado."

        cid_raw = (request.POST.get("comprador") or "").strip()
        comprador_id = None
        if err is None and cid_raw:
            if not cid_raw.isdigit():
                err = "Comprador no válido."
            else:
                comprador_id = int(cid_raw)
                if not Comprador.objects.filter(pk=comprador_id).exists():
                    err = "El comprador seleccionado no existe."

        fecha_v = parse_fecha_param(request.POST.get("fecha_vencimiento_pago") or "")
        raw_desc = (request.POST.get("descuento_monto") or "").strip()
        try:
            descuento = parse_decimal_from_input(raw_desc) if raw_desc else Decimal("0")
        except InvalidOperation:
            descuento = None
        raw_com = (request.POST.get("comision_porcentaje") or "").strip()
        try:
            comision_pct = parse_decimal_from_input(raw_com) if raw_com else Decimal("0")
        except InvalidOperation:
            comision_pct = None
        aplica_comision = request.POST.get("aplica_comision") == "1"

        if err is None and (descuento is None or descuento < 0):
            err = "El descuento no es válido."
        if err is None and (comision_pct is None or comision_pct < 0):
            err = "El porcentaje de comisión no es válido."

        solo_cab = request.POST.get("accion") == "solo_cabecera"
        if solo_cab and err is None:
            ref_sub = venta.subtotal_lineas or Decimal("0")
            if descuento is not None and descuento > ref_sub:
                err = "El descuento no puede superar el subtotal actual de líneas."
            elif descuento is not None and q2(ref_sub - descuento + (venta.envio or Decimal("0"))) < 0:
                err = "El descuento no puede superar el subtotal de las líneas actuales."

        if solo_cab:
            if err is not None:
                messages.error(request, err)
                repoblar = repoblar_campos_cabecera_desde_post(request)
                lineas_iniciales = lineas_iniciales_desde_post(request)
                productos_catalogo = productos_payload_para_lineas(lineas_iniciales)
                return render(
                    request,
                    "ventas/editar.html",
                    {
                        "venta": venta,
                        "vendedores": vendedores,
                        "compradores": compradores,
                        "productos_catalogo": productos_catalogo,
                        "lineas_iniciales": lineas_iniciales,
                        "repoblar": repoblar,
                        "comision_default": COMISION_PORCENTAJE_DEFECTO,
                        "pedido_pagado": pedido_pagado,
                    },
                )
            try:
                with transaction.atomic():
                    v_locked = Venta.objects.select_for_update().get(pk=venta.pk)
                    v_locked.vendedor_id = vid
                    v_locked.comprador_id = comprador_id
                    v_locked.fecha_vencimiento_pago = fecha_v
                    v_locked.descuento_monto = descuento or Decimal("0")
                    v_locked.comision_porcentaje = comision_pct or Decimal("0")
                    v_locked.aplica_comision = aplica_comision
                    v_locked.actualizado_por = request.user
                    v_locked.save(
                        update_fields=[
                            "vendedor",
                            "comprador",
                            "fecha_vencimiento_pago",
                            "descuento_monto",
                            "comision_porcentaje",
                            "aplica_comision",
                            "actualizado_por",
                        ]
                    )
                    sync_evento_pedido_pendiente(v_locked)
                messages.success(request, "Se actualizó cabecera y comisión (sin modificar productos ni stock).")
                return redirect("venta_detalle", pk=venta.pk)
            except Exception as exc:
                det = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
                messages.error(request, "No se pudo guardar." + det)
                repoblar = repoblar_campos_cabecera_desde_post(request)
                lineas_iniciales = lineas_iniciales_desde_post(request)
                productos_catalogo = productos_payload_para_lineas(lineas_iniciales)
                return render(
                    request,
                    "ventas/editar.html",
                    {
                        "venta": venta,
                        "vendedores": vendedores,
                        "compradores": compradores,
                        "productos_catalogo": productos_catalogo,
                        "lineas_iniciales": lineas_iniciales,
                        "repoblar": repoblar,
                        "comision_default": COMISION_PORCENTAJE_DEFECTO,
                        "pedido_pagado": pedido_pagado,
                    },
                )

        pids = request.POST.getlist("linea_producto")
        qtys = request.POST.getlist("linea_cantidad")
        precios_raw = request.POST.getlist("linea_precio_unitario")

        line_specs = []
        subtotal = Decimal("0.00")
        if err is None:
            for pid_s, qraw, praw in zip_longest(pids, qtys, precios_raw, fillvalue=""):
                pid_s = (pid_s or "").strip()
                qraw = (qraw or "").strip()
                praw = (praw or "").strip()
                if not pid_s and not qraw and not praw:
                    continue
                if not pid_s:
                    err = "Hay una línea sin producto (elegí el producto o borrá la fila vacía)."
                    break
                if not qraw:
                    err = "Indicá la cantidad en cada línea con producto."
                    break
                try:
                    qty = int(qraw)
                except ValueError:
                    err = "Las cantidades deben ser números enteros."
                    break
                if qty <= 0:
                    err = "La cantidad debe ser mayor a cero."
                    break
                if not pid_s.isdigit():
                    err = "Producto no válido."
                    break
                prod_id = int(pid_s)
                if pedido_pagado:
                    prod = Producto.objects.filter(pk=prod_id).first()
                    if prod is None:
                        err = "Un producto seleccionado no existe."
                        break
                else:
                    prod = Producto.objects.filter(pk=prod_id, habilitado=True).first()
                    if prod is None:
                        err = "Un producto seleccionado no existe o está deshabilitado."
                        break
                if praw:
                    try:
                        pu = q2(parse_decimal_from_input(praw))
                    except InvalidOperation:
                        err = f"El precio unitario no es válido en la línea de {prod.codigo}."
                        break
                else:
                    pu = q2(prod.precio_venta)
                if pu <= 0:
                    err = f"El precio unitario debe ser mayor a cero ({prod.codigo})."
                    break
                st = (pu * qty).quantize(Decimal("0.01"))
                subtotal += st
                line_specs.append((prod, qty, pu, st, prod.codigo, prod.descripcion))

        if err is None and not line_specs:
            err = "Agregá al menos un producto."
        if err is None and descuento > subtotal:
            err = "El descuento no puede superar el subtotal de las líneas."

        stock_conf = None
        if err is None and not pedido_pagado:
            try:
                stock_conf = parse_stock_venta_json_from_post(request.POST)
            except ValidationError as exc:
                err = "; ".join(getattr(exc, "messages", [str(exc)]))

        if err is None:
            try:
                with transaction.atomic():
                    v_locked = Venta.objects.select_for_update().prefetch_related("lineas").get(pk=venta.pk)
                    if pedido_pagado:
                        VentaLinea.objects.filter(venta_id=v_locked.pk).delete()
                        for spec in line_specs:
                            prod, qty, pu, st, cod, desc = spec
                            VentaLinea.objects.create(
                                venta=v_locked,
                                producto=prod,
                                cantidad=qty,
                                precio_unitario=pu,
                                subtotal=st,
                                codigo_snapshot=(cod or "")[:6],
                                descripcion_snapshot=(desc or "")[:255],
                            )
                    else:
                        old_lines = list(v_locked.lineas.all())
                        for ln in old_lines:
                            Producto.objects.filter(pk=ln.producto_id).update(stock=F("stock") + ln.cantidad)
                        VentaLinea.objects.filter(venta_id=v_locked.pk).delete()
                        pids_edit = [int(spec[0].pk) for spec in line_specs]
                        prev_snap_edit = snapshot_stock(pids_edit)
                        merged = merge_stock_confirmacion_venta_locked(line_specs, stock_conf)
                        for spec in line_specs:
                            prod, qty, pu, st, cod, desc = spec
                            VentaLinea.objects.create(
                                venta=v_locked,
                                producto=prod,
                                cantidad=qty,
                                precio_unitario=pu,
                                subtotal=st,
                                codigo_snapshot=(cod or "")[:6],
                                descripcion_snapshot=(desc or "")[:255],
                            )
                            Producto.objects.filter(pk=prod.pk).update(stock=F("stock") - qty)
                        Producto.aplicar_deshabilitado_si_queda_en_cero(merged)
                        if not stock_conf:
                            nuevos_cero = ids_que_quedaron_en_cero(prev_snap_edit, pids_edit)
                            if nuevos_cero:
                                encolar_prompt_stock_cero(request, nuevos_cero)

                    v_locked.vendedor_id = vid
                    v_locked.comprador_id = comprador_id
                    v_locked.fecha_vencimiento_pago = fecha_v
                    v_locked.subtotal_lineas = subtotal
                    v_locked.descuento_monto = descuento
                    v_locked.comision_porcentaje = comision_pct
                    v_locked.aplica_comision = aplica_comision
                    v_locked.actualizado_por = request.user
                    v_locked.save(
                        update_fields=[
                            "vendedor",
                            "comprador",
                            "fecha_vencimiento_pago",
                            "subtotal_lineas",
                            "descuento_monto",
                            "comision_porcentaje",
                            "aplica_comision",
                            "actualizado_por",
                        ]
                    )
                    sync_evento_pedido_pendiente(v_locked)
                messages.success(
                    request,
                    "Pedido actualizado (pedido ya cobrado: solo se ajustó el registro, el stock no se modificó)."
                    if pedido_pagado
                    else "Pedido actualizado.",
                )
                return redirect("venta_detalle", pk=venta.pk)
            except ValidationError as exc:
                messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
            except Exception as exc:
                det = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
                messages.error(request, "No se pudo actualizar el pedido." + det)
        else:
            messages.error(request, err)
            lineas_iniciales = lineas_iniciales_desde_post(request)
            repoblar = repoblar_campos_cabecera_desde_post(request)

    productos_catalogo = productos_payload_para_lineas(lineas_iniciales)

    return render(
        request,
        "ventas/editar.html",
        {
            "venta": venta,
            "vendedores": vendedores,
            "compradores": compradores,
            "productos_catalogo": productos_catalogo,
            "lineas_iniciales": lineas_iniciales,
            "repoblar": repoblar,
            "comision_default": COMISION_PORCENTAJE_DEFECTO,
            "pedido_pagado": pedido_pagado,
        },
    )


@login_required
@require_http_methods(["POST"])
def venta_actualizar_comision(request, pk: int):
    """Actualiza solo comisión (5% fijo si aplica) sin revalidar líneas; útil desde el historial."""
    venta = get_object_or_404(Venta, pk=pk)
    next_url = (request.POST.get("next") or "").strip()

    def _redirect_response():
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect("ventas_historial")

    if venta.comision_liquidacion_pago_id:
        messages.warning(
            request,
            "No se puede cambiar la comisión: este pedido ya figura en una liquidación de comisión pagada.",
        )
        return _redirect_response()

    if venta.estado not in (Venta.Estado.PENDIENTE, Venta.Estado.PAGADA):
        messages.warning(request, "Solo se puede cambiar la comisión en pedidos pendientes o ya cobrados.")
        return _redirect_response()

    aplica = request.POST.get("aplica_comision") == "1"
    descontar = request.POST.get("comision_descontada_en_pedido") == "1" and aplica
    venta.aplica_comision = aplica
    venta.comision_descontada_en_pedido = descontar
    if aplica:
        venta.comision_porcentaje = COMISION_PORCENTAJE_DEFECTO
    else:
        venta.comision_descontada_en_pedido = False
    venta.actualizado_por = request.user
    venta.save(
        update_fields=[
            "aplica_comision",
            "comision_descontada_en_pedido",
            "comision_porcentaje",
            "actualizado_por",
        ]
    )
    if venta.estado == Venta.Estado.PAGADA and venta.pago_movimiento_id:
        mov = venta.pago_movimiento
        nuevo_monto = venta.monto_ingreso_caja
        if mov.monto != nuevo_monto:
            mov.monto = nuevo_monto
            mov.actualizado_por = request.user
            mov.save(update_fields=["monto", "actualizado_por"])
    sync_evento_pedido_pendiente(venta)
    if aplica and descontar:
        msg = "Comisión activa: se descontará del monto a cobrar en caja."
    elif aplica:
        msg = "Comisión del vendedor activada (5% sobre el neto)."
    else:
        msg = "Comisión del vendedor desactivada."
    messages.success(request, msg)
    return _redirect_response()


@login_required
@require_http_methods(["GET", "POST"])
def venta_registrar_pago(request, pk: int):
    venta = get_object_or_404(
        Venta.objects.select_related("vendedor", "comprador", "pago_movimiento")
        .prefetch_related(
            Prefetch("lineas", queryset=VentaLinea.objects.select_related("producto"))
        ),
        pk=pk,
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
                venta_aplicar_snapshot_ganancia_cobro(venta)
                venta.save(
                    update_fields=[
                        "estado",
                        "pago_movimiento",
                        "actualizado_por",
                        "neto_cobro",
                        "costo_mercaderia_cobro",
                        "ganancia_cobro",
                    ]
                )
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


@login_required
@require_http_methods(["GET"])
def despachos_lista(request):
    qs = ventas_despachos_activos_queryset()
    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(qs, 120)
    page_obj = paginator.get_page(page or 1)
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    return render(
        request,
        "ventas/despachos.html",
        {
            "ventas": list(page_obj),
            "page_obj": page_obj,
            "querystring": qcopy.urlencode(),
            "historial_despachos": False,
            "despacho_historial_dias": DESPACHO_HISTORIAL_DIAS,
        },
    )


@login_required
@require_http_methods(["GET"])
def despachos_historial(request):
    qs = ventas_despachos_historial_queryset()
    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(qs, 120)
    page_obj = paginator.get_page(page or 1)
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    return render(
        request,
        "ventas/despachos.html",
        {
            "ventas": list(page_obj),
            "page_obj": page_obj,
            "querystring": qcopy.urlencode(),
            "historial_despachos": True,
            "despacho_historial_dias": DESPACHO_HISTORIAL_DIAS,
        },
    )


@login_required
@require_http_methods(["POST"])
def venta_actualizar_despacho(request, pk: int):
    venta = get_object_or_404(Venta, pk=pk)
    next_url = (request.POST.get("next") or "").strip()
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _redirect_response():
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect("despachos_lista")

    estado_clave = (request.POST.get("estado") or "").strip()
    if estado_clave:
        if not venta.set_estado_despacho_clave(estado_clave):
            if ajax:
                return JsonResponse({"error": "Estado no válido"}, status=400)
            messages.error(request, "Estado de despacho no válido.")
            return _redirect_response()
    else:
        armado = request.POST.get("despacho_armado") == "1"
        despachado = request.POST.get("despacho_despachado") == "1"
        venta.aplicar_estado_despacho(armado=armado, despachado=despachado)

    venta.actualizado_por = request.user
    venta.save(
        update_fields=[
            "despacho_armado",
            "despacho_despachado",
            "despacho_despachado_en",
            "actualizado_por",
            "actualizado_en",
        ]
    )
    if venta.despacho_despachado:
        archivar_lineas_pedido_despachado(venta)
    if ajax:
        return JsonResponse(venta_despacho_json_payload(venta))
    return _redirect_response()
