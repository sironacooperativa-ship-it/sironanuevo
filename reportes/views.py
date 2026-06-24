from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.export_utils import xlsx_response
from core.fecha_filtros import (
    fecha_filtro_value_iso,
    parse_fecha_dashboard,
    rango_periodo,
    trunc_to_date,
    trunc_to_month_start,
)
from core.money_decimal import q2
from personas.models import Comprador, Vendedor
from productos.models import Producto
from compras.models import Compra
from ventas.models import Venta, VentaLinea
from ventas.sql_metrics import venta_comision_expr, venta_linea_margen_bruto_expr, venta_neto_nonneg_expr

TOP_PRODUCTOS_TABLA = 10
TOP_PRODUCTOS_CHART_MAX = 150


def _chart_label_producto(row: dict) -> str:
    """Etiqueta para gráficos: descripción del producto (no el código)."""
    desc = (
        row.get("descripcion_ef")
        or row.get("lineas__producto__descripcion")
        or ""
    ).strip()
    if not desc:
        return row.get("codigo_ef") or row.get("lineas__producto__codigo") or "—"
    if len(desc) > 80:
        return desc[:77] + "…"
    return desc


def _venta_lineas_con_snapshot(ventas):
    """Líneas de venta con código/descripción efectivos (incluye pedidos archivados al despachar)."""
    return VentaLinea.objects.filter(venta__in=ventas).annotate(
        codigo_ef=Coalesce(F("codigo_snapshot"), F("producto__codigo"), Value("")),
        descripcion_ef=Coalesce(F("descripcion_snapshot"), F("producto__descripcion"), Value("")),
    )


def _chart_label_vendedor(row: dict) -> str:
    """Etiqueta para gráficos: apellido y nombre (no el código)."""
    ap = (row.get("vendedor__apellido") or "").strip()
    nom = (row.get("vendedor__nombre") or "").strip()
    if ap and nom:
        return f"{ap}, {nom}"
    if ap or nom:
        return ap or nom
    return row.get("vendedor__codigo") or "—"


def _rango_fechas(request):
    periodo = (request.GET.get("periodo") or "").strip()
    if periodo in ("7d", "30d", "mes", "mes_ant"):
        desde, hasta = rango_periodo(periodo)
    else:
        desde = parse_fecha_dashboard(request.GET.get("fecha_desde"))
        hasta = parse_fecha_dashboard(request.GET.get("fecha_hasta"))
    return periodo, desde, hasta


def _mes_primero(mes_val) -> date | None:
    return trunc_to_month_start(mes_val)


def _siguiente_mes(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _serie_mensual_chart(rows, valor_key: str, fecha_desde, fecha_hasta) -> tuple[list[str], list[str]]:
    """Etiquetas y valores por mes calendario (rellena huecos con cero)."""
    by_mes: dict[date, Decimal] = {}
    for row in rows:
        mk = _mes_primero(row.get("mes"))
        if mk is None:
            continue
        by_mes[mk] = q2(row.get(valor_key) or 0)

    hoy = timezone.localdate()
    if fecha_desde and fecha_hasta:
        start = fecha_desde.replace(day=1)
        end = fecha_hasta.replace(day=1)
    elif by_mes:
        start = min(by_mes.keys())
        end = max(by_mes.keys())
    else:
        end = hoy.replace(day=1)
        start = end
        for _ in range(11):
            if start.month == 1:
                start = date(start.year - 1, 12, 1)
            else:
                start = date(start.year, start.month - 1, 1)

    labels: list[str] = []
    valores: list[str] = []
    cur = start
    while cur <= end:
        labels.append(f"{cur.month:02d}/{cur.year}")
        valores.append(str(by_mes.get(cur, Decimal("0.00"))))
        cur = _siguiente_mes(cur)
    return labels, valores


def _serie_diaria_chart(
    rows, fecha_field: str, valor_key: str, fecha_desde, fecha_hasta
) -> tuple[list[str], list[str]]:
    """Etiquetas y montos por día (rellena huecos con cero en el rango)."""
    by_day: dict[date, Decimal] = {}
    for row in rows:
        d = trunc_to_date(row.get(fecha_field))
        if d is None:
            continue
        by_day[d] = q2(row.get(valor_key) or 0)

    hoy = timezone.localdate()
    if fecha_desde and fecha_hasta:
        start, end = fecha_desde, fecha_hasta
    elif by_day:
        start, end = min(by_day.keys()), max(by_day.keys())
    else:
        end = hoy
        start = hoy - timedelta(days=29)

    labels: list[str] = []
    valores: list[str] = []
    cur = start
    while cur <= end:
        labels.append(cur.strftime("%d/%m"))
        valores.append(str(by_day.get(cur, Decimal("0.00"))))
        cur += timedelta(days=1)
    return labels, valores


def _reportes_export_query(request) -> str:
    q = request.GET.copy()
    q.pop("modo", None)
    return q.urlencode()


def _mes_label(d: date) -> str:
    nombres = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")
    return f"{nombres[d.month - 1]} {d.year}"


def _ventas_queryset_reportes(request, *, aplicar_fechas: bool):
    periodo, fecha_desde, fecha_hasta = _rango_fechas(request)
    vid = (request.GET.get("vendedor") or "").strip()
    cid = (request.GET.get("comprador") or "").strip()
    pid = (request.GET.get("producto") or "").strip()

    ventas = Venta.objects.all()
    if aplicar_fechas:
        if fecha_desde:
            ventas = ventas.filter(creado_en__date__gte=fecha_desde)
        if fecha_hasta:
            ventas = ventas.filter(creado_en__date__lte=fecha_hasta)
    if vid.isdigit():
        ventas = ventas.filter(vendedor_id=int(vid))
    if cid.isdigit():
        ventas = ventas.filter(comprador_id=int(cid))
    if pid.isdigit():
        ventas = ventas.filter(lineas__producto_id=int(pid)).distinct()
    return ventas, periodo, fecha_desde, fecha_hasta


def _productos_vendidos_total_rows(ventas) -> list[list]:
    qs = (
        _venta_lineas_con_snapshot(ventas)
        .values("codigo_ef", "descripcion_ef")
        .annotate(unidades=Coalesce(Sum("cantidad"), Value(0)))
        .order_by("-unidades", "descripcion_ef")
    )
    return [
        [r["codigo_ef"] or "", r["descripcion_ef"] or "", int(r["unidades"] or 0)]
        for r in qs
        if int(r["unidades"] or 0) > 0
    ]


def _productos_vendidos_periodos_tabla(ventas) -> tuple[list[str], list[list]]:
    qs = (
        _venta_lineas_con_snapshot(ventas)
        .annotate(mes=TruncMonth("venta__creado_en"))
        .values("codigo_ef", "descripcion_ef", "mes")
        .annotate(unidades=Coalesce(Sum("cantidad"), Value(0)))
    )
    months_set: set[date] = set()
    by_prod: dict[tuple[str, str], dict[date, int]] = defaultdict(lambda: defaultdict(int))

    for r in qs:
        unidades = int(r["unidades"] or 0)
        if unidades <= 0:
            continue
        mes_key = trunc_to_month_start(r["mes"])
        if mes_key is None:
            continue
        prod_key = (r["codigo_ef"] or "", r["descripcion_ef"] or "")
        months_set.add(mes_key)
        by_prod[prod_key][mes_key] += unidades

    months_sorted = sorted(months_set)
    headers = ["Código", "Producto"] + [_mes_label(m) for m in months_sorted] + ["Total"]
    rows = []
    for (cod, desc), per_m in sorted(by_prod.items(), key=lambda item: -sum(item[1].values())):
        total = 0
        row = [cod, desc]
        for m in months_sorted:
            v = per_m.get(m, 0)
            row.append(v if v else "")
            total += v
        row.append(total)
        rows.append(row)
    return headers, rows


def _export_fname_sufijo(periodo: str, fecha_desde, fecha_hasta, modo: str) -> str:
    if modo == "inicio":
        return "desde_inicio"
    if periodo == "7d":
        return "periodos_7d"
    if periodo == "30d":
        return "periodos_30d"
    if periodo == "mes":
        return "periodos_mes_actual"
    if periodo == "mes_ant":
        return "periodos_mes_anterior"
    if fecha_desde and fecha_hasta:
        return f"periodos_{fecha_desde.isoformat()}_{fecha_hasta.isoformat()}"
    if fecha_desde:
        return f"periodos_desde_{fecha_desde.isoformat()}"
    if fecha_hasta:
        return f"periodos_hasta_{fecha_hasta.isoformat()}"
    return "periodos_todo"


@login_required
def reportes_dashboard(request):
    periodo, fecha_desde, fecha_hasta = _rango_fechas(request)

    vid = (request.GET.get("vendedor") or "").strip()
    cid = (request.GET.get("comprador") or "").strip()
    pid = (request.GET.get("producto") or "").strip()

    ventas = Venta.objects.select_related("vendedor", "comprador").prefetch_related("lineas__producto")
    compras = Compra.objects.filter(anulada=False).select_related("proveedor", "producto")

    if fecha_desde:
        ventas = ventas.filter(creado_en__date__gte=fecha_desde)
        compras = compras.filter(fecha_compra__gte=fecha_desde)
    if fecha_hasta:
        ventas = ventas.filter(creado_en__date__lte=fecha_hasta)
        compras = compras.filter(fecha_compra__lte=fecha_hasta)

    if vid.isdigit():
        ventas = ventas.filter(vendedor_id=int(vid))
    if cid.isdigit():
        ventas = ventas.filter(comprador_id=int(cid))
    if pid.isdigit():
        ventas = ventas.filter(lineas__producto_id=int(pid)).distinct()
        # El filtro de producto aplica a ventas; las compras tipo factura no tienen producto.

    neto_nonneg = venta_neto_nonneg_expr()
    comision_expr = venta_comision_expr(neto_nonneg)

    kpis = ventas.aggregate(
        pedidos=Count("id"),
        neto_total=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))),
        comision_total=Coalesce(Sum(comision_expr), Value(Decimal("0.00"))),
        pagadas=Count("id", filter=Q(estado=Venta.Estado.PAGADA)),
        pendientes=Count("id", filter=Q(estado=Venta.Estado.PENDIENTE)),
    )
    margen_line_expr = venta_linea_margen_bruto_expr()
    margen_pedidos_bruto = (
        VentaLinea.objects.filter(venta__in=ventas)
        .aggregate(m=Coalesce(Sum(margen_line_expr), Value(Decimal("0.00"))))
        .get("m")
        or Decimal("0.00")
    )
    comision_dec = kpis["comision_total"] or Decimal("0.00")
    ganancia_dec = (margen_pedidos_bruto or Decimal("0.00")) - comision_dec

    kpis["neto_total"] = q2(kpis["neto_total"])
    kpis["comision_total"] = q2(kpis["comision_total"])
    compras_kpis = compras.aggregate(
        compras=Count("id"),
        compras_total=Coalesce(Sum("monto"), Value(Decimal("0.00"))),
    )
    compras_dec = compras_kpis["compras_total"] or Decimal("0.00")
    compras_kpis["compras_total"] = q2(compras_dec)
    margen_pedidos = q2(margen_pedidos_bruto)
    ganancia = q2(ganancia_dec)
    egresos_operativos = q2(compras_dec + comision_dec)

    ventas_por_dia = (
        ventas.annotate(dia=TruncDate("creado_en"))
        .values("dia")
        .annotate(neto=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))), pedidos=Count("id"))
        .order_by("dia")
    )
    compras_por_dia = (
        compras.values("fecha_compra")
        .annotate(monto=Coalesce(Sum("monto"), Value(Decimal("0.00"))), compras=Count("id"))
        .order_by("fecha_compra")
    )

    ventas_por_mes = (
        ventas.annotate(mes=TruncMonth("creado_en"))
        .values("mes")
        .annotate(neto=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))), pedidos=Count("id"))
        .order_by("mes")
    )
    compras_por_mes = (
        compras.annotate(mes=TruncMonth("fecha_compra"))
        .values("mes")
        .annotate(monto=Coalesce(Sum("monto"), Value(Decimal("0.00"))), compras=Count("id"))
        .order_by("mes")
    )

    top_productos_qs = (
        _venta_lineas_con_snapshot(ventas)
        .values("codigo_ef", "descripcion_ef")
        .annotate(unidades=Coalesce(Sum("cantidad"), Value(0)))
        .order_by("-unidades")
    )
    top_productos_chart = list(top_productos_qs[:TOP_PRODUCTOS_CHART_MAX])
    top_productos = top_productos_chart[:TOP_PRODUCTOS_TABLA]
    top_vendedores = (
        ventas.values("vendedor_id", "vendedor__codigo", "vendedor__apellido", "vendedor__nombre")
        .annotate(neto=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))), pedidos=Count("id"))
        .order_by("-neto")[:10]
    )

    top_clientes = (
        ventas.exclude(comprador_id__isnull=True)
        .values("comprador_id", "comprador__codigo", "comprador__apellido", "comprador__nombre")
        .annotate(neto=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))), pedidos=Count("id"))
        .order_by("-neto")[:10]
    )

    clientes_activos = ventas.exclude(comprador_id__isnull=True).values("comprador_id").distinct().count()
    productos_vendidos = ventas.aggregate(
        u=Coalesce(Sum("lineas__cantidad"), Value(0)),
    )["u"] or 0

    # Resumen por categoría (tipo de producto) usando unidades vendidas por tipo.
    por_tipo = (
        ventas.values("lineas__producto__tipo")
        .annotate(unidades=Coalesce(Sum("lineas__cantidad"), Value(0)))
        .order_by("-unidades")
    )
    tipo_labels_map = dict(Producto.Tipo.choices)
    labels_tipo = [tipo_labels_map.get((r.get("lineas__producto__tipo") or "").strip(), "—") for r in por_tipo]
    tipo_unidades = [r["unidades"] for r in por_tipo]

    labels_ventas_mes, ventas_mes_neto = _serie_mensual_chart(
        list(ventas_por_mes), "neto", fecha_desde, fecha_hasta
    )
    labels_compras_mes, compras_mes_monto = _serie_mensual_chart(
        list(compras_por_mes), "monto", fecha_desde, fecha_hasta
    )
    labels_ventas_dia, ventas_dia_neto = _serie_diaria_chart(
        list(ventas_por_dia), "dia", "neto", fecha_desde, fecha_hasta
    )
    labels_compras_dia, compras_dia_monto = _serie_diaria_chart(
        list(compras_por_dia), "fecha_compra", "monto", fecha_desde, fecha_hasta
    )
    ventas_dia_pedidos_map = {
        trunc_to_date(v["dia"]): v["pedidos"]
        for v in ventas_por_dia
        if trunc_to_date(v.get("dia")) is not None
    }
    ventas_dia_pedidos = []
    if fecha_desde and fecha_hasta:
        cur = fecha_desde
        while cur <= fecha_hasta:
            ventas_dia_pedidos.append(ventas_dia_pedidos_map.get(cur, 0))
            cur += timedelta(days=1)

    chart = {
        "labels_ventas_dia": labels_ventas_dia,
        "ventas_dia_neto": ventas_dia_neto,
        "ventas_dia_pedidos": ventas_dia_pedidos,
        "labels_compras_dia": labels_compras_dia,
        "compras_dia_monto": compras_dia_monto,
        "labels_ventas_mes": labels_ventas_mes,
        "ventas_mes_neto": ventas_mes_neto,
        "labels_compras_mes": labels_compras_mes,
        "compras_mes_monto": compras_mes_monto,
        "compras_registros": int(compras_kpis.get("compras") or 0),
        "estado_labels": ["Pendiente", "Pagada"],
        "estado_counts": [kpis["pendientes"], kpis["pagadas"]],
        "labels_top_productos": [_chart_label_producto(p) for p in top_productos],
        "top_productos_unidades": [p["unidades"] for p in top_productos],
        "labels_top_productos_all": [_chart_label_producto(p) for p in top_productos_chart],
        "top_productos_unidades_all": [int(p["unidades"] or 0) for p in top_productos_chart],
        "top_productos_limite_defecto": TOP_PRODUCTOS_TABLA,
        "top_productos_limite_max": TOP_PRODUCTOS_CHART_MAX,
        "top_productos_ranking_disponible": len(top_productos_chart),
        "labels_top_vendedores": [_chart_label_vendedor(v) for v in top_vendedores],
        "top_vendedores_neto": [str(q2(v["neto"])) for v in top_vendedores],
        "labels_top_clientes": [
            (f'{c.get("comprador__apellido")}, {c.get("comprador__nombre")}'.strip(", ").strip() or c.get("comprador__codigo") or "—")
            for c in top_clientes
        ],
        "top_clientes_neto": [str(q2(c["neto"])) for c in top_clientes],
        "top_clientes_pedidos": [c["pedidos"] for c in top_clientes],
        "labels_tipo": labels_tipo,
        "tipo_unidades": tipo_unidades,
    }

    pedidos = int(kpis.get("pedidos") or 0)
    ticket_promedio = q2((kpis["neto_total"] / Decimal(pedidos)) if pedidos else Decimal("0.00"))

    ctx = {
        "filtros": {
            "periodo": periodo,
            "fecha_desde": fecha_filtro_value_iso(request.GET.get("fecha_desde")),
            "fecha_hasta": fecha_filtro_value_iso(request.GET.get("fecha_hasta")),
            "vendedor": vid,
            "comprador": cid,
            "producto": pid,
        },
        "kpis": kpis,
        "compras_kpis": compras_kpis,
        "margen_pedidos": margen_pedidos,
        "ganancia": ganancia,
        "egresos_operativos": egresos_operativos,
        "clientes_activos": clientes_activos,
        "ticket_promedio": ticket_promedio,
        "productos_vendidos": productos_vendidos,
        "top_clientes": list(top_clientes),
        "top_productos": list(top_productos),
        "top_vendedores": list(top_vendedores),
        "chart": chart,
        "vendedores_filtro": Vendedor.objects.order_by("apellido", "nombre", "codigo"),
        "compradores_filtro": Comprador.objects.order_by("apellido", "nombre", "codigo"),
        "productos_filtro": Producto.objects.filter(habilitado=True).order_by("descripcion", "codigo"),
        "productos_export_query": _reportes_export_query(request),
    }
    return render(request, "reportes/dashboard.html", ctx)


@login_required
@require_GET
def export_productos_vendidos(request):
    modo = (request.GET.get("modo") or "").strip()
    if modo not in ("inicio", "periodos"):
        return redirect("reportes_dashboard")

    aplicar_fechas = modo == "periodos"
    ventas, periodo, fecha_desde, fecha_hasta = _ventas_queryset_reportes(
        request, aplicar_fechas=aplicar_fechas
    )
    sufijo = _export_fname_sufijo(periodo, fecha_desde, fecha_hasta, modo)

    if modo == "inicio":
        headers = ["Código", "Producto", "Unidades vendidas"]
        rows = _productos_vendidos_total_rows(ventas)
        titulo_hoja = "Total histórico"
    else:
        headers, rows = _productos_vendidos_periodos_tabla(ventas)
        titulo_hoja = "Por mes"

    fname = f"reportes_productos_vendidos_{sufijo}"
    return xlsx_response(fname, [(titulo_hoja, headers, rows)])

