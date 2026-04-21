from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from calendario.models import Evento
from caja.models import MovimientoCaja
from core.authz import is_staff_user, staff_required
from core.export_utils import parse_export, pdf_response, xlsx_response
from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_dashboard, rango_periodo
from personas.models import Proveedor
from productos.models import Producto

from .forms import CompraRegistrarForm
from .models import Compra
from .servicios import compra_anular_por_admin, compra_eliminar_por_admin


def _filtrar_compras_queryset(request):
    periodo = (request.GET.get("periodo") or "").strip()
    if periodo in ("7d", "30d", "mes", "mes_ant"):
        fecha_desde, fecha_hasta = rango_periodo(periodo)
    else:
        fecha_desde = parse_fecha_dashboard(request.GET.get("fecha_desde"))
        fecha_hasta = parse_fecha_dashboard(request.GET.get("fecha_hasta"))

    qs = (
        Compra.objects.select_related(
            "proveedor", "producto", "movimiento_caja", "movimiento_credito"
        )
        .order_by("-creado_en", "-id")
    )
    if fecha_desde:
        qs = qs.filter(fecha_compra__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_compra__lte=fecha_hasta)

    prid = (request.GET.get("proveedor") or "").strip()
    if prid.isdigit():
        qs = qs.filter(proveedor_id=int(prid))

    pid = (request.GET.get("producto") or "").strip()
    if pid.isdigit():
        qs = qs.filter(producto_id=int(pid))

    return qs, {
        "periodo": periodo,
        "fecha_desde": fecha_filtro_value_iso(request.GET.get("fecha_desde")),
        "fecha_hasta": fecha_filtro_value_iso(request.GET.get("fecha_hasta")),
        "proveedor": prid,
        "producto": pid,
    }


@login_required
def compra_historial(request):
    compras, filtros_ctx = _filtrar_compras_queryset(request)
    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = [
            "Compra",
            "Fecha compra",
            "Proveedor",
            "Producto",
            "Cantidad",
            "Costo u.",
            "Monto",
            "Medio pago",
            "Anulada",
            "Registro",
        ]
        rows = []
        for c in compras:
            rows.append(
                [
                    c.pk,
                    c.fecha_compra.strftime("%d/%m/%Y"),
                    str(c.proveedor),
                    f"{c.producto.codigo} {c.producto.descripcion}"[:80],
                    c.cantidad,
                    str(c.costo_unitario),
                    str(c.monto),
                    c.get_medio_pago_display(),
                    "Sí" if c.anulada else "No",
                    c.creado_en.strftime("%d/%m/%Y %H:%M"),
                ]
            )
        if exp == "xlsx":
            return xlsx_response("compras", [("Compras", headers, rows)])
        return pdf_response("compras", "Historial de compras", [("Compras", headers, rows)])

    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(compras, 80)
    page_obj = paginator.get_page(page or 1)
    compras_page = list(page_obj)

    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    querystring = qcopy.urlencode()

    productos = Producto.objects.filter(habilitado=True).order_by("descripcion", "codigo")
    proveedores = Proveedor.objects.order_by("apellido", "nombre", "codigo")
    return render(
        request,
        "compras/historial.html",
        {
            "compras": compras_page,
            "filtros": filtros_ctx,
            "productos_filtro": productos,
            "proveedores_filtro": proveedores,
            "es_admin_compras": is_staff_user(request.user),
            "page_obj": page_obj,
            "querystring": querystring,
        },
    )


@login_required
@staff_required
@require_http_methods(["POST"])
def compra_admin_eliminar(request, pk: int):
    compra = get_object_or_404(Compra, pk=pk)
    try:
        compra_eliminar_por_admin(compra, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages) if exc.messages else str(exc))
    else:
        messages.success(request, "Compra eliminada; movimientos de caja asociados y stock actualizados.")
    return redirect("compra_historial")


@login_required
@staff_required
@require_http_methods(["POST"])
def compra_admin_anular(request, pk: int):
    compra = get_object_or_404(Compra, pk=pk)
    try:
        compra_anular_por_admin(compra, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages) if exc.messages else str(exc))
    else:
        messages.success(
            request,
            "Compra anulada. Quedó registrada la nota de crédito en caja (ingreso que compensa el egreso).",
        )
    return redirect("compra_historial")


@login_required
@require_http_methods(["GET", "POST"])
def compra_registrar(request):
    if request.method == "POST":
        form = CompraRegistrarForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                with transaction.atomic():
                    producto = Producto(
                        descripcion=cd["nombre_producto"].strip(),
                        tipo=cd["tipo_producto"],
                        costo=cd["costo_unitario"],
                        stock=cd["cantidad"],
                        fecha_vencimiento=cd.get("fecha_vencimiento_pedido"),
                    )
                    producto.save()

                    cb = cd.get("cuenta_bancaria")
                    mov = MovimientoCaja(
                        fecha=cd["fecha_compra"],
                        operacion=f"Compra {cd['proveedor']} — {producto.codigo} {producto.descripcion[:40]}",
                        tipo=MovimientoCaja.Tipo.EGRESO,
                        monto=cd["monto"],
                        medio_pago=cd["medio_pago"],
                        banco=(cd.get("banco") or "").strip(),
                        numero_cheque=(cd.get("numero_cheque") or "").strip(),
                        fecha_vencimiento_cheque=cd.get("fecha_vencimiento_cheque"),
                        cuenta_bancaria=cb if cb else None,
                        creado_por=request.user,
                        actualizado_por=request.user,
                    )
                    mov.full_clean()
                    mov.save()

                    compra = Compra.objects.create(
                        proveedor=cd["proveedor"],
                        producto=producto,
                        fecha_compra=cd["fecha_compra"],
                        fecha_vencimiento_pedido=cd.get("fecha_vencimiento_pedido"),
                        cantidad=cd["cantidad"],
                        costo_unitario=cd["costo_unitario"],
                        monto=cd["monto"],
                        medio_pago=cd["medio_pago"],
                        banco=mov.banco,
                        numero_cheque=mov.numero_cheque,
                        fecha_vencimiento_cheque=mov.fecha_vencimiento_cheque,
                        movimiento_caja=mov,
                        creado_por=request.user,
                        actualizado_por=request.user,
                    )

                    if cd.get("fecha_vencimiento_pedido"):
                        Evento.objects.create(
                            fecha=cd["fecha_vencimiento_pedido"],
                            titulo=f"Vencimiento compra — {producto.codigo}",
                            tipo=Evento.Tipo.COMPRA,
                            descripcion=(
                                f"Proveedor: {cd['proveedor']}. Producto: {producto.descripcion}. "
                                f"Pedido/compra #{compra.pk}. Cantidad: {cd['cantidad']}."
                            ),
                        )
            except ValidationError as exc:
                msgs = []
                if getattr(exc, "error_dict", None):
                    for lst in exc.error_dict.values():
                        msgs.extend(str(m) for m in lst)
                else:
                    msgs = [str(m) for m in exc.messages]
                messages.error(request, " ".join(msgs) if msgs else str(exc))
                return render(request, "compras/registrar.html", {"form": form})
            except DatabaseError as exc:
                messages.error(request, f"Error al guardar en la base de datos: {exc}")
                return render(request, "compras/registrar.html", {"form": form})

            messages.success(
                request,
                f"Compra registrada. Producto creado con código {producto.codigo}. Egreso en caja #{mov.pk}.",
            )
            return redirect("compra_historial")
    else:
        form = CompraRegistrarForm(
            initial={
                "fecha_compra": datetime.now().strftime("%Y-%m-%d"),
                "medio_pago": MovimientoCaja.MedioPago.EFECTIVO,
            }
        )

    return render(request, "compras/registrar.html", {"form": form})
