from decimal import Decimal, ROUND_HALF_UP

from django import template

register = template.Library()


@register.filter
def ars(value):
    """
    Formato monetario AR: $ 1.234.567,89
    """
    if value is None:
        return "$ 0,00"
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except Exception:
            return str(value)
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    us = f"{value:,.2f}"  # 1,234,567.89
    ar = us.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {ar}"

