from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Cast, Coalesce
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from core.authz import staff_required
from core.export_utils import parse_export, pdf_response, xlsx_response

from productos.models import Producto
from personas.models import Proveedor

from .forms import MovimientoStockForm
from .models import MovimientoStock


def _stock_productos_queryset(request):
    """Listado de productos para la tabla de stock (todos los saldos; filtro opcional por q)."""
    q = (request.GET.get("q") or "").strip()
    tipo = (request.GET.get("tipo") or "").strip()
    proveedor = (request.GET.get("proveedor") or "").strip()
    estado = (request.GET.get("estado") or "").strip()
    # Prefetch proveedor (vía compras) para mostrar "Marca" sin N+1.
    qs = Producto.objects.all().prefetch_related("compras_origen__proveedor").order_by("descripcion", "codigo")
    if q:
        qs = qs.filter(Q(descripcion__icontains=q) | Q(codigo__icontains=q))
    if tipo:
        qs = qs.filter(tipo=tipo)
    if proveedor.isdigit():
        qs = qs.filter(compras_origen__proveedor_id=int(proveedor)).distinct()
    if estado == "1":
        qs = qs.filter(habilitado=True)
    elif estado == "0":
        qs = qs.filter(habilitado=False)
    return qs, {"q": q, "tipo": tipo, "proveedor": proveedor, "estado": estado}


@staff_required
@require_http_methods(["POST"])
def stock_ajuste_inline(request):
    """Actualiza el stock disponible a mano; persiste en el producto y aplica reglas de habilitado/lista."""
    raw_id = (request.POST.get("producto_id") or "").strip()
    raw_stock = (request.POST.get("stock") or "").strip().replace(",", ".")
    retorno_q = (request.POST.get("retorno_q") or "").strip()

    def _redirect_stock():
        url = reverse("stock_home")
        if retorno_q:
            url += "?" + urlencode({"q": retorno_q})
        return redirect(url)

    if not raw_id.isdigit():
        messages.error(request, "Producto no válido.")
        return _redirect_stock()
    try:
        new_stock = int(float(raw_stock))
    except (ValueError, TypeError, OverflowError):
        messages.error(request, "El stock indicado no es válido.")
        return _redirect_stock()
    if new_stock < 0:
        messages.error(request, "El stock no puede ser negativo.")
        return _redirect_stock()

    try:
        with transaction.atomic():
            p = Producto.objects.select_for_update().get(pk=int(raw_id))
            prev = p.stock
            p.stock = new_stock
            p.save()
    except Producto.DoesNotExist:
        messages.error(request, "Producto no encontrado.")
        return _redirect_stock()

    if prev != new_stock:
        messages.success(
            request,
            f"Stock actualizado: {p.codigo} — {prev} → {new_stock} unidades.",
        )
    else:
        messages.info(request, f"Sin cambios de stock para {p.codigo}.")
    return _redirect_stock()


@login_required
@require_http_methods(["GET", "POST"])
def stock_home(request):
    if request.method == "POST":
        form = MovimientoStockForm(request.POST)
        if form.is_valid():
            producto: Producto = form.cleaned_data["producto"]
            tipo = form.cleaned_data["tipo"]
            cantidad = form.cleaned_data["cantidad"]

            with transaction.atomic():
                # Lock row to prevent races
                p = Producto.objects.select_for_update().get(pk=producto.pk)

                if tipo == MovimientoStock.Tipo.SALIDA and p.stock - cantidad < 0:
                    form.add_error("cantidad", "No hay stock suficiente para quitar esa cantidad.")
                else:
                    mov = MovimientoStock.objects.create(
                        producto=p,
                        tipo=tipo,
                        cantidad=cantidad,
                        numero_boleta=(form.cleaned_data.get("numero_boleta") or "").strip(),
                        proveedor=(form.cleaned_data.get("proveedor") or "").strip(),
                        numero_factura=(form.cleaned_data.get("numero_factura") or "").strip(),
                        destinatario=(form.cleaned_data.get("destinatario") or "").strip(),
                        usuario=request.user if request.user.is_authenticated else None,
                    )

                    delta = cantidad if tipo == MovimientoStock.Tipo.ENTRADA else -cantidad
                    stock_antes = p.stock
                    Producto.objects.filter(pk=p.pk).update(stock=F("stock") + delta)
                    stock_despues = stock_antes + delta
                    if stock_despues > 0 and stock_antes <= 0:
                        # Solo rehabilitamos venta; la lista Farmacia (PDF) se marca a mano en el producto.
                        Producto.objects.filter(pk=p.pk, stock__gt=0).update(habilitado=True)
                    Producto.deshabilitar_sin_stock([p.pk])

                    messages.success(request, f"Stock actualizado ({mov.get_tipo_display()}): {p.codigo} ({delta:+d})")
                    return redirect("stock_home")
    else:
        form = MovimientoStockForm()

    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        productos_qs, _ = _stock_productos_queryset(request)
        hp = ["Código", "Descripción", "Tipo", "Stock disponible", "Precio venta"]
        rp = [
            [
                p.codigo,
                p.descripcion,
                p.get_tipo_display(),
                p.stock,
                str(p.precio_venta),
            ]
            for p in productos_qs
        ]
        movs = list(
            MovimientoStock.objects.select_related("producto", "usuario").order_by("-creado_en", "-id")[:5000]
        )
        hm = ["Fecha/Hora", "Producto", "Tipo", "Cantidad", "Boleta", "Proveedor", "Factura", "Destinatario", "Usuario"]
        rm = []
        for mv in movs:
            rm.append(
                [
                    mv.creado_en.strftime("%d/%m/%Y %H:%M"),
                    mv.producto.descripcion,
                    mv.get_tipo_display(),
                    mv.cantidad,
                    mv.numero_boleta or "",
                    mv.proveedor or "",
                    mv.numero_factura or "",
                    mv.destinatario or "",
                    mv.usuario.get_username() if mv.usuario_id else "",
                ]
            )
        if exp == "xlsx":
            return xlsx_response("stock", [("Productos", hp, rp), ("Movimientos recientes", hm, rm)])
        return pdf_response(
            "stock",
            "Stock — productos y movimientos",
            [("Productos", hp, rp), ("Movimientos (últimos registros)", hm, rm)],
        )

    productos_qs, filtros = _stock_productos_queryset(request)
    productos_picker = list(
        Producto.objects.all()
        .order_by("descripcion", "codigo")
        .values("codigo", "descripcion")[:3000]
    )
    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(productos_qs, 120)
    page_obj = paginator.get_page(page or 1)
    productos = list(page_obj)
    for p in productos:
        try:
            p.valor_total_stock = (p.costo or 0) * (p.stock or 0)
        except Exception:
            p.valor_total_stock = 0
        # "Marca / Proveedor": mostrar un proveedor asociado por compras (si existe).
        try:
            pr = None
            for c in getattr(p, "compras_origen", []).all():
                if getattr(c, "proveedor_id", None):
                    pr = c.proveedor
                    break
            if pr:
                p.proveedor_marca = f"{pr.apellido}, {pr.nombre}".strip(", ")
            else:
                p.proveedor_marca = ""
        except Exception:
            p.proveedor_marca = ""
    movimientos = (
        MovimientoStock.objects.select_related("producto", "usuario")
        .order_by("-creado_en", "-id")[:30]
    )
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    querystring = qcopy.urlencode()

    # Django (v5+) exige tipos homogéneos en expresiones: `DecimalField * IntegerField` rompe.
    # Cast de stock a decimal para poder calcular el valor total.
    dec18_2 = DecimalField(max_digits=18, decimal_places=2)
    costo_dec = Coalesce(F("costo"), Value(0), output_field=dec18_2)
    stock_dec = Cast(Coalesce(F("stock"), Value(0)), dec18_2)
    valor_total_expr = ExpressionWrapper(costo_dec * stock_dec, output_field=dec18_2)
    kpi = productos_qs.aggregate(
        productos=Count("id"),
        activos=Count("id", filter=Q(habilitado=True)),
        stock_total=Coalesce(Sum("stock"), Value(0)),
        sin_stock=Count("id", filter=Q(stock__lte=0)),
        valor_total=Coalesce(Sum(valor_total_expr), Value(0), output_field=dec18_2),
    )

    template = "stock/home.html"
    if request.GET.get("modal") == "1":
        template = "stock/home_fragment.html"
    return render(
        request,
        template,
        {
            "form": form,
            "productos": productos,
            "movimientos": movimientos,
            "q": filtros["q"],
            "tipo": filtros["tipo"],
            "proveedor": filtros["proveedor"],
            "estado": filtros["estado"],
            "page_obj": page_obj,
            "querystring": querystring,
            "kpi": kpi,
            "productos_picker": productos_picker,
            "tipos": Producto.Tipo.choices,
            "proveedores_filtro": Proveedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo"),
        },
    )

