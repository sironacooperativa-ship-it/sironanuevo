"""Consultas compartidas para alertas de stock (dashboard, stock, productos)."""

from __future__ import annotations

from django.db.models import Q

from .models import Producto

# Umbrales de stock crítico por rubro (activos habilitados con stock por debajo).
STOCK_CRITICO_UMBRAL_MED = 20
STOCK_CRITICO_UMBRAL_AC_OT = 10

STOCK_CRITICO_Q = Q(habilitado=True) & (
    Q(tipo=Producto.Tipo.MEDICAMENTOS, stock__lt=STOCK_CRITICO_UMBRAL_MED)
    | Q(
        tipo__in=(Producto.Tipo.ACCESORIOS, Producto.Tipo.OTROS),
        stock__lt=STOCK_CRITICO_UMBRAL_AC_OT,
    )
)

# Todo lo que el inicio resume como «alerta»: críticos + deshabilitados por falta de stock.
STOCK_ALERTAS_Q = STOCK_CRITICO_Q | Q(deshabilitado_por_stock=True)


def umbral_stock_critico(tipo: str) -> int | None:
    if tipo == Producto.Tipo.MEDICAMENTOS:
        return STOCK_CRITICO_UMBRAL_MED
    if tipo in (Producto.Tipo.ACCESORIOS, Producto.Tipo.OTROS):
        return STOCK_CRITICO_UMBRAL_AC_OT
    return None


def es_stock_critico(*, tipo: str, stock: int, habilitado: bool = True) -> bool:
    if not habilitado:
        return False
    umbral = umbral_stock_critico(tipo)
    if umbral is None:
        return False
    return int(stock or 0) < umbral


def queryset_stock_critico():
    return Producto.objects.filter(STOCK_CRITICO_Q)


def queryset_stock_alertas():
    return Producto.objects.filter(STOCK_ALERTAS_Q).distinct()
