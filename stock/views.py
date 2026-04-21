from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from core.authz import staff_required
from core.export_utils import parse_export, pdf_response, xlsx_response

from productos.models import Producto

from .forms import MovimientoStockForm
from .models import MovimientoStock


def _stock_productos_queryset(request):
    """Listado de productos para la tabla de stock (todos los saldos; filtro opcional por q)."""
    q = (request.GET.get("q") or "").strip()
    qs = Producto.objects.all().order_by("descripcion", "codigo")
    if q:
        qs = qs.filter(Q(descripcion__icontains=q) | Q(codigo__icontains=q))
    return qs, q


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
                        Producto.objects.filter(pk=p.pk, stock__gt=0).update(
                            habilitado=True, en_lista_precios=True
                        )
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

    productos = list(_stock_productos_queryset(request)[0])
    movimientos = (
        MovimientoStock.objects.select_related("producto", "usuario")
        .order_by("-creado_en", "-id")[:30]
    )
    q = (request.GET.get("q") or "").strip()

    return render(
        request,
        "stock/home.html",
        {
            "form": form,
            "productos": productos,
            "movimientos": movimientos,
            "q": q,
        },
    )

