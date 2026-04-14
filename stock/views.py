from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from core.export_utils import parse_export, pdf_response, xlsx_response

from productos.models import Producto

from .forms import MovimientoStockForm
from .models import MovimientoStock


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
                    Producto.objects.filter(pk=p.pk).update(stock=F("stock") + delta)

                    messages.success(request, f"Stock actualizado ({mov.get_tipo_display()}): {p.codigo} ({delta:+d})")
                    return redirect("stock_home")
    else:
        form = MovimientoStockForm()

    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        productos_qs = Producto.objects.all().order_by("descripcion", "codigo")
        hp = ["Código", "Descripción", "Tipo", "Stock", "Costo", "Precio venta"]
        rp = [
            [
                p.codigo,
                p.descripcion,
                p.get_tipo_display(),
                p.stock,
                str(p.costo),
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

    productos = Producto.objects.all().order_by("descripcion", "codigo")
    movimientos = MovimientoStock.objects.select_related("producto", "usuario").all()[:30]

    return render(
        request,
        "stock/home.html",
        {"form": form, "productos": productos, "movimientos": movimientos},
    )

