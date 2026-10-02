from datetime import date, datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum, Case, When, F, Value, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce, TruncMonth
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from core.export_utils import parse_export, pdf_response, xlsx_response
from core.money_decimal import q2
from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_param
from personas.models import Vendedor
from ventas.models import Venta
from ventas.servicios import revertir_cobro_pedido_desde_movimiento_caja

from .forms import ActualizarSaldoForm, ArqueoCajaForm, MovimientoCajaForm
from .models import ArqueoCaja, MovimientoCaja


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

_DEC14 = DecimalField(max_digits=14, decimal_places=2)
_ZERO_DEC = Value(Decimal("0.00"), output_field=_DEC14)


def _delta_caja_expr():
    return Case(
        When(es_arqueo=True, then=Value(Decimal("0.00"), output_field=_DEC14)),
        When(tipo=MovimientoCaja.Tipo.ARQUEO, then=Value(Decimal("0.00"), output_field=_DEC14)),
        When(tipo=MovimientoCaja.Tipo.INGRESO, then=F("monto")),
        default=ExpressionWrapper(
            Value(0) - F("monto"), output_field=_DEC14
        ),
        output_field=_DEC14,
    )


def _saldo_antes_de(qs, fecha, pk, delta_expr):
    """Saldo del queryset inmediatamente antes de (fecha, pk), respetando arqueos."""
    previo = Q(fecha__lt=fecha) | Q(fecha=fecha, pk__lt=pk)
    ultimo = (
        qs.select_related(None).filter(es_arqueo=True)
        .filter(previo)
        .order_by("-fecha", "-pk")
        .only("saldo_arqueo", "fecha", "pk")
        .first()
    )
    if ultimo:
        extra = qs.filter(previo).filter(
            Q(fecha__gt=ultimo.fecha) | Q(fecha=ultimo.fecha, pk__gt=ultimo.pk)
        )
        s = extra.aggregate(s=Coalesce(Sum(delta_expr), _ZERO_DEC)).get("s") or Decimal("0.00")
        return q2(q2(ultimo.saldo_arqueo) + q2(s))
    s = qs.filter(previo).aggregate(s=Coalesce(Sum(delta_expr), _ZERO_DEC)).get("s") or Decimal("0.00")
    return q2(s)


def _saldo_caja_al(hasta: date) -> Decimal:
    qs = MovimientoCaja.objects.filter(fecha__lte=hasta)
    delta_expr = _delta_caja_expr()
    ultimo = qs.filter(es_arqueo=True).order_by("-fecha", "-pk").only("saldo_arqueo", "fecha", "pk").first()
    if ultimo:
        extra = qs.filter(Q(fecha__gt=ultimo.fecha) | Q(fecha=ultimo.fecha, pk__gt=ultimo.pk))
        s = extra.aggregate(s=Coalesce(Sum(delta_expr), _ZERO_DEC)).get("s") or Decimal("0.00")
        return q2(q2(ultimo.saldo_arqueo) + q2(s))
    ing = (
        qs.filter(tipo=MovimientoCaja.Tipo.INGRESO).aggregate(s=Sum("monto"))["s"] or Decimal("0.00")
    )
    egr = (
        qs.filter(tipo=MovimientoCaja.Tipo.EGRESO).aggregate(s=Sum("monto"))["s"] or Decimal("0.00")
    )
    return q2(ing - egr)


def _saldos_libro_por_medio(hasta: date) -> dict[str, Decimal]:
    acc: dict[str, Decimal] = {code: Decimal("0.00") for code, _lbl in MovimientoCaja.MedioPago.choices}
    qs = MovimientoCaja.objects.filter(fecha__lte=hasta)
    ultimo = (
        qs.filter(es_arqueo=True)
        .select_related("arqueo")
        .order_by("-fecha", "-pk")
        .first()
    )
    if ultimo:
        detalle = getattr(ultimo, "arqueo", None)
        if detalle is not None:
            acc[MovimientoCaja.MedioPago.EFECTIVO] = q2(detalle.saldo_efectivo)
            acc[MovimientoCaja.MedioPago.TRANSFERENCIA] = q2(detalle.saldo_transferencia)
            acc[MovimientoCaja.MedioPago.MERCADOPAGO] = q2(detalle.saldo_mercadopago)
            acc[MovimientoCaja.MedioPago.CHEQUE] = q2(detalle.saldo_cheque)
            acc[MovimientoCaja.MedioPago.OTRO] = q2(detalle.saldo_otro)
        else:
            acc[MovimientoCaja.MedioPago.OTRO] = q2(ultimo.saldo_arqueo)
        movs = qs.filter(Q(fecha__gt=ultimo.fecha) | Q(fecha=ultimo.fecha, pk__gt=ultimo.pk)).exclude(
            es_arqueo=True
        )
    else:
        movs = qs.exclude(es_arqueo=True)
    for m in movs.only("medio_pago", "tipo", "monto", "es_arqueo"):
        acc[m.medio_pago] = q2(acc.get(m.medio_pago, Decimal("0.00")) + m.delta)
    acc["total"] = q2(sum(acc[code] for code, _lbl in MovimientoCaja.MedioPago.choices))
    return acc


def _aplicar_saldo_movimiento(saldo: Decimal, m: MovimientoCaja) -> Decimal:
    if m.es_arqueo and m.saldo_arqueo is not None:
        return q2(m.saldo_arqueo)
    return q2(saldo + m.delta)


def _libro_diario_rows_con_saldo(qs, delta_expr, movimientos_orden_visual: list[MovimientoCaja]) -> list[dict]:
    """
    `movimientos_orden_visual`: orden en pantalla (ej. más reciente primero).
    Cada fila lleva el saldo real de caja, incluso cuando el listado está filtrado.
    """
    if not movimientos_orden_visual:
        return []
    chrono = sorted(movimientos_orden_visual, key=lambda m: (m.fecha, m.pk))
    first = chrono[0]
    last = chrono[-1]
    libro = MovimientoCaja.objects.all()
    saldo = _saldo_antes_de(libro, first.fecha, first.pk, delta_expr)
    intervalo = libro.filter(
        Q(fecha__gt=first.fecha) | Q(fecha=first.fecha, pk__gte=first.pk)
    ).filter(
        Q(fecha__lt=last.fecha) | Q(fecha=last.fecha, pk__lte=last.pk)
    ).only('fecha', 'tipo', 'monto', 'es_arqueo', 'saldo_arqueo').order_by('fecha', 'pk')
    by_id: dict[int, Decimal] = {}
    for m in intervalo:
        saldo = _aplicar_saldo_movimiento(saldo, m)
        by_id[m.pk] = saldo
    return [{"m": m, "saldo": by_id[m.pk]} for m in movimientos_orden_visual]


def _resumen_caja_dashboard(hoy: date) -> dict:
    """Saldo acumulado hasta hoy (con arqueos); ingresos/egresos del mes; ganancia neta por ventas cobradas en el mes."""
    saldo_al_dia = _saldo_caja_al(hoy)

    inicio_mes = hoy.replace(day=1)
    qs_mes = MovimientoCaja.objects.filter(fecha__gte=inicio_mes, fecha__lte=hoy).exclude(es_arqueo=True)
    ing_mes = (
        qs_mes.filter(tipo=MovimientoCaja.Tipo.INGRESO).aggregate(s=Sum("monto"))["s"]
        or Decimal("0.00")
    )
    egr_mes = (
        qs_mes.filter(tipo=MovimientoCaja.Tipo.EGRESO).aggregate(s=Sum("monto"))["s"]
        or Decimal("0.00")
    )
    dec14 = DecimalField(max_digits=14, decimal_places=2)
    gan_mes = (
        Venta.objects.filter(
            estado=Venta.Estado.PAGADA,
            pago_movimiento__isnull=False,
            pago_movimiento__fecha__gte=inicio_mes,
            pago_movimiento__fecha__lte=hoy,
        ).aggregate(
            s=Sum(
                Coalesce(
                    "ganancia_cobro",
                    Value(Decimal("0.00"), output_field=dec14),
                    output_field=dec14,
                )
            )
        )["s"]
        or Decimal("0.00")
    )
    return {
        "saldo_al_dia": saldo_al_dia,
        "ingresos_mes": q2(ing_mes),
        "egresos_mes": q2(egr_mes),
        "ganancia_neta_mes": q2(gan_mes),
        "fecha_resumen": hoy,
        "mes_etiqueta": f"{_MESES_ES[hoy.month - 1]} {hoy.year}",
    }


def _caja_historico_mensual_rows() -> list[dict[str, object]]:
    """
    Mes a mes: ingresos por cobros de pedidos (movimiento con venta vinculada),
    egresos totales, ganancia neta (ventas cobradas en ese mes según fecha del ingreso en caja).
    """
    dec14 = DecimalField(max_digits=14, decimal_places=2)
    zero = Value(Decimal("0.00"), output_field=dec14)

    ing_por_mes = {
        r["mes"]: q2(r["total"] or Decimal("0.00"))
        for r in MovimientoCaja.objects.filter(
            tipo=MovimientoCaja.Tipo.INGRESO,
            venta_id__isnull=False,
        )
        .annotate(mes=TruncMonth("fecha"))
        .values("mes")
        .annotate(total=Sum("monto"))
    }
    egr_por_mes = {
        r["mes"]: q2(r["total"] or Decimal("0.00"))
        for r in MovimientoCaja.objects.filter(tipo=MovimientoCaja.Tipo.EGRESO)
        .annotate(mes=TruncMonth("fecha"))
        .values("mes")
        .annotate(total=Sum("monto"))
    }
    gan_por_mes = {
        r["mes"]: q2(r["total"] or Decimal("0.00"))
        for r in Venta.objects.filter(
            estado=Venta.Estado.PAGADA,
            pago_movimiento__isnull=False,
        )
        .annotate(mes=TruncMonth("pago_movimiento__fecha"))
        .values("mes")
        .annotate(
            total=Sum(
                Coalesce(
                    "ganancia_cobro",
                    zero,
                    output_field=dec14,
                )
            )
        )
    }

    claves = (
        set(r["mes"] for r in MovimientoCaja.objects.annotate(mes=TruncMonth("fecha")).values("mes").distinct())
        | set(gan_por_mes.keys())
    )
    if not claves:
        return []

    def _clave_orden(m) -> tuple[int, int]:
        return (m.year, m.month)

    filas: list[dict[str, object]] = []
    for mes in sorted(claves, key=_clave_orden, reverse=True):
        d = mes.date() if isinstance(mes, datetime) else mes
        filas.append(
            {
                "mes": mes,
                "etiqueta": f"{_MESES_ES[d.month - 1].capitalize()} {d.year}",
                "ingresos_ventas": ing_por_mes.get(mes, Decimal("0.00")),
                "egresos": egr_por_mes.get(mes, Decimal("0.00")),
                "ganancia_neta": gan_por_mes.get(mes, Decimal("0.00")),
            }
        )
    return filas


@login_required
@require_http_methods(["GET"])
def caja_historico(request):
    filas = _caja_historico_mensual_rows()
    return render(
        request,
        "caja/historico.html",
        {
            "filas": filas,
        },
    )


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
    delta_expr = _delta_caja_expr()

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

    hoy = timezone.localdate()
    resumen_caja = _resumen_caja_dashboard(hoy)
    ultimo_arqueo = (
        MovimientoCaja.objects.filter(es_arqueo=True).order_by("-fecha", "-pk").first()
    )
    filtros_activos = any(
        (request.GET.get(k) or "").strip()
        for k in ("operacion", "tipo", "medio_pago", "vendedor", "desde", "hasta")
    )

    if exp in ("xlsx", "pdf"):
        movs_chrono = list(qs.order_by("fecha", "id"))
        saldos_by_id = {
            row['m'].pk: row['saldo']
            for row in _libro_diario_rows_con_saldo(qs, delta_expr, movs_chrono)
        }
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
            "ultimo_arqueo": ultimo_arqueo,
            "filtros_activos": filtros_activos,
            "mov_ids_cobro_pedido": mov_ids_cobro_pedido,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def caja_arqueo(request):
    """Cierre parcial: declara saldos al día y el libro sigue desde esos números."""
    hoy = timezone.localdate()
    fecha = parse_fecha_param(request.GET.get("fecha") or "") if request.method == "GET" else None
    if request.method == "POST":
        form = ArqueoCajaForm(request.POST)
        if form.is_valid():
            fecha_arq = form.cleaned_data["fecha"]
            saldos = {
                "efectivo": form.cleaned_data["saldo_efectivo"],
                "transferencia": form.cleaned_data["saldo_transferencia"],
                "mercadopago": form.cleaned_data["saldo_mercadopago"],
                "cheque": form.cleaned_data["saldo_cheque"],
                "otro": form.cleaned_data["saldo_otro"],
            }
            total = q2(sum(saldos.values()))
            etiqueta = f"Arqueo al día {fecha_arq.strftime('%d/%m/%Y')}"
            obs = (form.cleaned_data.get("observaciones") or "").strip()
            operacion = etiqueta if not obs else f"{etiqueta} — {obs}"[:255]
            with transaction.atomic():
                mov = MovimientoCaja(
                    fecha=fecha_arq,
                    operacion=operacion,
                    tipo=MovimientoCaja.Tipo.ARQUEO,
                    monto=total,
                    medio_pago=MovimientoCaja.MedioPago.OTRO,
                    es_arqueo=True,
                    saldo_arqueo=total,
                    creado_por=request.user,
                )
                mov.full_clean()
                mov.save()
                ArqueoCaja.objects.create(
                    fecha=fecha_arq,
                    movimiento=mov,
                    saldo_efectivo=saldos["efectivo"],
                    saldo_transferencia=saldos["transferencia"],
                    saldo_mercadopago=saldos["mercadopago"],
                    saldo_cheque=saldos["cheque"],
                    saldo_otro=saldos["otro"],
                    observaciones=obs,
                    creado_por=request.user,
                )
            messages.success(
                request,
                f"{etiqueta} registrado. El libro diario sigue contabilizando desde {total}.",
            )
            return redirect("caja_list")
        fecha = form.data.get("fecha")
        fecha = parse_fecha_param(fecha) if fecha else hoy
    else:
        if fecha is None:
            fecha = hoy
        libro = _saldos_libro_por_medio(fecha)
        form = ArqueoCajaForm(
            initial={
                "fecha": fecha.strftime("%Y-%m-%d"),
                "saldo_efectivo": str(libro[MovimientoCaja.MedioPago.EFECTIVO]),
                "saldo_transferencia": str(libro[MovimientoCaja.MedioPago.TRANSFERENCIA]),
                "saldo_mercadopago": str(libro[MovimientoCaja.MedioPago.MERCADOPAGO]),
                "saldo_cheque": str(libro[MovimientoCaja.MedioPago.CHEQUE]),
                "saldo_otro": str(libro[MovimientoCaja.MedioPago.OTRO]),
            }
        )
        libro_ref = libro
        return render(
            request,
            "caja/arqueo.html",
            {
                "form": form,
                "fecha_arqueo": fecha,
                "libro": libro_ref,
                "libro_total": libro_ref["total"],
            },
        )

    libro = _saldos_libro_por_medio(fecha or hoy)
    return render(
        request,
        "caja/arqueo.html",
        {
            "form": form,
            "fecha_arqueo": fecha or hoy,
            "libro": libro,
            "libro_total": libro["total"],
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
        form = MovimientoCajaForm(initial={"fecha": timezone.localdate().strftime("%Y-%m-%d")})

    tpl = "caja/form_fragment.html" if modal else "caja/form.html"
    return render(request, tpl, {"form": form, "modo": "nuevo"})


@login_required
@require_http_methods(["GET", "POST"])
def caja_edit(request, pk: int):
    mov = get_object_or_404(
        MovimientoCaja.objects.select_related("vendedor", "venta", "cuenta_bancaria"),
        pk=pk,
    )
    if mov.es_arqueo:
        messages.info(request, "Un arqueo no se edita. Si hace falta, eliminalo y cargá uno nuevo.")
        return redirect("caja_detail", pk=mov.pk)
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
            "vendedor", "venta", "compra_registro", "cuenta_bancaria", "arqueo"
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



@login_required
@require_http_methods(['GET', 'POST'])
def caja_actualizar_saldo(request):
    from core.money_decimal import format_monto_ars
    from .saldos import actualizar_saldo_caja

    form = ActualizarSaldoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        movimiento = actualizar_saldo_caja(
            saldo=form.cleaned_data['saldo_actual'], usuario=request.user,
            observaciones=form.cleaned_data['observaciones'],
        )
        messages.success(request, f"Saldo actualizado a {format_monto_ars(movimiento.saldo_arqueo)}. Los movimientos siguientes se calcularán desde este importe.")
        return redirect('caja_list')
    hoy = timezone.localdate()
    return render(request, 'caja/actualizar_saldo.html', {
        'form': form, 'hoy': hoy, 'saldo_libro': _saldo_caja_al(hoy),
    })
