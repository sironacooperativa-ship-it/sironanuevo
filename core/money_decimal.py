"""Montos en pesos: siempre 2 decimales (redondeo comercial)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Comisión sobre el neto del pedido cuando aplica (presupuesto no la muestra; se confirma/edita en Ventas).
COMISION_PORCENTAJE_DEFECTO = Decimal("5.00")


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


def redondear_precio_mostrador_ars(value) -> Decimal:
    """
    Precio de venta sugerido: solo termina en ,00 o ,50.
    Cualquier otro centavo redondea hacia arriba al próximo medio peso o peso entero.
    """
    d = q2(value)
    if d <= 0:
        return Decimal("0.00")
    cents = int((d * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))
    mod = cents % 100
    if mod in (0, 50):
        return (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))
    if mod < 50:
        out_cents = (cents // 100) * 100 + 50
    else:
        out_cents = (cents // 100 + 1) * 100
    return (Decimal(out_cents) / Decimal("100")).quantize(Decimal("0.01"))


def parse_decimal_from_input(raw: str | None) -> Decimal:
    """
    Interpreta montos ingresados en formulario: acepta salida de format_monto_ars (`$ 1.234,56`),
    `1234,56`, `1234.56` o entero sin separadores.
    """
    if raw is None:
        raise InvalidOperation()
    s = str(raw).strip()
    if not s:
        raise InvalidOperation()
    s = s.replace("$", "").replace("\u00a0", " ").replace(" ", "").strip()
    if not s:
        raise InvalidOperation()
    neg = s.startswith("-")
    if neg:
        s = s[1:].strip()
    if not s:
        raise InvalidOperation()
    if s.count(",") > 1:
        raise InvalidOperation()
    sign = "-" if neg else ""
    if "," in s:
        head, _, tail = s.rpartition(",")
        if tail == "" or not tail.isdigit():
            raise InvalidOperation()
        head = head.replace(".", "")
        if head == "" or head == "-":
            head = "0"
        s_norm = f"{sign}{head}.{tail}"
    else:
        parts = s.split(".")
        if len(parts) == 1:
            s_norm = f"{sign}{parts[0]}"
        elif len(parts) == 2 and len(parts[1]) <= 2 and parts[1].isdigit():
            s_norm = f"{sign}{parts[0]}.{parts[1]}"
        else:
            s_norm = f"{sign}{''.join(parts)}"
    return Decimal(s_norm)


def format_monto_ars(value) -> str:
    """
    Texto para mostrar montos en pesos: $ 1.234.567,89 (miles con punto, decimales con coma).
    """
    d = q2(value)
    us = f"{d:,.2f}"
    ar = us.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {ar}"
