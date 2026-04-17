from decimal import Decimal, InvalidOperation
from itertools import zip_longest

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from core.export_utils import parse_export
from core.money_decimal import COMISION_PORCENTAJE_DEFECTO, format_monto_ars, parse_decimal_from_input
from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_param, parse_fecha_dashboard, rango_periodo
from core.repoblar_lineas import repoblar_campos_cabecera_desde_post
from personas.models import Comprador, Vendedor
from productos.models import Producto
from ventas.servicios import crear_venta_confirmada, eliminar_venta_admin
from ventas.models import Venta, VentaLinea
from calendario.models import Evento


def _es_staff(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))

from .models import Presupuesto, PresupuestoLinea


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


def _lineas_presupuesto_desde_post(request) -> list[dict]:
    """
    Repuebla líneas tras error de validación: conserva producto, cantidad y precio tal como los envió el usuario
    (incluye filas incompletas o cantidades/precios inválidos para que pueda corregir solo eso).
    """
    pids = request.POST.getlist("linea_producto")
    qtys = request.POST.getlist("linea_cantidad")
    precios = request.POST.getlist("linea_precio_unitario")
    out: list[dict] = []
    for pid, qraw, praw in zip_longest(pids, qtys, precios, fillvalue=""):
        ps = (pid or "").strip()
        qs = (qraw or "").strip()
        pc = (praw or "").strip()
        if not ps and not qs and not pc:
            continue
        row: dict = {"cantidad_raw": qs}
        if ps.isdigit():
            row["producto_id"] = int(ps)
        if pc:
            row["precio_unitario"] = pc
        out.append(row)
    return out


def _validar_lineas_post(request):
    """Valida POST de líneas (igual que venta). Devuelve (error_msg|None, line_specs, subtotal, extras)."""
    vid = request.POST.get("vendedor")
    fecha_v = parse_fecha_param(request.POST.get("fecha_vencimiento_pago") or "")
    raw_desc = (request.POST.get("descuento_monto") or "").strip()
    try:
        descuento = (
            parse_decimal_from_input(raw_desc) if raw_desc else Decimal("0")
        )
    except InvalidOperation:
        descuento = None

    pids = request.POST.getlist("linea_producto")
    qtys = request.POST.getlist("linea_cantidad")
    precios_raw = request.POST.getlist("linea_precio_unitario")

    cid_raw = (request.POST.get("comprador") or "").strip()
    comprador_id = None
    if cid_raw:
        try:
            comprador_id = int(cid_raw)
            if not Comprador.objects.filter(pk=comprador_id).exists():
                return "El comprador seleccionado no existe.", None, None, None
        except ValueError:
            return "Comprador no válido.", None, None, None

    if not vid:
        return "Elegí un vendedor.", None, None, None
    if descuento is None or descuento < 0:
        return "El descuento no es válido.", None, None, None

    try:
        Vendedor.objects.get(pk=int(vid), habilitado=True)
    except (ValueError, Vendedor.DoesNotExist):
        return "El vendedor seleccionado no existe o no está habilitado.", None, None, None
    raw_com = (request.POST.get("comision_porcentaje") or "").strip()
    try:
        comision_pct = parse_decimal_from_input(raw_com) if raw_com else COMISION_PORCENTAJE_DEFECTO
    except InvalidOperation:
        comision_pct = None
    if comision_pct is None or comision_pct < 0:
        return "El porcentaje de comisión no es válido.", None, None, None

    line_specs = []
    subtotal = Decimal("0.00")
    err = None
    for pid, qraw, praw in zip_longest(pids, qtys, precios_raw, fillvalue=""):
        pid = (pid or "").strip()
        qraw = (qraw or "").strip()
        praw_s = (praw or "").strip()
        if not pid and not qraw and not praw_s:
            continue
        if not pid:
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
        try:
            prod = Producto.objects.get(pk=int(pid), habilitado=True)
        except (ValueError, Producto.DoesNotExist):
            err = "Un producto seleccionado no existe o está deshabilitado."
            break
        if prod.stock < qty:
            err = f"Stock insuficiente para {prod.codigo} (disponible: {prod.stock})."
            break
        raw_pu = praw_s
        if raw_pu:
            try:
                pu = parse_decimal_from_input(raw_pu)
            except InvalidOperation:
                err = f"El precio unitario no es válido en la línea de {prod.codigo}."
                break
        else:
            pu = prod.precio_venta
        if pu <= 0:
            err = f"El precio unitario debe ser mayor a cero ({prod.codigo})."
            break
        st = (pu * qty).quantize(Decimal("0.01"))
        subtotal += st
        line_specs.append((prod, qty, pu, st))

    if err:
        return err, None, None, None
    if not line_specs:
        return "Agregá al menos un producto.", None, None, None
    if descuento > subtotal:
        return "El descuento no puede superar el subtotal de las líneas.", None, None, None

    aplica_comision = request.POST.get("aplica_comision", "1") == "1"
    return None, line_specs, subtotal, (
        int(vid),
        fecha_v,
        descuento,
        comision_pct,
        comprador_id,
        aplica_comision,
    )


def _guardar_presupuesto_desde_lineas(
    presupuesto,
    line_specs,
    subtotal,
    vid,
    fecha_v,
    descuento,
    comision_pct,
    comprador_id=None,
    aplica_comision: bool = True,
):
    presupuesto.vendedor_id = vid
    presupuesto.comprador_id = comprador_id
    presupuesto.fecha_vencimiento_pago = fecha_v
    presupuesto.subtotal_lineas = subtotal
    presupuesto.descuento_monto = descuento
    presupuesto.comision_porcentaje = comision_pct
    presupuesto.aplica_comision = aplica_comision
    presupuesto.save()
    presupuesto.lineas.all().delete()
    for prod, qty, pu, st in line_specs:
        PresupuestoLinea.objects.create(
            presupuesto=presupuesto,
            producto=prod,
            cantidad=qty,
            precio_unitario=pu,
            subtotal=st,
        )


def _filtrar_presupuestos_queryset(request):
    periodo = (request.GET.get("periodo") or "").strip()
    if periodo in ("7d", "30d", "mes", "mes_ant"):
        fecha_desde, fecha_hasta = rango_periodo(periodo)
    else:
        fecha_desde = parse_fecha_dashboard(request.GET.get("fecha_desde"))
        fecha_hasta = parse_fecha_dashboard(request.GET.get("fecha_hasta"))

    qs = (
        Presupuesto.objects.select_related("vendedor", "venta", "comprador")
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

    return qs, {
        "periodo": periodo,
        "fecha_desde": fecha_filtro_value_iso(request.GET.get("fecha_desde")),
        "fecha_hasta": fecha_filtro_value_iso(request.GET.get("fecha_hasta")),
        "vendedor": vid,
        "comprador": cid,
    }


@login_required
def presupuesto_lista(request):
    items, filtros_ctx = _filtrar_presupuestos_queryset(request)
    compradores = Comprador.objects.order_by("apellido", "nombre", "codigo")
    vendedores = Vendedor.objects.order_by("apellido", "nombre", "codigo")
    return render(
        request,
        "presupuestos/lista.html",
        {
            "presupuestos": items,
            "filtros": filtros_ctx,
            "compradores_filtro": compradores,
            "vendedores_filtro": vendedores,
        },
    )


@login_required
def presupuesto_detalle(request, pk: int):
    p = get_object_or_404(
        Presupuesto.objects.select_related(
            "vendedor",
            "comprador",
            "venta",
            "venta__pago_movimiento",
            "venta__pago_movimiento__creado_por",
        ).prefetch_related("lineas__producto"),
        pk=pk,
    )
    if parse_export(request) == "pdf":
        return presupuesto_pdf_response(p)
    return render(request, "presupuestos/detalle.html", {"presupuesto": p})


@login_required
@require_http_methods(["GET", "POST"])
def presupuesto_nuevo(request):
    vendedores = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    productos_catalogo = _productos_payload()
    lineas_iniciales: list = []
    repoblar = None

    if request.method == "POST":
        err, line_specs, subtotal, meta = _validar_lineas_post(request)
        if err is None:
            vid, fecha_v, descuento, comision_pct, comprador_id, aplica_comision = meta
            with transaction.atomic():
                pr = Presupuesto.objects.create(
                    vendedor_id=vid,
                    comprador_id=comprador_id,
                    fecha_vencimiento_pago=fecha_v,
                    subtotal_lineas=subtotal,
                    descuento_monto=descuento,
                    comision_porcentaje=comision_pct,
                    aplica_comision=aplica_comision,
                    creado_por=request.user,
                    actualizado_por=request.user,
                )
                for prod, qty, pu, st in line_specs:
                    PresupuestoLinea.objects.create(
                        presupuesto=pr,
                        producto=prod,
                        cantidad=qty,
                        precio_unitario=pu,
                        subtotal=st,
                    )
            messages.success(request, f"Presupuesto #{pr.pk} guardado.")
            return redirect("presupuesto_lista")
        messages.error(request, err)
        lineas_iniciales = _lineas_presupuesto_desde_post(request)
        repoblar = repoblar_campos_cabecera_desde_post(request)

    return render(
        request,
        "presupuestos/form.html",
        {
            "modo": "nuevo",
            "vendedores": vendedores,
            "compradores": Comprador.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo"),
            "productos_catalogo": productos_catalogo,
            "presupuesto": None,
            "lineas_iniciales": lineas_iniciales,
            "repoblar": repoblar,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def presupuesto_editar(request, pk: int):
    presupuesto = get_object_or_404(Presupuesto, pk=pk)
    es_admin = _es_staff(request.user)
    if presupuesto.estado != Presupuesto.Estado.ACTIVO and not es_admin:
        messages.warning(request, "Solo administradores pueden editar presupuestos aprobados.")
        return redirect("presupuesto_lista")

    vendedores = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    productos_catalogo = _productos_payload()
    lineas_iniciales = [
        {
            "producto_id": ln.producto_id,
            "cantidad": ln.cantidad,
            "precio_unitario": str(ln.precio_unitario),
        }
        for ln in presupuesto.lineas.all()
    ]
    repoblar = None

    if request.method == "POST":
        err, line_specs, subtotal, meta = _validar_lineas_post(request)
        if err is None:
            vid, fecha_v, descuento, comision_pct, comprador_id, aplica_comision = meta
            with transaction.atomic():
                _guardar_presupuesto_desde_lineas(
                    presupuesto,
                    line_specs,
                    subtotal,
                    vid,
                    fecha_v,
                    descuento,
                    comision_pct,
                    comprador_id,
                    aplica_comision,
                )
                # Si ya estaba aprobado y tiene pedido generado, reflejar cambios en la Venta
                # (solo si sigue pendiente de pago; si está pagada no se toca para no romper caja).
                if presupuesto.estado == Presupuesto.Estado.APROBADO and presupuesto.venta_id:
                    qs = Venta.objects
                    try:
                        qs = qs.select_for_update(of=("self",))
                    except TypeError:
                        qs = qs.select_for_update()
                    venta = (
                        qs.prefetch_related("lineas")
                        .get(pk=presupuesto.venta_id)
                    )
                    if venta.estado == Venta.Estado.PAGADA or venta.pago_movimiento_id:
                        raise ValueError(
                            "El pedido generado ya está pagado; no se puede editar el presupuesto aprobado porque impacta caja."
                        )
                    # Revertir stock por líneas viejas, rearmar líneas y descontar stock nuevo.
                    old_lines = list(venta.lineas.all())
                    for ln in old_lines:
                        Producto.objects.filter(pk=ln.producto_id).update(stock=F("stock") + ln.cantidad)
                    VentaLinea.objects.filter(venta_id=venta.pk).delete()

                    pids_afectados: list[int] = []
                    for prod, qty, pu, st in line_specs:
                        VentaLinea.objects.create(
                            venta=venta,
                            producto=prod,
                            cantidad=qty,
                            precio_unitario=pu,
                            subtotal=st,
                        )
                        Producto.objects.filter(pk=prod.pk).update(stock=F("stock") - qty)
                        pids_afectados.append(prod.pk)
                    Producto.deshabilitar_sin_stock(pids_afectados)

                    venta.vendedor_id = vid
                    venta.comprador_id = comprador_id
                    venta.fecha_vencimiento_pago = fecha_v
                    venta.subtotal_lineas = subtotal
                    venta.descuento_monto = descuento
                    venta.comision_porcentaje = comision_pct
                    venta.aplica_comision = aplica_comision
                    venta.actualizado_por = request.user
                    venta.save(
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
                    # Sincronizar evento de calendario del pedido pendiente (mismo título).
                    Evento.objects.filter(
                        tipo=Evento.Tipo.PEDIDO,
                        titulo=f"Pago pendiente — Pedido #{venta.pk}",
                    ).delete()
                    if venta.fecha_vencimiento_pago is not None:
                        extra_comprador = (
                            f" Comprador: {venta.comprador}." if venta.comprador_id else ""
                        )
                        com_txt = (
                            f"Comisión ({venta.comision_porcentaje}%): {format_monto_ars(venta.monto_comision)}. "
                            if venta.aplica_comision
                            else "Sin comisión al vendedor. "
                        )
                        Evento.objects.create(
                            fecha=venta.fecha_vencimiento_pago,
                            titulo=f"Pago pendiente — Pedido #{venta.pk}",
                            tipo=Evento.Tipo.PEDIDO,
                            descripcion=(
                                f"Vendedor: {venta.vendedor}. "
                                f"Monto neto pedido: {format_monto_ars(venta.neto)}. "
                                f"{com_txt}"
                                f"Ingreso en caja al cobrar: {format_monto_ars(venta.monto_ingreso_caja)}.{extra_comprador}"
                            ),
                        )
                presupuesto.actualizado_por = request.user
                presupuesto.save(update_fields=["actualizado_por"])
            messages.success(request, "Presupuesto actualizado.")
            return redirect("presupuesto_lista")
        messages.error(request, err)
        lineas_iniciales = _lineas_presupuesto_desde_post(request)
        repoblar = repoblar_campos_cabecera_desde_post(request)

    return render(
        request,
        "presupuestos/form.html",
        {
            "modo": "editar",
            "vendedores": vendedores,
            "compradores": Comprador.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo"),
            "productos_catalogo": productos_catalogo,
            "presupuesto": presupuesto,
            "lineas_iniciales": lineas_iniciales,
            "repoblar": repoblar,
        },
    )


@login_required
@require_http_methods(["POST"])
def presupuesto_eliminar(request, pk: int):
    presupuesto = get_object_or_404(Presupuesto, pk=pk)
    es_admin = _es_staff(request.user)
    if presupuesto.estado != Presupuesto.Estado.ACTIVO and not es_admin:
        messages.warning(
            request,
            "No se puede eliminar un presupuesto ya aprobado (solo administradores).",
        )
        return redirect("presupuesto_lista")
    nid = presupuesto.pk
    try:
        with transaction.atomic():
            # En Postgres, `FOR UPDATE` puede fallar si la query incorpora LEFT OUTER JOIN
            # (p. ej. por relaciones nulas). Lockeamos solo la tabla de Presupuesto.
            qs = Presupuesto.objects
            try:
                qs = qs.select_for_update(of=("self",))
            except TypeError:
                qs = qs.select_for_update()
            pr = qs.get(pk=presupuesto.pk)
            if pr.venta_id:
                eliminar_venta_admin(pr.venta)
            pr.delete()
    except Exception as exc:
        messages.error(request, f"No se pudo eliminar el presupuesto: {exc}")
        return redirect("presupuesto_lista")
    messages.success(request, f"Presupuesto #{nid} eliminado.")
    return redirect("presupuesto_lista")


@login_required
@require_http_methods(["POST"])
def presupuesto_aprobar(request, pk: int):
    presupuesto = get_object_or_404(
        Presupuesto.objects.prefetch_related("lineas__producto"),
        pk=pk,
    )
    if presupuesto.estado != Presupuesto.Estado.ACTIVO:
        messages.warning(request, "Este presupuesto ya fue aprobado.")
        return redirect("presupuesto_lista")

    line_specs = []
    err = None
    for ln in presupuesto.lineas.select_related("producto"):
        prod = ln.producto
        if not prod.habilitado:
            err = f"El producto {prod.codigo} ya no está habilitado."
            break
        if prod.stock < ln.cantidad:
            err = (
                f"Stock insuficiente para {prod.codigo} al aprobar (necesario: {ln.cantidad}, "
                f"disponible: {prod.stock})."
            )
            break
        line_specs.append((prod, ln.cantidad, ln.precio_unitario, ln.subtotal))

    if err:
        messages.error(request, err)
        return redirect("presupuesto_detalle", pk=pk)
    if not line_specs:
        messages.error(request, "El presupuesto no tiene líneas.")
        return redirect("presupuesto_detalle", pk=pk)

    try:
        with transaction.atomic():
            venta = crear_venta_confirmada(
                presupuesto.vendedor_id,
                presupuesto.fecha_vencimiento_pago,
                presupuesto.descuento_monto,
                presupuesto.comision_porcentaje,
                line_specs,
                comprador_id=presupuesto.comprador_id,
                creado_por_id=request.user.id,
                aplica_comision=presupuesto.aplica_comision,
            )
            presupuesto.estado = Presupuesto.Estado.APROBADO
            presupuesto.venta = venta
            presupuesto.aprobado_en = timezone.now()
            presupuesto.aprobado_por = request.user
            presupuesto.actualizado_por = request.user
            presupuesto.save(
                update_fields=[
                    "estado",
                    "venta",
                    "aprobado_en",
                    "aprobado_por",
                    "actualizado_por",
                ]
            )
    except Exception as exc:
        messages.error(request, f"No se pudo generar el pedido: {exc}")
        return redirect("presupuesto_detalle", pk=pk)

    messages.success(
        request,
        f"Presupuesto aprobado. Pedido #{venta.pk} creado (mismo flujo que ventas: pago, caja, calendario).",
    )
    return redirect("ventas_historial")
