from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from calendario.models import Evento
from caja.models import MovimientoCaja
from core.export_utils import parse_export, pdf_response, xlsx_response
from core.fecha_filtros import parse_fecha_dashboard, rango_periodo
from personas.models import Proveedor
from productos.models import Producto

from .forms import CompraRegistrarForm
from .models import Compra


def _filtrar_compras_queryset(request):
    periodo = (request.GET.get("periodo") or "").strip()
    if periodo in ("7d", "30d", "mes", "mes_ant"):
        fecha_desde, fecha_hasta = rango_periodo(periodo)
    else:
        fecha_desde = parse_fecha_dashboard(request.GET.get("fecha_desde"))
        fecha_hasta = parse_fecha_dashboard(request.GET.get("fecha_hasta"))

    qs = (
        Compra.objects.select_related("proveedor", "producto", "movimiento_caja")
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
        "fecha_desde": (request.GET.get("fecha_desde") or "").strip(),
        "fecha_hasta": (request.GET.get("fecha_hasta") or "").strip(),
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
                    c.creado_en.strftime("%d/%m/%Y %H:%M"),
                ]
            )
        if exp == "xlsx":
            return xlsx_response("compras", [("Compras", headers, rows)])
        return pdf_response("compras", "Historial de compras", [("Compras", headers, rows)])

    productos = Producto.objects.filter(habilitado=True).order_by("codigo")
    proveedores = Proveedor.objects.order_by("apellido", "nombre", "codigo")
    return render(
        request,
        "compras/historial.html",
        {
            "compras": compras,
            "filtros": filtros_ctx,
            "productos_filtro": productos,
            "proveedores_filtro": proveedores,
        },
    )


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
                        fecha_vencimiento=cd["fecha_vencimiento_pedido"],
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
                        fecha_vencimiento_pedido=cd["fecha_vencimiento_pedido"],
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
                "fecha_compra": datetime.now().strftime("%d/%m/%y"),
                "medio_pago": MovimientoCaja.MedioPago.EFECTIVO,
            }
        )

    return render(request, "compras/registrar.html", {"form": form})
