from django import template

from core.money_decimal import format_monto_ars

register = template.Library()


@register.filter
def ars(value):
    """Formato monetario AR: $ 1.234.567,89 (miles con punto, decimales con coma)."""
    return format_monto_ars(value)

