from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum, Case, When, F, Value, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.export_utils import parse_export, pdf_response, xlsx_response
from core.money_decimal import q2
from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_param
from personas.models import Vendedor
from ventas.models import Venta
from ventas.servicios import revertir_cobro_pedido_desde_movimiento_caja

from .forms import MovimientoCajaForm
from .models import MovimientoCaja


_MESES_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

# Libro diario (listado): filas por “hoja” en pantalla y en exportación.
_LIBRO_CAJA_FILAS_POR_HOJA = 30


def _libro_diario_rows_con_saldo(qs, delta_expr, movimientos_orden_visual: list[MovimientoCaja]) -> list[dict]:
    """
    `movimientos_orden_visual`: orden en pantalla (ej. más reciente primero).
    Cada fila lleva el saldo **después** de aplicar ese movimiento en el orden cronológico real.
    """
    if not movimientos_orden_visual:
        return []
    chrono = sorted(movimientos_orden_visual, key=lambda m: (m.fecha, m.pk))
    first = chrono[0]
    saldo_previo = (
        qs.filter(Q(fecha__lt=first.fecha) | Q(fecha=first.fecha, pk__lt=first.pk))
        .aggregate(
            s=Coalesce(
                Sum(delta_expr),
                Value(
                    Decimal("0.00"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
            )
        )
        .get("s")
        or Decimal("0.00")
    )
    saldo = q2(saldo_previo)
    by_id: dict[int, Decimal] = {}
    for m in chrono:
        saldo = q2(saldo + m.delta)
        by_id[m.pk] = saldo
    return [{"m": m, "saldo": by_id[m.pk]} for m in movimientos_orden_visual]


def _resumen_caja_dashboard(hoy: date) -> dict:
    """Saldo acumulado hasta hoy e ingresos/egresos del mes calendario (del 1.º al día indicado)."""
    ing_hasta = (
        MovimientoCaja.objects.filter(fecha__lte=hoy, tipo=MovimientoCaja.Tipo.INGRESO).aggregate(
            s=Sum("monto")
        )["s"]
        or Decimal("0.00")
    )
    egr_hasta = (
        MovimientoCaja.objects.filter(fecha__lte=hoy, tipo=MovimientoCaja.Tipo.EGRESO).aggregate(
            s=Sum("monto")
        )["s"]
        or Decimal("0.00")
    )
    saldo_al_dia = q2(ing_hasta - egr_hasta)

    inicio_mes = hoy.replace(day=1)
    ing_mes = (
        MovimientoCaja.objects.filter(
            fecha__gte=inicio_mes, fecha__lte=hoy, tipo=MovimientoCaja.Tipo.INGRESO
        ).aggregate(s=Sum("monto"))["s"]
        or Decimal("0.00")
    )
    egr_mes = (
        MovimientoCaja.objects.filter(
            fecha__gte=inicio_mes, fecha__lte=hoy, tipo=MovimientoCaja.Tipo.EGRESO
        ).aggregate(s=Sum("monto"))["s"]
        or Decimal("0.00")
    )
    return {
        "saldo_al_dia": saldo_al_dia,
        "ingresos_mes": q2(ing_mes),
        "egresos_mes": q2(egr_mes),
        "fecha_resumen": hoy,
        "mes_etiqueta": f"{_MESES_ES[hoy.month - 1]} {hoy.year}",
    }


@login_required
def caja_list(request):
    qs = MovimientoCaja.objects.select_related("vendedor", "cuenta_bancaria", "venta").all()

    q_operacion = (request.GET.get("operacion") or "").strip()
    tipo = (request.GET.get("tipo") or "").strip()
    medio_pago = (request.GET.get("medio_pago") or "").strip()
    vendedor = (request.GET.get("vendedor") or "").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()

    if q_operacion:
        qs = qs.filter(Q(operacion__icontains=q_operacion))
    if tipo:
        qs = qs.filter(tipo=tipo)
    if medio_pago:
        qs = qs.filter(medio_pago=medio_pago)
    if vendedor and vendedor.isdigit():
        qs = qs.filter(vendedor_id=int(vendedor))
    elif vendedor and not vendedor.isdigit():
        vendedor = ""

    d_desde = parse_fecha_param(desde) if desde else None
    d_hasta = parse_fecha_param(hasta) if hasta else None
    exp = parse_export(request)
    if d_desde:
        qs = qs.filter(fecha__gte=d_desde)
    if d_hasta:
        qs = qs.filter(fecha__lte=d_hasta)

    # Delta en DB para poder sumar sin traer todo.
    delta_expr = Case(
        When(tipo=MovimientoCaja.Tipo.INGRESO, then=F("monto")),
        default=ExpressionWrapper(Value(0) - F("monto"), output_field=DecimalField(max_digits=14, decimal_places=2)),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )

    movimientos_qs = qs.order_by("-fecha", "-id")
    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(movimientos_qs, _LIBRO_CAJA_FILAS_POR_HOJA)
    page_obj = paginator.get_page(page or 1)
    movimientos = list(page_obj)

    rows = _libro_diario_rows_con_saldo(qs, delta_expr, movimientos)

    ids_page = [r["m"].pk for r in rows]
    mov_ids_cobro_pedido: set[int] = set()
    if ids_page:
        mov_ids_cobro_pedido = set(
            Venta.objects.filter(pago_movimiento_id__in=ids_page).values_list("pago_movimiento_id", flat=True)
        )

    totales = qs.aggregate(total_ingreso=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.INGRESO)),
                           total_egreso=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.EGRESO)))
    totales = {
        "total_ingreso": q2(totales.get("total_ingreso")),
        "total_egreso": q2(totales.get("total_egreso")),
    }

    hoy = date.today()
    resumen_caja = _resumen_caja_dashboard(hoy)
    filtros_activos = any(
        (request.GET.get(k) or "").strip()
        for k in ("operacion", "tipo", "medio_pago", "vendedor", "desde", "hasta")
    )

    if exp in ("xlsx", "pdf"):
        movs_chrono = list(qs.order_by("fecha", "id"))
        saldo = Decimal("0.00")
        saldos_by_id: dict[int, Decimal] = {}
        for m in movs_chrono:
            saldo = q2(saldo + m.delta)
            saldos_by_id[m.pk] = saldo
        movs_recientes = list(reversed(movs_chrono))
        headers = [
            "Fecha",
            "Operación",
            "Tipo mov.",
            "Monto",
            "Medio pago",
            "Banco / texto",
            "Cuenta bancaria",
            "Vendedor",
            "Saldo acumulado",
        ]
        flat_rows: list[list] = []
        for m in movs_recientes:
            cb = ""
            if m.cuenta_bancaria_id:
                cb = f"{m.cuenta_bancaria.banco} — {m.cuenta_bancaria.cuenta}"
            flat_rows.append(
                [
                    m.fecha.strftime("%d/%m/%Y"),
                    m.operacion,
                    m.get_tipo_display(),
                    str(q2(m.monto)),
                    m.get_medio_pago_display(),
                    m.banco or "",
                    cb,
                    str(m.vendedor) if m.vendedor else "",
                    str(saldos_by_id[m.pk]),
                ]
            )
        sheets: list[tuple[str, list[str], list[list]]] = []
        n = len(flat_rows)
        if n == 0:
            sheets.append(("Libro 1", headers, []))
        else:
            for i in range(0, n, _LIBRO_CAJA_FILAS_POR_HOJA):
                hoja = i // _LIBRO_CAJA_FILAS_POR_HOJA + 1
                chunk = flat_rows[i : i + _LIBRO_CAJA_FILAS_POR_HOJA]
                sheets.append((f"Libro hoja {hoja}", headers, chunk))
        if exp == "xlsx":
            return xlsx_response("caja_movimientos", sheets)
        return pdf_response("caja_movimientos", "Movimientos de caja (más reciente primero)", sheets)

    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    querystring = qcopy.urlencode()

    return render(
        request,
        "caja/list.html",
        {
            "rows": rows,
            "page_obj": page_obj,
            "querystring": querystring,
            "f": {
                "operacion": q_operacion,
                "tipo": tipo,
                "medio_pago": medio_pago,
                "vendedor": vendedor,
                "desde": fecha_filtro_value_iso(request.GET.get("desde")),
                "hasta": fecha_filtro_value_iso(request.GET.get("hasta")),
            },
            "tipos": MovimientoCaja.Tipo.choices,
            "medios": MovimientoCaja.MedioPago.choices,
            "vendedores_filtro": Vendedor.objects.order_by("apellido", "nombre", "codigo"),
            "totales": totales,
            "resumen_caja": resumen_caja,
            "filtros_activos": filtros_activos,
            "mov_ids_cobro_pedido": mov_ids_cobro_pedido,
        },
    )


@login_required
@require_http_methods(["GET"])
def caja_cheques(request):
    """
    Cheques a pagar y a cobrar (según fecha de vencimiento de cheque) con filtros:
    - criterio: pagar / cobrar / todos
    - desde/hasta (vencimiento)
    """
    criterio = (request.GET.get("criterio") or "todos").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()

    qs = MovimientoCaja.objects.filter(
        medio_pago=MovimientoCaja.MedioPago.CHEQUE,
        fecha_vencimiento_cheque__isnull=False,
    ).order_by("fecha_vencimiento_cheque", "id")

    if criterio == "pagar":
        qs = qs.filter(tipo=MovimientoCaja.Tipo.EGRESO)
    elif criterio == "cobrar":
        qs = qs.filter(tipo=MovimientoCaja.Tipo.INGRESO)
    else:
        criterio = "todos"

    d_desde = parse_fecha_param(desde) if desde else None
    d_hasta = parse_fecha_param(hasta) if hasta else None
    if d_desde:
        qs = qs.filter(fecha_vencimiento_cheque__gte=d_desde)
    if d_hasta:
        qs = qs.filter(fecha_vencimiento_cheque__lte=d_hasta)

    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(qs, 120)
    page_obj = paginator.get_page(page or 1)
    cheques = list(page_obj)

    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    querystring = qcopy.urlencode()

    return render(
        request,
        "caja/cheques.html",
        {
            "cheques": cheques,
            "page_obj": page_obj,
            "querystring": querystring,
            "f": {
                "criterio": criterio,
                "desde": fecha_filtro_value_iso(request.GET.get("desde")),
                "hasta": fecha_filtro_value_iso(request.GET.get("hasta")),
            },
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def caja_create(request):
    modal = (request.GET.get("modal") or "").strip() == "1" or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method == "POST":
        form = MovimientoCajaForm(request.POST)
        if form.is_valid():
            mov = form.save(commit=False)
            mov.creado_por = request.user
            mov.save()
            messages.success(request, f"Movimiento de caja guardado (#{mov.pk}).")
            return redirect("caja_list")
    else:
        form = MovimientoCajaForm(initial={"fecha": date.today().strftime("%Y-%m-%d")})

    tpl = "caja/form_fragment.html" if modal else "caja/form.html"
    return render(request, tpl, {"form": form, "modo": "nuevo"})


@login_required
@require_http_methods(["GET", "POST"])
def caja_edit(request, pk: int):
    mov = get_object_or_404(
        MovimientoCaja.objects.select_related("vendedor", "venta", "cuenta_bancaria"),
        pk=pk,
    )
    venta_cobro = Venta.objects.filter(pago_movimiento_id=mov.pk).select_related("vendedor").first()

    if request.method == "POST":
        form = MovimientoCajaForm(request.POST, instance=mov)
        if form.is_valid():
            if venta_cobro and form.cleaned_data.get("tipo") != MovimientoCaja.Tipo.INGRESO:
                form.add_error(
                    "tipo",
                    "Este movimiento es el cobro registrado de un pedido; debe seguir siendo un ingreso.",
                )
        if form.is_valid():
            obj = form.save(commit=False)
            obj.actualizado_por = request.user
            obj.save()
            messages.success(request, "Movimiento actualizado.")
            return redirect("caja_detail", pk=obj.pk)
    else:
        form = MovimientoCajaForm(instance=mov)

    return render(
        request,
        "caja/form.html",
        {
            "form": form,
            "modo": "editar",
            "mov": mov,
            "venta_cobro": venta_cobro,
        },
    )


@login_required
def caja_detail(request, pk: int):
    mov = get_object_or_404(
        MovimientoCaja.objects.select_related(
            "vendedor", "venta", "compra_registro", "cuenta_bancaria"
        ),
        pk=pk,
    )
    return render(request, "caja/detail.html", {"mov": mov})


@login_required
@require_http_methods(["POST"])
def caja_delete(request, pk: int):
    mov = get_object_or_404(MovimientoCaja, pk=pk)
    try:
        revirtio = False
        with transaction.atomic():
            revirtio = revertir_cobro_pedido_desde_movimiento_caja(mov, request.user)
            if not revirtio:
                mov.delete()
        if revirtio:
            messages.success(request, "Cobro eliminado de caja. El pedido volvió a pendiente de pago en el historial.")
        else:
            messages.success(request, "Movimiento eliminado.")
    except ValidationError as e:
        for msg in e.messages:
            messages.error(request, msg)
    return redirect("caja_list")

