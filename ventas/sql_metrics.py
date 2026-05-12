"""Expresiones ORM alineadas con `Venta.neto` y métricas derivadas (comisión, margen por línea)."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Case, DecimalField, ExpressionWrapper, F, Value, When
from django.db.models.functions import Coalesce, Greatest

DEC14 = DecimalField(max_digits=14, decimal_places=2)
_ZERO = Value(Decimal("0.00"), output_field=DEC14)


def venta_neto_nonneg_expr():
    """
    Réplica SQL de `Venta.neto`: subtotal_lineas − descuento + envío, acotado a no negativo.
    """
    raw = ExpressionWrapper(
        F("subtotal_lineas")
        - F("descuento_monto")
        + Coalesce(F("envio"), _ZERO, output_field=DEC14),
        output_field=DEC14,
    )
    return Greatest(raw, _ZERO, output_field=DEC14)


def venta_comision_expr(neto_nonneg):
    """Comisión por fila de `Venta`, coherente con `Venta.monto_comision`."""
    comision_bruta = ExpressionWrapper(
        neto_nonneg * (F("comision_porcentaje") / Value(Decimal("100.00"))),
        output_field=DEC14,
    )
    return Case(
        When(aplica_comision=True, then=comision_bruta),
        default=_ZERO,
        output_field=DEC14,
    )


def venta_linea_margen_bruto_expr():
    """Margen bruto por línea: subtotal de línea − cantidad × costo actual del producto."""
    costo = Coalesce(F("producto__costo"), _ZERO, output_field=DEC14)
    return ExpressionWrapper(F("subtotal") - F("cantidad") * costo, output_field=DEC14)
