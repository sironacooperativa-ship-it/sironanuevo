from django import template

from core.money_decimal import q2

register = template.Library()


@register.filter
def ars(value):
    """
    Formato monetario AR: $ 1.234.567,89 (máx. 2 decimales).
    """
    d = q2(value)
    us = f"{d:,.2f}"  # 1,234,567.89
    ar = us.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {ar}"

