from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from core.fecha_filtros import parse_fecha_param
from core.repoblar_lineas import lineas_iniciales_desde_post, repoblar_campos_cabecera_desde_post
from personas.models import Comprador, Vendedor
from productos.models import Producto
from ventas.servicios import crear_venta_confirmada

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


def _validar_lineas_post(request):
    """Valida POST de líneas (igual que venta). Devuelve (error_msg|None, line_specs, subtotal, extras)."""
    vid = request.POST.get("vendedor")
    fecha_v = parse_fecha_param(request.POST.get("fecha_vencimiento_pago") or "")
    try:
        descuento = Decimal(str(request.POST.get("descuento_monto") or "0").replace(",", "."))
    except InvalidOperation:
        descuento = None

    pids = request.POST.getlist("linea_producto")
    qtys = request.POST.getlist("linea_cantidad")

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
        ven = Vendedor.objects.get(pk=int(vid), habilitado=True)
    except (ValueError, Vendedor.DoesNotExist):
        return "El vendedor seleccionado no existe o no está habilitado.", None, None, None
    comision_pct = ven.comision_porcentaje

    line_specs = []
    subtotal = Decimal("0.00")
    err = None
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

    if err:
        return err, None, None, None
    if not line_specs:
        return "Agregá al menos un producto.", None, None, None
    if descuento > subtotal:
        return "El descuento no puede superar el subtotal de las líneas.", None, None, None

    aplica_comision = request.POST.get("aplica_comision") == "1"
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


@login_required
def presupuesto_lista(request):
    items = (
        Presupuesto.objects.select_related("vendedor", "venta")
        .prefetch_related("lineas__producto")
        .order_by("-creado_en", "-id")
    )
    return render(request, "presupuestos/lista.html", {"presupuestos": items})


@login_required
def presupuesto_detalle(request, pk: int):
    p = get_object_or_404(
        Presupuesto.objects.select_related("vendedor", "venta", "comprador").prefetch_related(
            "lineas__producto"
        ),
        pk=pk,
    )
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
        lineas_iniciales = lineas_iniciales_desde_post(request)
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
    if presupuesto.estado != Presupuesto.Estado.ACTIVO:
        messages.warning(request, "Solo se pueden editar presupuestos pendientes de aprobar.")
        return redirect("presupuesto_lista")

    vendedores = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    productos_catalogo = _productos_payload()
    lineas_iniciales = [
        {"producto_id": ln.producto_id, "cantidad": ln.cantidad} for ln in presupuesto.lineas.all()
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
                presupuesto.actualizado_por = request.user
                presupuesto.save(update_fields=["actualizado_por"])
            messages.success(request, "Presupuesto actualizado.")
            return redirect("presupuesto_lista")
        messages.error(request, err)
        lineas_iniciales = lineas_iniciales_desde_post(request)
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
    if presupuesto.estado != Presupuesto.Estado.ACTIVO:
        messages.warning(request, "No se puede eliminar un presupuesto ya aprobado.")
        return redirect("presupuesto_lista")
    nid = presupuesto.pk
    presupuesto.delete()
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

    comision_aprobacion = presupuesto.vendedor.comision_porcentaje
    try:
        with transaction.atomic():
            venta = crear_venta_confirmada(
                presupuesto.vendedor_id,
                presupuesto.fecha_vencimiento_pago,
                presupuesto.descuento_monto,
                comision_aprobacion,
                line_specs,
                comprador_id=presupuesto.comprador_id,
                creado_por_id=request.user.id,
                aplica_comision=presupuesto.aplica_comision,
            )
            presupuesto.comision_porcentaje = comision_aprobacion
            presupuesto.estado = Presupuesto.Estado.APROBADO
            presupuesto.venta = venta
            presupuesto.aprobado_en = timezone.now()
            presupuesto.aprobado_por = request.user
            presupuesto.actualizado_por = request.user
            presupuesto.save(
                update_fields=[
                    "comision_porcentaje",
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
