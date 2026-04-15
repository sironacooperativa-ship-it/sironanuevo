from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.comision_agg import comisiones_acumuladas_por_mes
from core.export_utils import parse_export, pdf_response, xlsx_response

from ventas.models import Venta

from .forms import CompradorForm, ProveedorForm, VendedorForm
from .models import Comprador, Proveedor, Vendedor


@login_required
def vendedores_list(request):
    vendedores = Vendedor.objects.all().order_by("apellido", "nombre")
    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = ["Código", "Apellido", "Nombre", "DNI", "Teléfono", "Mail", "Dirección", "Comisión %"]
        rows = [
            [
                v.codigo,
                v.apellido,
                v.nombre,
                v.dni,
                v.telefono,
                v.mail,
                v.direccion,
                str(v.comision_porcentaje),
            ]
            for v in vendedores
        ]
        if exp == "xlsx":
            return xlsx_response("vendedores", [("Vendedores", headers, rows)])
        return pdf_response("vendedores", "Vendedores", [("Vendedores", headers, rows)])
    return render(request, "personas/vendedores_list.html", {"vendedores": vendedores})


@login_required
def vendedor_detalle(request, pk: int):
    v = get_object_or_404(Vendedor, pk=pk)
    ventas_qs = (
        Venta.objects.filter(vendedor=v)
        .select_related("comprador", "pago_movimiento")
        .prefetch_related("lineas__producto")
        .order_by("-creado_en", "-id")
    )
    ventas = list(ventas_qs[:400])
    comisiones_por_mes = comisiones_acumuladas_por_mes(ventas_qs)
    return render(
        request,
        "personas/vendedor_detalle.html",
        {
            "vendedor": v,
            "ventas": ventas,
            "comisiones_por_mes": comisiones_por_mes,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def vendedor_create(request):
    if request.method == "POST":
        form = VendedorForm(request.POST)
        if form.is_valid():
            v = form.save()
            messages.success(request, f"Vendedor creado: {v.codigo}")
            return redirect("vendedores_list")
    else:
        form = VendedorForm()
    return render(request, "personas/vendedor_form.html", {"form": form, "modo": "nuevo"})


@login_required
@require_http_methods(["GET", "POST"])
def vendedor_update(request, pk: int):
    v = get_object_or_404(Vendedor, pk=pk)
    if request.method == "POST":
        form = VendedorForm(request.POST, instance=v)
        if form.is_valid():
            v = form.save()
            messages.success(request, f"Vendedor actualizado: {v.codigo}")
            return redirect("vendedores_list")
    else:
        form = VendedorForm(instance=v)
    return render(
        request, "personas/vendedor_form.html", {"form": form, "modo": "editar", "vendedor": v}
    )


@login_required
@require_http_methods(["POST"])
def vendedor_delete(request, pk: int):
    v = get_object_or_404(Vendedor, pk=pk)
    # No borrar si hay historial asociado: preserva integridad del sistema.
    tiene_historial = (
        v.ventas.exists()
        or v.presupuestos.exists()
        or v.movimientocaja_set.exists()
    )
    if tiene_historial:
        messages.error(
            request,
            f"No se puede eliminar {v.codigo} porque tiene historial asociado. Usá 'Inhabilitar'.",
        )
        return redirect("vendedores_list")
    codigo = v.codigo
    v.delete()
    messages.success(request, f"Vendedor eliminado: {codigo}")
    return redirect("vendedores_list")


@login_required
@require_http_methods(["POST"])
def vendedor_toggle(request, pk: int):
    v = get_object_or_404(Vendedor, pk=pk)
    v.habilitado = not v.habilitado
    v.save(update_fields=["habilitado"])
    messages.success(
        request,
        f"Vendedor {v.codigo}: {'habilitado' if v.habilitado else 'inhabilitado'}.",
    )
    return redirect("vendedores_list")


@login_required
def proveedores_list(request):
    proveedores = Proveedor.objects.all().order_by("apellido", "nombre")
    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = ["Código", "Apellido", "Nombre", "DNI", "Teléfono", "Mail", "Dirección"]
        rows = [
            [p.codigo, p.apellido, p.nombre, p.dni, p.telefono, p.mail, p.direccion]
            for p in proveedores
        ]
        if exp == "xlsx":
            return xlsx_response("proveedores", [("Proveedores", headers, rows)])
        return pdf_response("proveedores", "Proveedores", [("Proveedores", headers, rows)])
    return render(request, "personas/proveedores_list.html", {"proveedores": proveedores})


@login_required
@require_http_methods(["GET", "POST"])
def proveedor_create(request):
    if request.method == "POST":
        form = ProveedorForm(request.POST)
        if form.is_valid():
            p = form.save()
            messages.success(request, f"Proveedor creado: {p.codigo}")
            return redirect("proveedores_list")
    else:
        form = ProveedorForm()
    return render(request, "personas/proveedor_form.html", {"form": form, "modo": "nuevo"})


@login_required
@require_http_methods(["GET", "POST"])
def proveedor_update(request, pk: int):
    p = get_object_or_404(Proveedor, pk=pk)
    if request.method == "POST":
        form = ProveedorForm(request.POST, instance=p)
        if form.is_valid():
            p = form.save()
            messages.success(request, f"Proveedor actualizado: {p.codigo}")
            return redirect("proveedores_list")
    else:
        form = ProveedorForm(instance=p)
    return render(
        request, "personas/proveedor_form.html", {"form": form, "modo": "editar", "proveedor": p}
    )


@login_required
@require_http_methods(["POST"])
def proveedor_delete(request, pk: int):
    p = get_object_or_404(Proveedor, pk=pk)
    if p.compras.exists():
        messages.error(
            request,
            f"No se puede eliminar {p.codigo} porque tiene compras asociadas. Usá 'Inhabilitar'.",
        )
        return redirect("proveedores_list")
    codigo = p.codigo
    p.delete()
    messages.success(request, f"Proveedor eliminado: {codigo}")
    return redirect("proveedores_list")


@login_required
@require_http_methods(["POST"])
def proveedor_toggle(request, pk: int):
    p = get_object_or_404(Proveedor, pk=pk)
    p.habilitado = not p.habilitado
    p.save(update_fields=["habilitado"])
    messages.success(
        request,
        f"Proveedor {p.codigo}: {'habilitado' if p.habilitado else 'inhabilitado'}.",
    )
    return redirect("proveedores_list")


@login_required
def compradores_list(request):
    compradores = Comprador.objects.all().order_by("apellido", "nombre")
    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = ["Código", "Apellido", "Nombre", "DNI", "Teléfono", "Mail", "Dirección"]
        rows = [
            [c.codigo, c.apellido, c.nombre, c.dni, c.telefono, c.mail, c.direccion]
            for c in compradores
        ]
        if exp == "xlsx":
            return xlsx_response("compradores", [("Compradores", headers, rows)])
        return pdf_response("compradores", "Compradores", [("Compradores", headers, rows)])
    return render(request, "personas/compradores_list.html", {"compradores": compradores})


@login_required
@require_http_methods(["GET", "POST"])
def comprador_create(request):
    if request.method == "POST":
        form = CompradorForm(request.POST)
        if form.is_valid():
            c = form.save()
            messages.success(request, f"Comprador creado: {c.codigo}")
            return redirect("compradores_list")
    else:
        form = CompradorForm()
    return render(request, "personas/comprador_form.html", {"form": form, "modo": "nuevo"})


@login_required
@require_http_methods(["GET", "POST"])
def comprador_update(request, pk: int):
    c = get_object_or_404(Comprador, pk=pk)
    if request.method == "POST":
        form = CompradorForm(request.POST, instance=c)
        if form.is_valid():
            c = form.save()
            messages.success(request, f"Comprador actualizado: {c.codigo}")
            return redirect("compradores_list")
    else:
        form = CompradorForm(instance=c)
    return render(
        request, "personas/comprador_form.html", {"form": form, "modo": "editar", "comprador": c}
    )


@login_required
@require_http_methods(["POST"])
def comprador_delete(request, pk: int):
    c = get_object_or_404(Comprador, pk=pk)
    if c.ventas.exists() or c.presupuestos.exists():
        messages.error(
            request,
            f"No se puede eliminar {c.codigo} porque tiene historial asociado. Usá 'Inhabilitar'.",
        )
        return redirect("compradores_list")
    codigo = c.codigo
    c.delete()
    messages.success(request, f"Comprador eliminado: {codigo}")
    return redirect("compradores_list")


@login_required
@require_http_methods(["POST"])
def comprador_toggle(request, pk: int):
    c = get_object_or_404(Comprador, pk=pk)
    c.habilitado = not c.habilitado
    c.save(update_fields=["habilitado"])
    messages.success(
        request,
        f"Comprador {c.codigo}: {'habilitado' if c.habilitado else 'inhabilitado'}.",
    )
    return redirect("compradores_list")

