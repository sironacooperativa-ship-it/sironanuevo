from __future__ import annotations

from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from personas.models import Comprador, Vendedor
from personas.forms import CompradorForm
from presupuestos.models import Presupuesto, PresupuestoLinea
from presupuestos.views import _lineas_presupuesto_desde_post, _productos_payload, _validar_lineas_post
from productos.models import ListaPrecios, Producto
from core.money_decimal import format_monto_ars
from core.pdf_membrete import platypus_membrete
from ventas.models import Venta
from caja.models import MovimientoCaja

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

def _get_vendedor_from_user(user) -> Vendedor | None:
    if not user or not user.is_authenticated:
        return None
    v = getattr(user, "vendedor_perfil", None)
    return v if isinstance(v, Vendedor) else None


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
        comprador = Comprador.objects.filter(pk=int(comprador_id_raw), habilitado=True).first()

    mis_clientes = list(
        Comprador.objects.filter(habilitado=True, vendedor_asignado_id=vendedor.pk)
        .order_by("apellido", "nombre", "codigo")[:500]
    )

    # Buscar clientes (si hay texto y todavía no eligieron uno)
    candidatos = []
    if q and comprador is None:
        candidatos = (
            Comprador.objects.filter(habilitado=True)
            .filter(apellido__icontains=q)
            .order_by("apellido", "nombre", "codigo")[:15]
        )
        if not candidatos:
            candidatos = (
                Comprador.objects.filter(habilitado=True)
                .filter(nombre__icontains=q)
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

    productos_catalogo = _productos_payload()
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
                for prod, qty, pu, st in line_specs:
                    PresupuestoLinea.objects.create(
                        presupuesto=pr,
                        producto=prod,
                        cantidad=qty,
                        precio_unitario=pu,
                        subtotal=st,
                    )
            messages.success(request, f"Presupuesto #{pr.pk} guardado.")
            return redirect(f"{redirect('vendedor_home').url}?comprador={comprador.pk}")

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
            "lineas_iniciales": lineas_iniciales,
            "repoblar": repoblar,
        },
    )


@login_required
def vendedor_clientes_list(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    q = (request.GET.get("q") or "").strip()
    qs = Comprador.objects.all().order_by("apellido", "nombre", "codigo")
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


_LISTAS_FIJAS: list[dict] = [
    {"slug": "farmacias", "nombre": "Farmacias"},
    {"slug": "kioscos", "nombre": "Kioscos"},
    {"slug": "almacenes-y-supermercados", "nombre": "Almacenes y supermercados"},
    {"slug": "sexshop", "nombre": "SexShop"},
]


def _lista_nombre_por_slug(slug: str) -> str | None:
    s = (slug or "").strip().lower()
    for it in _LISTAS_FIJAS:
        if it["slug"] == s:
            return it["nombre"]
    return None


def _get_lista_precios_por_slug(slug: str) -> ListaPrecios | None:
    nombre = _lista_nombre_por_slug(slug)
    if not nombre:
        return None
    return ListaPrecios.objects.filter(nombre=nombre).first()


def _productos_lista_precios(lista: ListaPrecios) -> list[Producto]:
    return list(
        lista.productos.filter(habilitado=True).order_by("descripcion", "codigo").all()
    )


def _build_lista_precios_pdf(*, titulo: str, productos: list[Producto]) -> HttpResponse:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    story = platypus_membrete(titulo, doc.width, styles)

    headers = ["Código", "Descripción", "Precio"]
    data = [headers]
    for p in productos:
        desc = p.descripcion
        if len(desc) > 110:
            desc = desc[:107] + "..."
        data.append([p.codigo, desc, format_monto_ars(p.precio_venta)])

    if len(data) == 1:
        data.append(["—", "—", "—"])

    tw = doc.width
    col_w = [tw * 0.16, tw * 0.58, tw * 0.26]
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0097B2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f9fb")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 1), (0, -1), "LEFT"),
                ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    story.append(t)
    doc.build(story)
    buffer.seek(0)

    fecha = timezone.localtime().strftime("%d-%m-%Y")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in titulo)[:60]
    filename = f"{safe}_{fecha}.pdf"
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type="application/pdf")


@login_required
def vendedor_listas(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    items = []
    for it in _LISTAS_FIJAS:
        lista = ListaPrecios.objects.filter(nombre=it["nombre"]).first()
        items.append(
            {
                **it,
                "existe": bool(lista),
                "cantidad": lista.productos.count() if lista else 0,
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
    productos = _productos_lista_precios(lista)
    return _build_lista_precios_pdf(titulo=f"Lista de precios — {lista.nombre}", productos=productos)


@login_required
def vendedor_lista_png(request, slug: str):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

    lista = _get_lista_precios_por_slug(slug)
    if lista is None:
        return HttpResponseBadRequest("Lista no válida o no configurada.")
    productos = _productos_lista_precios(lista)
    payload = [
        {"codigo": p.codigo, "descripcion": p.descripcion, "precio": format_monto_ars(p.precio_venta)}
        for p in productos
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


@login_required
def vendedor_cuenta_corriente(request):
    vendedor = _get_vendedor_from_user(request.user)
    if vendedor is None:
        return HttpResponseForbidden("Este usuario no tiene perfil de vendedor.")

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
        default=Value(0),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    mis_ventas = Venta.objects.filter(vendedor_id=vendedor.pk)
    actividad = mis_ventas.aggregate(
        pedidos=Count("id"),
        neto_total=Coalesce(Sum(neto_nonneg), Value(0)),
    )

    # Ranking por neto total acumulado (hasta la fecha)
    ranking_qs = (
        Venta.objects.values("vendedor_id", "vendedor__codigo", "vendedor__apellido", "vendedor__nombre")
        .annotate(neto_total=Coalesce(Sum(neto_nonneg), Value(0)))
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
        {"vendedor": vendedor, "actividad": actividad, "ranking": ranking, "posicion": pos},
    )

