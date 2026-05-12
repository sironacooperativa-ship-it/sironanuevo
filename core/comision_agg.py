"""Agregación de comisiones por mes calendario (según fecha de registro del pedido)."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from core.money_decimal import q2

_MESES_ES = (
    "",
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


def _comisiones_por_mes(qs, *, porcentaje: Decimal | None = None):
    """
    Recibe un QuerySet de Venta ya filtrado. Devuelve lista de dicts:
    { "anio", "mes", "total" } ordenados del mes más reciente al más viejo.
    """
    qs = qs.order_by().distinct()
    by_month: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in qs.values(
        "creado_en",
        "subtotal_lineas",
        "descuento_monto",
        "envio",
        "comision_porcentaje",
        "aplica_comision",
    ):
        if not row["aplica_comision"]:
            continue
        ce = row["creado_en"]
        envio = row.get("envio") or Decimal("0")
        neto = row["subtotal_lineas"] - row["descuento_monto"] + envio
        if neto < 0:
            neto = Decimal("0")
        pct = porcentaje if porcentaje is not None else (row["comision_porcentaje"] or Decimal("0"))
        com = q2(neto * (pct / Decimal("100")))
        by_month[(ce.year, ce.month)] += com
    return by_month


def _salida_meses(by_month: dict[tuple[int, int], Decimal]):
    keys = sorted(by_month.keys(), reverse=True)
    out = []
    for (y, m) in keys:
        out.append(
            {
                "anio": y,
                "mes": m,
                "mes_nombre": _MESES_ES[m] if 1 <= m <= 12 else str(m),
                "total": q2(by_month[(y, m)]),
            }
        )
    return out


def comisiones_acumuladas_por_mes(qs):
    """
    Recibe un QuerySet de Venta ya filtrado. Devuelve lista de dicts:
    { "anio", "mes", "total" } ordenados del mes más reciente al más viejo.
    """
    return _salida_meses(_comisiones_por_mes(qs))


def comisiones_vendedor_con_grupo_por_mes(qs_propias, qs_grupo, porcentaje_grupo: Decimal):
    propias = _comisiones_por_mes(qs_propias)
    grupo = _comisiones_por_mes(qs_grupo, porcentaje=porcentaje_grupo)
    keys = sorted(set(propias.keys()) | set(grupo.keys()), reverse=True)
    out = []
    for (y, m) in keys:
        total_propias = q2(propias[(y, m)])
        total_grupo = q2(grupo[(y, m)])
        out.append(
            {
                "anio": y,
                "mes": m,
                "mes_nombre": _MESES_ES[m] if 1 <= m <= 12 else str(m),
                "propias": total_propias,
                "grupo": total_grupo,
                "total": q2(total_propias + total_grupo),
            }
        )
    return out
