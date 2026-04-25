from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Sum, Value, When
from django.db.models.functions import Coalesce
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.dateparse import parse_date

from personas.models import Comprador, Vendedor
from personas.forms import CompradorForm
from core.export_utils import parse_export
from presupuestos.models import Presupuesto, PresupuestoLinea, presupuesto_tiene_alerta_catalogo
from presupuestos.presupuesto_pdf import presupuesto_pdf_response
from presupuestos.share_utils import contexto_compartir_presupuesto
from presupuestos.views import _lineas_presupuesto_desde_post, _productos_payload, _validar_lineas_post
from productos.lista_precios_pdf import filas_lista_precios, lista_precios_pdf_file_response
from productos.models import ListaPrecioItem, ListaPrecios, Producto
from core.money_decimal import format_monto_ars
from ventas.models import Venta
from ventas.servicios import unpack_linea_spec
from caja.models import MovimientoCaja

def _get_vendedor_from_user(user) -> Vendedor | None:
    if not user or not user.is_authenticated:
        return None
    v = getattr(user, "vendedor_perfil", None)
    return v if isinstance(v, Vendedor) else None


def _listas_precios_accesibles(vendedor: Vendedor):
    bloqueadas = vendedor.listas_precios_bloqueadas.values_list("pk", flat=True)
    return ListaPrecios.objects.exclude(pk__in=bloqueadas)


def _vendedor_puede_ver_lista(vendedor: Vendedor, lista: ListaPrecios) -> bool:
    return not vendedor.listas_precios_bloqueadas.filter(pk=lista.pk).exists()


@login_required
@require_http_methods(["GET", "POST"])
def vendedor_home(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    q = (request.GET.get("cliente") or "").strip()
    comprador_id_raw = (request.GET.get("comprador") or request.POST.get("comprador") or "").strip()
    comprador = None
    if comprador_id_raw.isdigit():
        comprador = (
            Comprador.objects.filter(
                pk=int(comprador_id_raw),
                habilitado=True,
                vendedor_asignado_id=vendedor.pk,
            ).first()
        )

    mis_clientes = list(
        Comprador.objects.filter(habilitado=True, vendedor_asignado_id=vendedor.pk)
        .order_by("apellido", "nombre", "codigo")[:500]
    )

    # Buscar clientes (si hay texto y todavía no eligieron uno)
    candidatos = []
    if q and comprador is None:
        candidatos = list(
            Comprador.objects.filter(habilitado=True, vendedor_asignado_id=vendedor.pk)
            .filter(
                Q(apellido__icontains=q)
                | Q(nombre__icontains=q)
                | Q(codigo__icontains=q)
                | Q(dni__icontains=q)
            )
            .order_by("apellido", "nombre", "codigo")[:15]
        )

    # Historial impago (solo si hay comprador elegido)
    impagos = []
    if comprador is not None:
        impagos = (
            Venta.objects.filter(
                estado=Venta.Estado.PENDIENTE,
                vendedor_id=vendedor.pk,
                comprador_id=comprador.pk,
            )
            .order_by("fecha_vencimiento_pago", "id")
            .all()
        )

    lista_default = (
        ListaPrecios.objects.filter(es_farmacia=True).order_by("id").first()
        or ListaPrecios.objects.order_by("id").first()
    )
    listas_precio = list(ListaPrecios.objects.all().order_by("-es_farmacia", "nombre"))
    productos_catalogo = (
        [{"id": p.id, "codigo": p.codigo, "descripcion": p.descripcion, "precio": str(lista_default.precio_para(p) or p.precio_venta), "stock": p.stock}
         for p in (
            (Producto.objects.filter(habilitado=True, en_lista_precios=True) if lista_default and lista_default.es_farmacia
             else Producto.objects.filter(habilitado=True, items_lista_precio__lista_id=lista_default.pk).distinct()
            ).order_by("descripcion", "codigo")
         )]
        if lista_default
        else []
    )
    lineas_iniciales: list = []
    repoblar = None

    if request.method == "POST":
        if comprador is None:
            messages.error(request, "Elegí un cliente antes de guardar el presupuesto.")
            return redirect("vendedor_home")

        # Reusar validador existente, pero forzar vendedor = este perfil
        post = request.POST.copy()
        post["vendedor"] = str(vendedor.pk)
        # Comisión inamovible en modo vendedor: viene del perfil del vendedor.
        post["comision_porcentaje"] = str(vendedor.comision_porcentaje)
        post["aplica_comision"] = "1"
        request.POST = post  # type: ignore[misc]

        err, line_specs, subtotal, meta = _validar_lineas_post(request)
        if err is None:
            vid, fecha_v, descuento, comision_pct, comprador_id, aplica_comision = meta
            comprador_id = comprador.pk
            with transaction.atomic():
                pr = Presupuesto.objects.create(
                    vendedor_id=vid,
                    comprador_id=comprador_id,
                    fecha_vencimiento_pago=fecha_v,
                    subtotal_lineas=subtotal,
                    descuento_monto=descuento,
                    comision_porcentaje=vendedor.comision_porcentaje,
                    aplica_comision=True,
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
            messages.success(request, f"Presupuesto #{pr.pk} guardado. Podés compartirlo por WhatsApp desde la ficha.")
            return redirect("vendedor_presupuesto_ver", pk=pr.pk)

        messages.error(request, err)
        lineas_iniciales = _lineas_presupuesto_desde_post(request)
        repoblar = {
            "fecha_vencimiento_pago": request.POST.get("fecha_vencimiento_pago") or "",
            "descuento_monto": request.POST.get("descuento_monto") or "0",
            "aplica_comision": True,
        }

    return render(
        request,
        "vendedor_portal/home.html",
        {
            "vendedor": vendedor,
            "cliente_busqueda": q,
            "mis_clientes": mis_clientes,
            "candidatos": candidatos,
            "comprador": comprador,
            "impagos": impagos,
            "productos_catalogo": productos_catalogo,
            "listas_precio": listas_precio,
            "lista_default": lista_default,
            "lineas_iniciales": lineas_iniciales,
            "repoblar": repoblar,
        },
    )


@login_required
def vendedor_presupuesto_ver(request, pk: int):
    """Ficha del presupuesto para el vendedor (compartir por WhatsApp, mismo contenido que en administración)."""
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")
    p = get_object_or_404(
        Presupuesto.objects.select_related(
            "vendedor",
            "comprador",
            "venta",
            "venta__pago_movimiento",
            "venta__pago_movimiento__creado_por",
        ).prefetch_related("lineas__producto"),
        pk=pk,
        vendedor_id=vendedor.pk,
    )
    if parse_export(request) == "pdf":
        return presupuesto_pdf_response(p)
    ctx = {
        "presupuesto": p,
        "alerta_catalogo": presupuesto_tiene_alerta_catalogo(p),
        "vista_publica_compartida": False,
        **contexto_compartir_presupuesto(request, p),
    }
    return render(request, "presupuestos/detalle.html", ctx)


@login_required
def vendedor_clientes_list(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    q = (request.GET.get("q") or "").strip()
    qs = Comprador.objects.filter(vendedor_asignado_id=vendedor.pk).order_by(
        "apellido", "nombre", "codigo"
    )
    if q:
        qs = qs.filter(Q(apellido__icontains=q) | Q(nombre__icontains=q) | Q(codigo__icontains=q))
    clientes = list(qs[:250])
    return render(
        request,
        "vendedor_portal/clientes_list.html",
        {"vendedor": vendedor, "clientes": clientes, "q": q},
    )


@login_required
@require_http_methods(["GET", "POST"])
def vendedor_cliente_create(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    if request.method == "POST":
        post = request.POST.copy()
        post.pop("vendedor_asignado", None)
        request.POST = post  # type: ignore[misc]
        form = CompradorForm(request.POST)
        if form.is_valid():
            c = form.save(commit=False)
            c.vendedor_asignado_id = vendedor.pk
            c.save()
            messages.success(request, f"Cliente creado: {c.codigo}")
            return redirect("vendedor_clientes_list")
    else:
        form = CompradorForm()
    return render(
        request,
        "vendedor_portal/cliente_form.html",
        {"vendedor": vendedor, "form": form, "modo": "nuevo", "cliente": None},
    )


@login_required
@require_http_methods(["GET", "POST"])
def vendedor_cliente_update(request, pk: int):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    c = get_object_or_404(Comprador, pk=pk)
    # Seguridad simple: el vendedor solo edita sus clientes asignados.
    if c.vendedor_asignado_id not in (None, vendedor.pk):
        return HttpResponseForbidden("No podés editar este cliente.")
    if request.method == "POST":
        post = request.POST.copy()
        post.pop("vendedor_asignado", None)
        request.POST = post  # type: ignore[misc]
        form = CompradorForm(request.POST, instance=c)
        if form.is_valid():
            c = form.save(commit=False)
            if c.vendedor_asignado_id is None:
                c.vendedor_asignado_id = vendedor.pk
            c.save()
            messages.success(request, f"Cliente actualizado: {c.codigo}")
            return redirect("vendedor_clientes_list")
    else:
        form = CompradorForm(instance=c)
    return render(
        request,
        "vendedor_portal/cliente_form.html",
        {"vendedor": vendedor, "form": form, "modo": "editar", "cliente": c},
    )


@login_required
def vendedor_stock(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    q = (request.GET.get("q") or "").strip()
    qs = Producto.objects.filter(habilitado=True).order_by("descripcion", "codigo")
    if q:
        qs = qs.filter(Q(descripcion__icontains=q) | Q(codigo__icontains=q))
    productos = list(qs[:400])
    return render(
        request,
        "vendedor_portal/stock.html",
        {"vendedor": vendedor, "productos": productos, "q": q},
    )


def _get_lista_precios_por_slug(slug: str) -> ListaPrecios | None:
    s = (slug or "").strip().lower()
    if not s:
        return None
    return ListaPrecios.objects.filter(slug=s).first()


@login_required
def vendedor_listas(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    items = []
    for lista in _listas_precios_accesibles(vendedor).order_by("-es_farmacia", "nombre"):
        if lista.es_farmacia:
            cant = Producto.objects.filter(habilitado=True, en_lista_precios=True).count()
        else:
            cant = ListaPrecioItem.objects.filter(lista=lista, producto__habilitado=True).count()
        items.append(
            {
                "slug": lista.slug,
                "nombre": lista.nombre,
                "existe": True,
                "cantidad": cant,
                "es_farmacia": lista.es_farmacia,
            }
        )
    return render(request, "vendedor_portal/listas.html", {"vendedor": vendedor, "listas": items})


@login_required
def vendedor_lista_pdf(request, slug: str):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    lista = _get_lista_precios_por_slug(slug)
    if lista is None:
        return HttpResponseBadRequest("Lista no válida o no configurada.")
    if not _vendedor_puede_ver_lista(vendedor, lista):
        return HttpResponseForbidden("No tenés acceso a esa lista de precios.")
    return lista_precios_pdf_file_response(lista=lista)


@login_required
def vendedor_lista_png(request, slug: str):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    lista = _get_lista_precios_por_slug(slug)
    if lista is None:
        return HttpResponseBadRequest("Lista no válida o no configurada.")
    if not _vendedor_puede_ver_lista(vendedor, lista):
        return HttpResponseForbidden("No tenés acceso a esa lista de precios.")
    filas = filas_lista_precios(lista)
    payload = [
        {
            "codigo": p.codigo,
            "tipo": p.get_tipo_display(),
            "descripcion": p.descripcion,
            "precio": format_monto_ars(precio),
        }
        for p, precio in filas
    ]
    return render(
        request,
        "vendedor_portal/lista_png.html",
        {
            "vendedor": vendedor,
            "titulo": f"Lista de precios — {lista.nombre}",
            "slug": slug,
            "productos": payload,
        },
    )


def _venta_neto_sql():
    """Replica `Venta.neto` en SQL para agregaciones."""
    return Case(
        When(subtotal_lineas__gt=F("descuento_monto"), then=F("subtotal_lineas") - F("descuento_monto")),
        default=Value(0),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


@login_required
def vendedor_cuenta_corriente(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    hoy = timezone.localdate()
    neto_expr = _venta_neto_sql()
    pendientes = Venta.objects.filter(vendedor_id=vendedor.pk, estado=Venta.Estado.PENDIENTE)
    # Imputado al saldo: sin fecha de vencimiento o fecha ya vencida (incluye el día de hoy).
    saldo_pendiente = pendientes.filter(
        Q(fecha_vencimiento_pago__isnull=True) | Q(fecha_vencimiento_pago__lte=hoy)
    ).aggregate(s=Sum(neto_expr))["s"] or Decimal("0")
    # Con vencimiento futuro: aún no imputa al saldo; se muestra como "a pagar".
    total_a_pagar_futuro = pendientes.filter(fecha_vencimiento_pago__gt=hoy).aggregate(s=Sum(neto_expr))[
        "s"
    ] or Decimal("0")

    # Pedidos del vendedor (incluye comprador si existe)
    ventas = (
        Venta.objects.filter(vendedor_id=vendedor.pk)
        .select_related("comprador", "pago_movimiento")
        .order_by("-creado_en", "-id")[:250]
    )

    # Movimientos de caja relacionados (pagos / ajustes que referencien vendedor o venta del vendedor)
    movs = (
        MovimientoCaja.objects.filter(
            Q(vendedor_id=vendedor.pk) | Q(venta__vendedor_id=vendedor.pk)
        )
        .select_related("venta")
        .order_by("-fecha", "-id")[:250]
    )

    return render(
        request,
        "vendedor_portal/cuenta_corriente.html",
        {
            "vendedor": vendedor,
            "ventas": ventas,
            "movimientos": movs,
            "hoy": hoy,
            "saldo_pendiente": saldo_pendiente,
            "total_a_pagar_futuro": total_a_pagar_futuro,
        },
    )


@login_required
def vendedor_reportes(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    # Actividad propia
    neto_expr = ExpressionWrapper(
        F("subtotal_lineas") - F("descuento_monto"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    neto_nonneg = Case(
        When(subtotal_lineas__gte=F("descuento_monto"), then=neto_expr),
        default=Value(Decimal("0.00")),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    mis_ventas = Venta.objects.filter(vendedor_id=vendedor.pk)
    actividad = mis_ventas.aggregate(
        pedidos=Count("id"),
        neto_total=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))),
    )

    # --- Series temporales (gráficos) ---
    # GET params:
    # - g: day | week | month
    # - r: weekly | monthly | bimonthly | annual | all
    # - desde/hasta opcionales (si r=custom)
    gran = (request.GET.get("g") or "month").strip().lower()
    rango = (request.GET.get("r") or "annual").strip().lower()
    desde = parse_date((request.GET.get("desde") or "").strip() or "") if rango == "custom" else None
    hasta = parse_date((request.GET.get("hasta") or "").strip() or "") if rango == "custom" else None

    hoy = timezone.localdate()
    start = None
    end = None
    if rango == "weekly":
        start = hoy - timedelta(days=6)
    elif rango == "monthly":
        start = hoy - timedelta(days=29)
    elif rango == "bimonthly":
        start = hoy - timedelta(days=59)
    elif rango == "annual":
        start = hoy - timedelta(days=364)
    elif rango == "all":
        start = None
    elif rango == "custom":
        start = desde
        end = hasta

    if gran not in ("day", "week", "month"):
        gran = "month"
    if rango not in ("weekly", "monthly", "bimonthly", "annual", "all", "custom"):
        rango = "annual"

    qs_ts = mis_ventas
    if start is not None:
        qs_ts = qs_ts.filter(creado_en__date__gte=start)
    if end is not None:
        qs_ts = qs_ts.filter(creado_en__date__lte=end)

    if gran == "day":
        bucket = TruncDay("creado_en")
        label_fmt = "%d/%m"
    elif gran == "week":
        bucket = TruncWeek("creado_en")
        label_fmt = "sem %W/%Y"
    else:
        bucket = TruncMonth("creado_en")
        label_fmt = "%m/%Y"

    rows = (
        qs_ts.annotate(bucket=bucket)
        .values("bucket")
        .annotate(neto=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))), pedidos=Count("id"))
        .order_by("bucket")
    )
    labels = []
    serie_neto = []
    serie_pedidos = []
    for r in rows:
        b = r["bucket"]
        if not b:
            continue
        b_local = timezone.localtime(b) if timezone.is_aware(b) else b
        labels.append(b_local.strftime(label_fmt))
        serie_neto.append(float(r["neto"] or 0))
        serie_pedidos.append(int(r["pedidos"] or 0))

    # Global: últimos ~3 meses, semana a semana, total de TODOS los vendedores
    start_global = hoy - timedelta(days=7 * 12 - 1)  # ~12 semanas
    global_rows = (
        Venta.objects.filter(creado_en__date__gte=start_global)
        .annotate(bucket=TruncWeek("creado_en"))
        .values("bucket")
        .annotate(neto=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))), pedidos=Count("id"))
        .order_by("bucket")
    )
    global_labels = []
    global_neto = []
    global_pedidos = []
    for r in global_rows:
        b = r["bucket"]
        if not b:
            continue
        b_local = timezone.localtime(b) if timezone.is_aware(b) else b
        global_labels.append(b_local.strftime("sem %W/%Y"))
        global_neto.append(float(r["neto"] or 0))
        global_pedidos.append(int(r["pedidos"] or 0))

    chart = {
        "labels": labels,
        "neto": serie_neto,
        "pedidos": serie_pedidos,
        "gran": gran,
        "rango": rango,
        "desde": str(desde) if desde else "",
        "hasta": str(hasta) if hasta else "",
        "global_labels": global_labels,
        "global_neto": global_neto,
        "global_pedidos": global_pedidos,
    }

    # Ranking por neto total acumulado (hasta la fecha)
    ranking_qs = (
        Venta.objects.values("vendedor_id", "vendedor__codigo", "vendedor__apellido", "vendedor__nombre")
        .annotate(neto_total=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))))
        .order_by("-neto_total", "vendedor__apellido", "vendedor__nombre")
    )
    ranking = list(ranking_qs[:50])
    pos = None
    for i, r in enumerate(ranking, start=1):
        if int(r["vendedor_id"]) == int(vendedor.pk):
            pos = i
            break

    return render(
        request,
        "vendedor_portal/reportes.html",
        {
            "vendedor": vendedor,
            "actividad": actividad,
            "ranking": ranking,
            "posicion": pos,
            "chart": chart,
        },
    )

