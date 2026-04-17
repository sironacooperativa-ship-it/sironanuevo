"""Montos en pesos: siempre 2 decimales (redondeo comercial)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def q2(value) -> Decimal:
    """
    Normaliza a 2 decimales. Útil tras agregados SQL y operaciones con float.
    """
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        s = str(value).strip().replace(",", ".")
        if not s or s.lower() in ("nan", "inf", "-inf"):
            return Decimal("0.00")
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_monto_ars(value) -> str:
    """
    Texto para mostrar montos en pesos: $ 1.234.567,89 (miles con punto, decimales con coma).
    """
    d = q2(value)
    us = f"{d:,.2f}"
    ar = us.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {ar}"
