from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.shortcuts import render

from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_dashboard, rango_periodo
from core.money_decimal import q2
from personas.models import Comprador, Vendedor
from productos.models import Producto
from compras.models import Compra
from ventas.models import Venta


def _chart_label_producto(row: dict) -> str:
    """Etiqueta para gráficos: descripción del producto (no el código)."""
    desc = (row.get("lineas__producto__descripcion") or "").strip()
    if not desc:
        return row.get("lineas__producto__codigo") or "—"
    if len(desc) > 80:
        return desc[:77] + "…"
    return desc


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


@login_required
def reportes_dashboard(request):
    periodo, fecha_desde, fecha_hasta = _rango_fechas(request)

    vid = (request.GET.get("vendedor") or "").strip()
    cid = (request.GET.get("comprador") or "").strip()
    pid = (request.GET.get("producto") or "").strip()

    ventas = Venta.objects.select_related("vendedor", "comprador").prefetch_related("lineas__producto")
    compras = Compra.objects.select_related("proveedor", "producto")

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
        compras = compras.filter(producto_id=int(pid))

    neto_expr = ExpressionWrapper(
        F("subtotal_lineas") - F("descuento_monto"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    neto_nonneg = Case(
        When(subtotal_lineas__gte=F("descuento_monto"), then=neto_expr),
        default=Value(Decimal("0.00")),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    comision_bruta = ExpressionWrapper(
        neto_nonneg * (F("comision_porcentaje") / Value(Decimal("100.00"))),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    comision_expr = Case(
        When(aplica_comision=True, then=comision_bruta),
        default=Value(Decimal("0.00")),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )

    kpis = ventas.aggregate(
        pedidos=Count("id"),
        neto_total=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))),
        comision_total=Coalesce(Sum(comision_expr), Value(Decimal("0.00"))),
        pagadas=Count("id", filter=Q(estado=Venta.Estado.PAGADA)),
        pendientes=Count("id", filter=Q(estado=Venta.Estado.PENDIENTE)),
    )
    kpis["neto_total"] = q2(kpis["neto_total"])
    kpis["comision_total"] = q2(kpis["comision_total"])
    compras_kpis = compras.aggregate(
        compras=Count("id"),
        compras_total=Coalesce(Sum("monto"), Value(Decimal("0.00"))),
    )
    compras_kpis["compras_total"] = q2(compras_kpis["compras_total"])
    margen = q2((kpis["neto_total"] or Decimal("0.00")) - (compras_kpis["compras_total"] or Decimal("0.00")))

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

    top_productos = (
        ventas.values("lineas__producto_id", "lineas__producto__codigo", "lineas__producto__descripcion")
        .annotate(unidades=Coalesce(Sum("lineas__cantidad"), Value(0)))
        .order_by("-unidades")[:10]
    )
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

    chart = {
        "labels_ventas_dia": [v["dia"].strftime("%d/%m") for v in ventas_por_dia],
        "ventas_dia_neto": [str(q2(v["neto"])) for v in ventas_por_dia],
        "ventas_dia_pedidos": [v["pedidos"] for v in ventas_por_dia],
        "labels_compras_dia": [c["fecha_compra"].strftime("%d/%m") for c in compras_por_dia],
        "compras_dia_monto": [str(q2(c["monto"])) for c in compras_por_dia],
        "labels_ventas_mes": [v["mes"].strftime("%m/%Y") for v in ventas_por_mes],
        "ventas_mes_neto": [str(q2(v["neto"])) for v in ventas_por_mes],
        "labels_compras_mes": [c["mes"].strftime("%m/%Y") for c in compras_por_mes],
        "compras_mes_monto": [str(q2(c["monto"])) for c in compras_por_mes],
        "estado_labels": ["Pendiente", "Pagada"],
        "estado_counts": [kpis["pendientes"], kpis["pagadas"]],
        "labels_top_productos": [_chart_label_producto(p) for p in top_productos],
        "top_productos_unidades": [p["unidades"] for p in top_productos],
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
        "margen": margen,
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
    }
    return render(request, "reportes/dashboard.html", ctx)

