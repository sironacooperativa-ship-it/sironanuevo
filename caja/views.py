from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.export_utils import parse_export, pdf_response, xlsx_response

from .forms import MovimientoCajaForm
from .models import MovimientoCaja


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
    if vendedor:
        qs = qs.filter(vendedor_id=vendedor)

    # filtros por fecha (dd/mm/aa)
    def parse_fecha(s: str):
        from datetime import datetime

        for fmt in ("%d/%m/%y", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    d_desde = parse_fecha(desde) if desde else None
    d_hasta = parse_fecha(hasta) if hasta else None
    if d_desde:
        qs = qs.filter(fecha__gte=d_desde)
    if d_hasta:
        qs = qs.filter(fecha__lte=d_hasta)

    movimientos = list(qs.order_by("fecha", "id"))

    # saldo acumulado
    saldo = Decimal("0.00")
    rows = []
    for m in movimientos:
        saldo += m.delta
        rows.append({"m": m, "saldo": saldo})

    # agrupar por periodo (YYYY-MM)
    grupos = defaultdict(list)
    for r in rows:
        key = r["m"].fecha.strftime("%Y-%m")
        grupos[key].append(r)

    periodos = []
    for key in sorted(grupos.keys()):
        items = grupos[key]
        total_periodo = sum((it["m"].delta for it in items), Decimal("0.00"))
        periodos.append({"periodo": key, "items": items, "total": total_periodo})

    totales = qs.aggregate(total_ingreso=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.INGRESO)),
                           total_egreso=Sum("monto", filter=Q(tipo=MovimientoCaja.Tipo.EGRESO)))

    exp = parse_export(request)
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
            saldo += m.delta
            cb = ""
            if m.cuenta_bancaria_id:
                cb = f"{m.cuenta_bancaria.banco} — {m.cuenta_bancaria.cuenta}"
            rows.append(
                [
                    m.fecha.strftime("%d/%m/%Y"),
                    m.operacion,
                    m.get_tipo_display(),
                    str(m.monto),
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

    return render(
        request,
        "caja/list.html",
        {
            "periodos": periodos,
            "f": {
                "operacion": q_operacion,
                "tipo": tipo,
                "medio_pago": medio_pago,
                "vendedor": vendedor,
                "desde": desde,
                "hasta": hasta,
            },
            "tipos": MovimientoCaja.Tipo.choices,
            "medios": MovimientoCaja.MedioPago.choices,
            "vendedores": list({r["m"].vendedor for r in rows if r["m"].vendedor}),
            "totales": totales,
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
        form = MovimientoCajaForm(initial={"fecha": date.today().strftime("%d/%m/%y")})

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


@login_required
@require_http_methods(["POST"])
def caja_delete(request, pk: int):
    mov = get_object_or_404(MovimientoCaja, pk=pk)
    mov.delete()
    messages.success(request, "Movimiento eliminado.")
    return redirect("caja_list")

