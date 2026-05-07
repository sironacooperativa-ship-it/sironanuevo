from decimal import Decimal, InvalidOperation
from itertools import zip_longest

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from core.authz import is_staff_user
from core.export_utils import parse_export
from core.money_decimal import COMISION_PORCENTAJE_DEFECTO, format_monto_ars, parse_decimal_from_input, q2
from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_param, parse_fecha_dashboard, rango_periodo
from core.repoblar_lineas import repoblar_campos_cabecera_desde_post
from personas.models import Comprador, Vendedor
from productos.models import ListaPrecios, Producto
from ventas.servicios import crear_venta_confirmada, eliminar_venta_admin, unpack_linea_spec
from ventas.models import Venta, VentaLinea
from calendario.models import Evento

def _get_vendedor_from_user(user) -> Vendedor | None:
    if not user or not user.is_authenticated:
        return None
    v = getattr(user, "vendedor_perfil", None)
    return v if isinstance(v, Vendedor) else None

from .models import Presupuesto, PresupuestoLinea, presupuesto_tiene_alerta_catalogo
from .presupuesto_pdf import presupuesto_pdf_response
from .share_utils import contexto_compartir_presupuesto, pk_desde_token_compartir


def _usuario_puede_gestionar_presupuesto(user, pr: Presupuesto) -> bool:
    if not user or not user.is_authenticated:
        return False
    if is_staff_user(user):
        return True
    v = _get_vendedor_from_user(user)
    return v is not None and int(v.pk) == int(pr.vendedor_id)


def _ejecutar_aprobar_presupuesto_core(request, pr: Presupuesto, resolver: str) -> Venta:
    """
    `pr` debe estar bloqueada (select_for_update) y en ACT.
    `resolver` si hay alerta de catálogo: "actualizar" o "conservar".
    """
    if pr.estado != Presupuesto.Estado.ACTIVO:
        raise ValueError("Este presupuesto ya no está pendiente.")

    lineas_list = list(pr.lineas.select_related("producto").order_by("id"))
    if not lineas_list:
        raise ValueError("El presupuesto no tiene líneas.")

    for ln in lineas_list:
        prod = ln.producto
        if not prod.habilitado:
            raise ValueError(f"El producto {prod.codigo} ya no está habilitado.")
        if prod.stock < ln.cantidad:
            raise ValueError(
                f"Stock insuficiente para {prod.codigo} al aprobar (necesario: {ln.cantidad}, "
                f"disponible: {prod.stock})."
            )

    if presupuesto_tiene_alerta_catalogo(pr):
        if resolver == "actualizar":
            _actualizar_presupuesto_lineas_desde_catalogo(pr)
        elif resolver == "conservar":
            _marcar_lineas_presupuesto_al_dia_con_catalogo(pr)
        else:
            raise ValueError(
                "Elegí cómo resolver el catálogo: «Actualizar desde catálogo» o «Conservar presupuesto original»."
            )

    pr.refresh_from_db()
    if pr.descuento_monto > pr.subtotal_lineas:
        raise ValueError(
            "El descuento supera el subtotal de líneas. Editá el presupuesto y ajustá descuento o líneas."
        )

    line_specs = []
    for ln in pr.lineas.select_related("producto").order_by("id"):
        prod = ln.producto
        line_specs.append(
            (
                prod,
                ln.cantidad,
                ln.precio_unitario,
                ln.subtotal,
                ln.codigo_snapshot or prod.codigo,
                ln.descripcion_snapshot or prod.descripcion,
            )
        )

    venta = crear_venta_confirmada(
        pr.vendedor_id,
        pr.fecha_vencimiento_pago,
        pr.descuento_monto,
        pr.comision_porcentaje,
        line_specs,
        comprador_id=pr.comprador_id,
        creado_por_id=request.user.id,
        aplica_comision=pr.aplica_comision,
        envio=pr.envio,
    )
    pr.estado = Presupuesto.Estado.APROBADO
    pr.venta = venta
    pr.aprobado_en = timezone.now()
    pr.aprobado_por = request.user
    pr.actualizado_por = request.user
    pr.save(
        update_fields=[
            "estado",
            "venta",
            "aprobado_en",
            "aprobado_por",
            "actualizado_por",
        ]
    )
    return venta


def _actualizar_presupuesto_lineas_desde_catalogo(presupuesto: Presupuesto) -> None:
    """Recalcula precios desde el precio de venta actual del producto y actualiza snapshots."""
    subtotal = Decimal("0.00")
    for ln in presupuesto.lineas.select_related("producto").order_by("id"):
        prod = ln.producto
        pu = q2(prod.precio_venta)
        st = q2(Decimal(ln.cantidad) * pu)
        subtotal += st
        PresupuestoLinea.objects.filter(pk=ln.pk).update(
            precio_unitario=pu,
            subtotal=st,
            codigo_snapshot=(prod.codigo or "")[:6],
            descripcion_snapshot=(prod.descripcion or "")[:255],
            producto_capturado_en=prod.actualizado_en,
        )
    presupuesto.subtotal_lineas = subtotal
    presupuesto.save(update_fields=["subtotal_lineas"])


def _marcar_lineas_presupuesto_al_dia_con_catalogo(presupuesto: Presupuesto) -> None:
    """Sin cambiar montos ni textos: registra que el presupuesto se aprueba con valores actuales respecto al catálogo."""
    for ln in presupuesto.lineas.select_related("producto"):
        prod = ln.producto
        PresupuestoLinea.objects.filter(pk=ln.pk).update(producto_capturado_en=prod.actualizado_en)


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


def _lista_farmacia_o_primera() -> ListaPrecios | None:
    return (
        ListaPrecios.objects.filter(es_farmacia=True).order_by("id").first()
        or ListaPrecios.objects.order_by("id").first()
    )


def _lista_precios_desde_post(request) -> ListaPrecios | None:
    raw = (request.POST.get("lista_precios") or "").strip()
    if raw.isdigit():
        lp = ListaPrecios.objects.filter(pk=int(raw)).first()
        if lp:
            return lp
    return _lista_farmacia_o_primera()


def _precio_producto_para_lista(lista: ListaPrecios, prod: Producto) -> Decimal:
    p = lista.precio_para(prod)
    if p is not None:
        return q2(Decimal(str(p)))
    return q2(prod.precio_venta)


def _productos_queryset_para_lista(lista: ListaPrecios):
    qs = Producto.objects.filter(habilitado=True)
    if lista.es_farmacia:
        return qs.filter(en_lista_precios=True)
    return qs.filter(items_lista_precio__lista_id=lista.pk).distinct()


def _productos_payload_lista(lista: ListaPrecios):
    qs = _productos_queryset_para_lista(lista).order_by("descripcion", "codigo")
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
def presupuesto_catalogo_precios(request):
    lid = (request.GET.get("lista") or "").strip()
    if not lid.isdigit():
        return JsonResponse({"error": "Lista no válida"}, status=400)
    lista = ListaPrecios.objects.filter(pk=int(lid)).first()
    if lista is None:
        return JsonResponse({"error": "Lista no encontrada"}, status=404)
    return JsonResponse({"productos": _productos_payload_lista(lista)})


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
    raw_envio = (request.POST.get("envio") or "").strip()
    try:
        descuento = (
            parse_decimal_from_input(raw_desc) if raw_desc else Decimal("0")
        )
    except InvalidOperation:
        descuento = None
    try:
        envio = parse_decimal_from_input(raw_envio) if raw_envio else Decimal("0")
    except InvalidOperation:
        envio = None

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
    if envio is None or envio < 0:
        return "El envío no es válido.", None, None, None

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

    lista_venta = _lista_precios_desde_post(request)
    if lista_venta is None:
        return "No hay listas de precio disponibles. Creá al menos una en Productos → Listas de precio.", None, None, None

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
            prod_id = int(pid)
        except ValueError:
            err = "Producto no válido."
            break
        prod = _productos_queryset_para_lista(lista_venta).filter(pk=prod_id).first()
        if prod is None:
            err = "Un producto seleccionado no pertenece a la lista de precios elegida."
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
            pu = _precio_producto_para_lista(lista_venta, prod)
        if pu <= 0:
            err = f"El precio unitario debe ser mayor a cero ({prod.codigo})."
            break
        st = (pu * qty).quantize(Decimal("0.01"))
        subtotal += st
        line_specs.append((prod, qty, pu, st, prod.codigo, prod.descripcion))

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
        envio,
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
    envio,
    comision_pct,
    comprador_id=None,
    aplica_comision: bool = False,
):
    presupuesto.vendedor_id = vid
    presupuesto.comprador_id = comprador_id
    presupuesto.fecha_vencimiento_pago = fecha_v
    presupuesto.subtotal_lineas = subtotal
    presupuesto.descuento_monto = descuento
    presupuesto.envio = envio
    presupuesto.comision_porcentaje = comision_pct
    presupuesto.aplica_comision = aplica_comision
    presupuesto.save()
    presupuesto.lineas.all().delete()
    for spec in line_specs:
        prod, qty, pu, st, cod, desc = unpack_linea_spec(spec)
        PresupuestoLinea.objects.create(
            presupuesto=presupuesto,
            producto=prod,
            cantidad=qty,
            precio_unitario=pu,
            subtotal=st,
            codigo_snapshot=(cod or "")[:6],
            descripcion_snapshot=(desc or "")[:255],
            producto_capturado_en=prod.actualizado_en,
        )


def _filtrar_presupuestos_queryset(request):
    periodo = (request.GET.get("periodo") or "").strip()
    custom_periodo = (request.GET.get("custom_periodo") or "").strip()
    if periodo == "custom":
        if custom_periodo in ("60d", "180d", "365d"):
            fecha_desde, fecha_hasta = rango_periodo(custom_periodo)
        else:
            fecha_desde, fecha_hasta = None, None
    elif periodo in ("7d", "30d", "mes", "mes_ant"):
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
        "custom_periodo": custom_periodo,
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
    for pr in items:
        pr.alerta_catalogo = presupuesto_tiene_alerta_catalogo(pr)
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


def presupuesto_compartido(request, token: str):
    """
    Vista sin login: el cliente abre el enlace firmado (WhatsApp, etc.).
    """
    pk = pk_desde_token_compartir(token)
    if pk is None:
        raise Http404("El enlace no es válido o expiró. Pedí al vendedor que lo reenvíe desde el sistema.")
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
        resp = presupuesto_pdf_response(p)
        if (request.GET.get("inline") or "").strip() == "1":
            try:
                cd = resp.get("Content-Disposition", "")
                if cd:
                    resp["Content-Disposition"] = cd.replace("attachment", "inline", 1)
            except Exception:
                pass
        return resp
    ctx = {
        "presupuesto": p,
        "alerta_catalogo": False,
        "vista_publica_compartida": True,
        **contexto_compartir_presupuesto(request, p),
    }
    ctx["whatsapp_compartir_url"] = None
    ctx["url_compartir_cliente"] = None
    response = render(request, "presupuestos/detalle.html", ctx)
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


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
        resp = presupuesto_pdf_response(p)
        if (request.GET.get("inline") or "").strip() == "1":
            try:
                cd = resp.get("Content-Disposition", "")
                if cd:
                    resp["Content-Disposition"] = cd.replace("attachment", "inline", 1)
            except Exception:
                pass
        return resp
    ctx = {
        "presupuesto": p,
        "alerta_catalogo": presupuesto_tiene_alerta_catalogo(p),
        "vista_publica_compartida": False,
        **contexto_compartir_presupuesto(request, p),
    }
    return render(request, "presupuestos/detalle.html", ctx)


@login_required
@require_http_methods(["GET", "POST"])
def presupuesto_nuevo(request):
    vendedores = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    listas_precio = list(ListaPrecios.objects.all().order_by("-es_farmacia", "nombre"))
    lista_default = _lista_farmacia_o_primera()
    productos_catalogo = _productos_payload_lista(lista_default) if lista_default else []
    lineas_iniciales: list = []
    repoblar = None
    vendedor_default_id = None
    vuser = _get_vendedor_from_user(request.user)
    if vuser is not None and getattr(vuser, "habilitado", True):
        vendedor_default_id = vuser.pk

    if request.method == "POST":
        err, line_specs, subtotal, meta = _validar_lineas_post(request)
        if err is None:
            vid, fecha_v, descuento, envio, comision_pct, comprador_id, aplica_comision = meta
            with transaction.atomic():
                pr = Presupuesto.objects.create(
                    vendedor_id=vid,
                    comprador_id=comprador_id,
                    fecha_vencimiento_pago=fecha_v,
                    subtotal_lineas=subtotal,
                    descuento_monto=descuento,
                    envio=envio,
                    comision_porcentaje=comision_pct,
                    aplica_comision=aplica_comision,
                    creado_por=request.user,
                    actualizado_por=request.user,
                )
                for spec in line_specs:
                    prod, qty, pu, st, cod, desc = unpack_linea_spec(spec)
                    PresupuestoLinea.objects.create(
                        presupuesto=pr,
                        producto=prod,
                        cantidad=qty,
                        precio_unitario=pu,
                        subtotal=st,
                        codigo_snapshot=(cod or "")[:6],
                        descripcion_snapshot=(desc or "")[:255],
                        producto_capturado_en=prod.actualizado_en,
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
            "listas_precio": listas_precio,
            "presupuesto": None,
            "lineas_iniciales": lineas_iniciales,
            "repoblar": repoblar,
            "vendedor_default_id": vendedor_default_id,
            "lista_default": lista_default,
            "comision_default": COMISION_PORCENTAJE_DEFECTO,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def presupuesto_editar(request, pk: int):
    presupuesto = get_object_or_404(Presupuesto, pk=pk)
    es_admin = is_staff_user(request.user)
    if presupuesto.estado != Presupuesto.Estado.ACTIVO and not es_admin:
        messages.warning(request, "Solo administradores pueden editar presupuestos aprobados.")
        return redirect("presupuesto_lista")

    vendedores = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    listas_precio = list(ListaPrecios.objects.all().order_by("-es_farmacia", "nombre"))
    lista_default = _lista_farmacia_o_primera()
    productos_catalogo = _productos_payload_lista(lista_default) if lista_default else []
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
            vid, fecha_v, descuento, envio, comision_pct, comprador_id, aplica_comision = meta
            with transaction.atomic():
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
                        # Pedido pagado: permitir editar SOLO comisión (sin tocar líneas/stock/cabecera para no romper caja).
                        def _norm_line_specs(specs):
                            out = []
                            for spec in specs:
                                prod, qty, pu, st, _c, _d = unpack_linea_spec(spec)
                                out.append((prod.pk, int(qty), str(pu)))
                            return sorted(out)

                        actuales = [
                            (ln.producto_id, int(ln.cantidad), str(ln.precio_unitario))
                            for ln in presupuesto.lineas.all()
                        ]
                        if (
                            int(vid) != int(presupuesto.vendedor_id)
                            or int(comprador_id or 0) != int(presupuesto.comprador_id or 0)
                            or (fecha_v or None) != (presupuesto.fecha_vencimiento_pago or None)
                            or str(descuento) != str(presupuesto.descuento_monto)
                            or str(envio) != str(presupuesto.envio)
                            or _norm_line_specs(line_specs) != sorted(actuales)
                        ):
                            raise ValueError(
                                "El pedido generado ya está pagado. En este caso solo se puede editar la comisión del presupuesto (no líneas, vendedor, comprador, vencimiento, descuento ni envío)."
                            )
                        presupuesto.comision_porcentaje = comision_pct
                        presupuesto.aplica_comision = aplica_comision
                        presupuesto.actualizado_por = request.user
                        presupuesto.save(update_fields=["comision_porcentaje", "aplica_comision", "actualizado_por"])
                        messages.success(request, "Comisión actualizada (el pedido ya estaba pagado, no se modificó caja).")
                        return redirect("presupuesto_lista")

                    # Pedido pendiente: primero guardamos presupuesto y luego sincronizamos la venta
                    _guardar_presupuesto_desde_lineas(
                        presupuesto,
                        line_specs,
                        subtotal,
                        vid,
                        fecha_v,
                        descuento,
                        envio,
                        comision_pct,
                        comprador_id,
                        aplica_comision,
                    )
                    # Revertir stock por líneas viejas, rearmar líneas y descontar stock nuevo.
                    old_lines = list(venta.lineas.all())
                    for ln in old_lines:
                        Producto.objects.filter(pk=ln.producto_id).update(stock=F("stock") + ln.cantidad)
                    VentaLinea.objects.filter(venta_id=venta.pk).delete()

                    pids_afectados: list[int] = []
                    for spec in line_specs:
                        prod, qty, pu, st, cod, desc = unpack_linea_spec(spec)
                        VentaLinea.objects.create(
                            venta=venta,
                            producto=prod,
                            cantidad=qty,
                            precio_unitario=pu,
                            subtotal=st,
                            codigo_snapshot=(cod or "")[:6],
                            descripcion_snapshot=(desc or "")[:255],
                        )
                        Producto.objects.filter(pk=prod.pk).update(stock=F("stock") - qty)
                        pids_afectados.append(prod.pk)
                    Producto.deshabilitar_sin_stock(pids_afectados)

                    venta.vendedor_id = vid
                    venta.comprador_id = comprador_id
                    venta.fecha_vencimiento_pago = fecha_v
                    venta.subtotal_lineas = subtotal
                    venta.descuento_monto = descuento
                    venta.envio = envio
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
                            "envio",
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
                else:
                    _guardar_presupuesto_desde_lineas(
                        presupuesto,
                        line_specs,
                        subtotal,
                        vid,
                        fecha_v,
                        descuento,
                        envio,
                        comision_pct,
                        comprador_id,
                        aplica_comision,
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
            "listas_precio": listas_precio,
            "presupuesto": presupuesto,
            "lineas_iniciales": lineas_iniciales,
            "repoblar": repoblar,
            "lista_default": lista_default,
            "comision_default": COMISION_PORCENTAJE_DEFECTO,
        },
    )


@login_required
@require_http_methods(["POST"])
def presupuesto_eliminar(request, pk: int):
    presupuesto = get_object_or_404(Presupuesto, pk=pk)
    es_admin = is_staff_user(request.user)
    if not es_admin:
        vuser = _get_vendedor_from_user(request.user)
        if vuser is None or int(vuser.pk) != int(presupuesto.vendedor_id):
            messages.error(
                request,
                "No tenés permiso para eliminar este presupuesto. Solo el vendedor asignado o un administrador.",
            )
            return redirect("presupuesto_lista")
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
        detalle = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
        messages.error(request, "No se pudo eliminar el presupuesto." + detalle)
        return redirect("presupuesto_lista")
    messages.success(request, f"Presupuesto #{nid} eliminado.")
    return redirect("presupuesto_lista")


@login_required
@require_http_methods(["POST"])
def presupuesto_aprobar(request, pk: int):
    presupuesto = get_object_or_404(Presupuesto, pk=pk)
    if not _usuario_puede_gestionar_presupuesto(request.user, presupuesto):
        messages.error(
            request,
            "No tenés permiso para aprobar este presupuesto (solo el vendedor asignado o un administrador).",
        )
        return redirect("presupuesto_lista")
    if presupuesto.estado != Presupuesto.Estado.ACTIVO:
        messages.warning(request, "Este presupuesto ya fue aprobado.")
        return redirect("presupuesto_lista")

    resolver = (request.POST.get("resolver_catalogo") or "").strip()
    necesita_resolver = presupuesto_tiene_alerta_catalogo(presupuesto)
    if necesita_resolver and resolver not in ("actualizar", "conservar"):
        messages.error(
            request,
            "El catálogo de productos cambió después de armar este presupuesto. "
            "Elegí «Actualizar desde catálogo» o «Conservar presupuesto original» antes de aprobar.",
        )
        return redirect("presupuesto_detalle", pk=pk)

    venta = None
    try:
        with transaction.atomic():
            pr = Presupuesto.objects.select_for_update().get(pk=pk)
            if pr.estado != Presupuesto.Estado.ACTIVO:
                messages.warning(request, "Este presupuesto ya fue aprobado.")
                return redirect("presupuesto_lista")
            venta = _ejecutar_aprobar_presupuesto_core(request, pr, resolver)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("presupuesto_detalle", pk=pk)
    except Exception as exc:
        detalle = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
        messages.error(request, "No se pudo generar el pedido." + detalle)
        return redirect("presupuesto_detalle", pk=pk)

    messages.success(
        request,
        f"Presupuesto aprobado. Pedido #{venta.pk} creado (mismo flujo que ventas: pago, caja, calendario).",
    )
    return redirect("ventas_historial")


@login_required
@require_http_methods(["POST"])
def presupuesto_duplicar(request, pk: int):
    orig = get_object_or_404(
        Presupuesto.objects.select_related("vendedor", "comprador").prefetch_related("lineas__producto"),
        pk=pk,
    )
    if not _usuario_puede_gestionar_presupuesto(request.user, orig):
        messages.error(
            request,
            "No tenés permiso para duplicar este presupuesto (solo el vendedor asignado o un administrador).",
        )
        return redirect("presupuesto_lista")

    try:
        with transaction.atomic():
            nuevo = Presupuesto.objects.create(
                vendedor_id=orig.vendedor_id,
                comprador_id=orig.comprador_id,
                estado=Presupuesto.Estado.ACTIVO,
                fecha_vencimiento_pago=orig.fecha_vencimiento_pago,
                subtotal_lineas=orig.subtotal_lineas,
                descuento_monto=orig.descuento_monto,
                envio=orig.envio,
                comision_porcentaje=orig.comision_porcentaje,
                aplica_comision=orig.aplica_comision,
                creado_por=request.user,
                actualizado_por=request.user,
            )
            for ln in orig.lineas.select_related("producto").order_by("id"):
                PresupuestoLinea.objects.create(
                    presupuesto=nuevo,
                    producto_id=ln.producto_id,
                    cantidad=ln.cantidad,
                    precio_unitario=ln.precio_unitario,
                    subtotal=ln.subtotal,
                    codigo_snapshot=ln.codigo_snapshot,
                    descripcion_snapshot=ln.descripcion_snapshot,
                    producto_capturado_en=ln.producto_capturado_en,
                )
    except Exception as exc:
        detalle = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
        messages.error(request, "No se pudo duplicar el presupuesto." + detalle)
        return redirect("presupuesto_detalle", pk=pk)

    messages.success(
        request,
        f"Copia creada: presupuesto #{nuevo.pk} (mismas líneas y montos). Podés editarla o aprobarla.",
    )
    return redirect("presupuesto_detalle", pk=nuevo.pk)


@login_required
@require_http_methods(["POST"])
def presupuestos_aprobar_masivo(request):
    raw = request.POST.getlist("presupuesto_id")
    ids = sorted({int(x) for x in raw if str(x).isdigit()})
    retorno = (request.POST.get("retorno_query") or "").strip()
    lista_url = reverse("presupuesto_lista")
    if retorno:
        lista_url += "?" + retorno

    if not ids:
        messages.warning(request, "No seleccionaste presupuestos pendientes.")
        return redirect(lista_url)

    modo = (request.POST.get("resolver_masivo_catalogo") or "omitir").strip()
    if modo not in ("omitir", "conservar", "actualizar"):
        modo = "omitir"

    ok: list[tuple[int, int]] = []
    skip_alerta: list[int] = []
    fallos: list[str] = []

    for pid in ids:
        try:
            pr = Presupuesto.objects.filter(pk=pid).select_related("vendedor").first()
            if not pr:
                fallos.append(f"#{pid} no encontrado")
                continue
            if not _usuario_puede_gestionar_presupuesto(request.user, pr):
                fallos.append(f"#{pid} sin permiso")
                continue
            if pr.estado != Presupuesto.Estado.ACTIVO:
                fallos.append(f"#{pid} no está pendiente")
                continue
            if presupuesto_tiene_alerta_catalogo(pr):
                if modo == "omitir":
                    skip_alerta.append(pid)
                    continue
                res = "conservar" if modo == "conservar" else "actualizar"
            else:
                res = ""
            with transaction.atomic():
                bloqueado = Presupuesto.objects.select_for_update().get(pk=pr.pk)
                if bloqueado.estado != Presupuesto.Estado.ACTIVO:
                    fallos.append(f"#{pid} ya aprobado")
                    continue
                venta_creada = _ejecutar_aprobar_presupuesto_core(request, bloqueado, res)
                ok.append((pid, venta_creada.pk))
        except ValueError as e:
            fallos.append(f"#{pid}: {e}")
        except Exception as e:
            det = str(e) if getattr(request.user, "is_staff", False) else ""
            fallos.append(f"#{pid} error" + (f" ({det})" if det else ""))

    partes: list[str] = []
    if ok:
        nums = ", ".join(f"#{p} → pedido #{vp}" for p, vp in ok)
        partes.append(f"{len(ok)} aprobado(s): {nums}.")
    if skip_alerta:
        partes.append(
            f"Omitidos {len(skip_alerta)} (alerta de catálogo: {', '.join(f'#{i}' for i in skip_alerta)}). "
            f"Aprobalos desde el detalle o elegí «conservar/actualizar catálogo» arriba."
        )
    if fallos:
        partes.append("No aprobados: " + " · ".join(fallos[:8]) + ("…" if len(fallos) > 8 else ""))

    if ok:
        messages.success(request, " ".join(partes) or "Listo.")
    elif not fallos and skip_alerta:
        messages.info(request, " ".join(partes))
    else:
        messages.warning(request, " ".join(partes) if partes else "Nada para aprobar.")

    return redirect(lista_url)
