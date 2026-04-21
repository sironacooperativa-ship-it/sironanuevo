from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, Case, When, F, Value, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.authz import staff_required
from core.export_utils import parse_export, pdf_response, xlsx_response
from core.money_decimal import q2
from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_param
from personas.models import Vendedor

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
    qs = MovimientoCaja.objects.select_related("vendedor", "cuenta_bancaria").all()

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
    auto_limitado = False
    if not exp:
        # Si no hay filtros, limitar por defecto a 90 días para evitar cargar todo el histórico.
        if not any([q_operacion, tipo, medio_pago, vendedor, d_desde, d_hasta]):
            d_desde = date.today() - timedelta(days=90)
            auto_limitado = True
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

    # Saldo previo al rango (si hay desde)
    saldo_previo = Decimal("0.00")
    if d_desde:
        saldo_previo = (
            MovimientoCaja.objects.filter(fecha__lt=d_desde)
            .aggregate(s=Coalesce(Sum(delta_expr), Value(Decimal("0.00"))))
            .get("s")
            or Decimal("0.00")
        )

    movimientos_qs = qs.order_by("fecha", "id")
    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(movimientos_qs, 200)
    page_obj = paginator.get_page(page or 1)
    movimientos = list(page_obj)

    # saldo acumulado
    saldo = q2(saldo_previo)
    rows = []
    for m in movimientos:
        saldo = q2(saldo + m.delta)
        rows.append({"m": m, "saldo": saldo})

    # agrupar por periodo (YYYY-MM)
    grupos = defaultdict(list)
    for r in rows:
        key = r["m"].fecha.strftime("%Y-%m")
        grupos[key].append(r)

    periodos = []
    for key in sorted(grupos.keys()):
        items = grupos[key]
        total_periodo = q2(sum((it["m"].delta for it in items), Decimal("0.00")))
        periodos.append({"periodo": key, "items": items, "total": total_periodo})

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
        movs = list(qs.order_by("fecha", "id"))
        saldo = Decimal("0.00")
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
        rows = []
        for m in movs:
            saldo = q2(saldo + m.delta)
            cb = ""
            if m.cuenta_bancaria_id:
                cb = f"{m.cuenta_bancaria.banco} — {m.cuenta_bancaria.cuenta}"
            rows.append(
                [
                    m.fecha.strftime("%d/%m/%Y"),
                    m.operacion,
                    m.get_tipo_display(),
                    str(q2(m.monto)),
                    m.get_medio_pago_display(),
                    m.banco or "",
                    cb,
                    str(m.vendedor) if m.vendedor else "",
                    str(saldo),
                ]
            )
        if exp == "xlsx":
            return xlsx_response("caja_movimientos", [("Movimientos", headers, rows)])
        return pdf_response("caja_movimientos", "Movimientos de caja", [("Movimientos", headers, rows)])

    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    querystring = qcopy.urlencode()

    return render(
        request,
        "caja/list.html",
        {
            "periodos": periodos,
            "page_obj": page_obj,
            "querystring": querystring,
            "auto_limitado": auto_limitado,
            "f": {
                "operacion": q_operacion,
                "tipo": tipo,
                "medio_pago": medio_pago,
                "vendedor": vendedor,
                "desde": (d_desde.isoformat() if d_desde and auto_limitado else fecha_filtro_value_iso(request.GET.get("desde"))),
                "hasta": fecha_filtro_value_iso(request.GET.get("hasta")),
            },
            "tipos": MovimientoCaja.Tipo.choices,
            "medios": MovimientoCaja.MedioPago.choices,
            "vendedores_filtro": Vendedor.objects.order_by("apellido", "nombre", "codigo"),
            "totales": totales,
            "resumen_caja": resumen_caja,
            "filtros_activos": filtros_activos,
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

    return render(
        request,
        "caja/cheques.html",
        {
            "cheques": cheques,
            "page_obj": page_obj,
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
    if request.method == "POST":
        form = MovimientoCajaForm(request.POST)
        if form.is_valid():
            mov = form.save()
            messages.success(request, f"Movimiento cargado: {mov.id}")
            return redirect("caja_list")
    else:
        form = MovimientoCajaForm(initial={"fecha": date.today().strftime("%Y-%m-%d")})

    return render(request, "caja/form.html", {"form": form, "modo": "nuevo"})


@login_required
def caja_detail(request, pk: int):
    mov = get_object_or_404(
        MovimientoCaja.objects.select_related(
            "vendedor", "venta", "compra_registro", "cuenta_bancaria"
        ),
        pk=pk,
    )
    return render(request, "caja/detail.html", {"mov": mov})


@staff_required
@require_http_methods(["POST"])
def caja_delete(request, pk: int):
    mov = get_object_or_404(MovimientoCaja, pk=pk)
    mov.delete()
    messages.success(request, "Movimiento eliminado.")
    return redirect("caja_list")

