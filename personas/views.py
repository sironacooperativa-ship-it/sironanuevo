from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.comision_agg import comisiones_acumuladas_por_mes, comisiones_vendedor_con_grupo_por_mes
from core.export_utils import parse_export, pdf_response, xlsx_response
from core.authz import staff_required
from core.authz import is_staff_user

from caja.models import MovimientoCaja
from presupuestos.models import Presupuesto
from ventas.models import Venta

from .forms import CompradorForm, ProveedorForm, VendedorForm
from .models import Comprador, Proveedor, Vendedor
from .services import eliminar_vendedor_y_historial_admin, resumen_historial_vendedor


def _es_staff(user) -> bool:
    # Legacy helper (usado en 1-2 lugares). Preferir `core.authz.is_staff_user`.
    return is_staff_user(user)


@login_required
def vendedores_list(request):
    vendedores = (
        Vendedor.objects.annotate(
            nv=Count("ventas"),
            np=Count("presupuestos"),
            nc=Count("movimientocaja"),
        )
        .order_by("apellido", "nombre")
    )
    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = [
            "Código",
            "Apellido",
            "Nombre",
            "DNI",
            "Teléfono",
            "Mail",
            "Dirección",
            "Comisión %",
            "A cargo de grupo",
            "Comisión grupo %",
        ]
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
                "Sí" if v.es_jefe_grupo else "No",
                str(v.comision_grupo_porcentaje),
            ]
            for v in vendedores
        ]
        if exp == "xlsx":
            return xlsx_response("vendedores", [("Vendedores", headers, rows)])
        return pdf_response("vendedores", "Vendedores", [("Vendedores", headers, rows)])
    return render(request, "personas/vendedores_list.html", {"vendedores": vendedores})


@login_required
def vendedor_ficha(request, pk: int):
    """Ficha de datos del vendedor; con ?modal=1 devuelve HTML para el popup del listado."""
    v = get_object_or_404(Vendedor.objects.select_related("usuario"), pk=pk)
    if request.GET.get("modal") == "1":
        return render(request, "personas/vendedor_ficha_fragment.html", {"vendedor": v})
    return render(request, "personas/vendedor_ficha_standalone.html", {"vendedor": v})


@login_required
def vendedor_detalle(request, pk: int):
    v = get_object_or_404(Vendedor, pk=pk)
    page = (request.GET.get("page") or "").strip()
    ventas_qs = (
        Venta.objects.filter(vendedor=v)
        .select_related("comprador", "pago_movimiento")
        .prefetch_related("lineas__producto")
        .order_by("-creado_en", "-id")
    )
    paginator = Paginator(ventas_qs, 80)
    page_obj = paginator.get_page(page or 1)
    ventas = list(page_obj)
    vendedores_a_cargo = list(v.vendedores_a_cargo.filter(habilitado=True).order_by("apellido", "nombre", "codigo"))
    ventas_grupo_qs = Venta.objects.none()
    if v.es_jefe_grupo and vendedores_a_cargo:
        ventas_grupo_qs = Venta.objects.filter(vendedor__in=vendedores_a_cargo)
    comisiones_por_mes = comisiones_acumuladas_por_mes(ventas_qs)
    comisiones_con_grupo_por_mes = comisiones_vendedor_con_grupo_por_mes(
        ventas_qs,
        ventas_grupo_qs,
        v.comision_grupo_porcentaje,
    )
    hist = resumen_historial_vendedor(v)
    tiene_historial = any(
        hist[k] > 0 for k in ("n_ventas", "n_presupuestos", "n_movimientos_caja")
    )
    return render(
        request,
        "personas/vendedor_detalle.html",
        {
            "vendedor": v,
            "ventas": ventas,
            "comisiones_por_mes": comisiones_por_mes,
            "comisiones_con_grupo_por_mes": comisiones_con_grupo_por_mes,
            "vendedores_a_cargo": vendedores_a_cargo,
            "ventas_grupo_qs": ventas_grupo_qs,
            "resumen_historial": hist,
            "tiene_historial": tiene_historial,
            "page_obj": page_obj,
        },
    )


@login_required
def vendedor_actividad(request, pk: int):
    """Clientes vinculados, pedidos y movimientos de caja que involucran al vendedor."""
    v = get_object_or_404(Vendedor, pk=pk)
    page_v = (request.GET.get("page_v") or "").strip()
    page_m = (request.GET.get("page_m") or "").strip()
    ids_en_pedidos = set(
        Venta.objects.filter(vendedor=v, comprador_id__isnull=False).values_list("comprador_id", flat=True)
    )
    ids_asignados = set(Comprador.objects.filter(vendedor_asignado=v).values_list("pk", flat=True))
    ids_clientes = ids_en_pedidos | ids_asignados
    filas_clientes: list[dict] = []
    if ids_clientes:
        for c in (
            Comprador.objects.filter(pk__in=ids_clientes)
            .select_related("vendedor_asignado")
            .order_by("apellido", "nombre", "codigo")
        ):
            filas_clientes.append(
                {
                    "comprador": c,
                    "asignado_a_este": c.vendedor_asignado_id == v.pk,
                    "en_pedidos": c.pk in ids_en_pedidos,
                }
            )

    ventas_qs = (
        Venta.objects.filter(vendedor=v)
        .select_related("comprador", "pago_movimiento")
        .order_by("-creado_en", "-id")
    )
    ventas_page = Paginator(ventas_qs, 80).get_page(page_v or 1)

    movs_qs = (
        MovimientoCaja.objects.filter(vendedor=v)
        .select_related("venta", "cuenta_bancaria")
        .order_by("-fecha", "-creado_en", "-id")
    )
    movs_page = Paginator(movs_qs, 80).get_page(page_m or 1)
    return render(
        request,
        "personas/vendedor_actividad.html",
        {
            "vendedor": v,
            "filas_clientes": filas_clientes,
            "ventas": list(ventas_page),
            "movimientos": list(movs_page),
            "ventas_page": ventas_page,
            "movs_page": movs_page,
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


@staff_required
@require_http_methods(["POST"])
def vendedor_delete(request, pk: int):
    v = get_object_or_404(Vendedor, pk=pk)
    tiene_historial = (
        v.ventas.exists()
        or v.presupuestos.exists()
        or v.movimientocaja_set.exists()
    )
    if tiene_historial:
        if _es_staff(request.user):
            return redirect("vendedor_eliminar_admin", pk=pk)
        messages.error(
            request,
            f"No se puede eliminar {v.codigo} porque tiene historial asociado. Usá 'Inhabilitar'.",
        )
        return redirect("vendedores_list")
    codigo = v.codigo
    v.delete()
    messages.success(request, f"Vendedor eliminado: {codigo}")
    return redirect("vendedores_list")


@staff_required
@require_http_methods(["GET", "POST"])
def vendedor_eliminar_admin(request, pk: int):
    v = get_object_or_404(Vendedor, pk=pk)
    resumen = resumen_historial_vendedor(v)
    ventas_muestra = (
        Venta.objects.filter(vendedor=v)
        .select_related("comprador")
        .order_by("-creado_en")[:50]
    )
    presupuestos_muestra = (
        Presupuesto.objects.filter(vendedor=v).order_by("-creado_en")[:50]
    )

    if request.method == "POST":
        try:
            codigo = eliminar_vendedor_y_historial_admin(v)
        except Exception as exc:
            detalle = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
            messages.error(request, "No se pudo eliminar al vendedor." + detalle)
            return redirect("vendedores_list")
        messages.success(
            request,
            f"Vendedor {codigo} eliminado junto con pedidos, presupuestos y movimientos de caja vinculados.",
        )
        return redirect("vendedores_list")

    return render(
        request,
        "personas/vendedor_eliminar_admin.html",
        {
            "vendedor": v,
            "resumen": resumen,
            "ventas_muestra": ventas_muestra,
            "presupuestos_muestra": presupuestos_muestra,
        },
    )


@staff_required
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


@staff_required
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


@staff_required
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
    vid = (request.GET.get("vendedor") or "").strip()
    compradores = Comprador.objects.select_related("vendedor_asignado").order_by("apellido", "nombre")
    if vid.isdigit():
        compradores = compradores.filter(vendedor_asignado_id=int(vid))
    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = ["Código", "Apellido", "Nombre", "Vendedor asignado", "Dirección"]
        rows = [
            [
                c.codigo,
                c.apellido,
                c.nombre,
                str(c.vendedor_asignado) if c.vendedor_asignado_id else "",
                c.direccion,
            ]
            for c in compradores
        ]
        if exp == "xlsx":
            return xlsx_response("compradores", [("Compradores", headers, rows)])
        return pdf_response("compradores", "Compradores", [("Compradores", headers, rows)])
    vendedores_filtro = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
    return render(
        request,
        "personas/compradores_list.html",
        {"compradores": compradores, "vendedores_filtro": vendedores_filtro, "f": {"vendedor": vid}},
    )


@login_required
def comprador_ficha(request, pk: int):
    """Ficha de datos del cliente; con ?modal=1 devuelve HTML para el popup del listado."""
    c = get_object_or_404(
        Comprador.objects.select_related("vendedor_asignado"),
        pk=pk,
    )
    ventas = list(
        Venta.objects.filter(comprador_id=c.pk)
        .select_related("vendedor", "pago_movimiento")
        .order_by("-creado_en", "-id")[:250]
    )
    pagos = list(
        MovimientoCaja.objects.filter(venta__comprador_id=c.pk)
        .select_related("venta", "cuenta_bancaria")
        .order_by("-fecha", "-id")[:250]
    )
    if request.GET.get("modal") == "1":
        return render(
            request,
            "personas/comprador_ficha_fragment.html",
            {"comprador": c, "ventas": ventas, "pagos": pagos},
        )
    return render(
        request,
        "personas/comprador_ficha_standalone.html",
        {"comprador": c, "ventas": ventas, "pagos": pagos},
    )


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


@staff_required
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


@staff_required
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

