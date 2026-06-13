"""Consultas y reglas de negocio para el módulo Despachos."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import Venta

DESPACHO_HISTORIAL_DIAS = 7


def cutoff_despacho_historial():
    """Pedidos despachados antes de esta fecha van al historial."""
    return timezone.now() - timedelta(days=DESPACHO_HISTORIAL_DIAS)


def ventas_despachos_activos_queryset():
    """Pedidos visibles en Despachos: activos o despachados hace menos de 7 días."""
    cutoff = cutoff_despacho_historial()
    return (
        Venta.objects.select_related("vendedor", "comprador")
        .exclude(despacho_despachado=True, despacho_despachado_en__lt=cutoff)
        .order_by("-creado_en", "-id")
    )


def ventas_despachos_historial_queryset():
    """Pedidos despachados hace más de 7 días."""
    cutoff = cutoff_despacho_historial()
    return (
        Venta.objects.select_related("vendedor", "comprador")
        .filter(despacho_despachado=True, despacho_despachado_en__lt=cutoff)
        .order_by("-despacho_despachado_en", "-creado_en", "-id")
    )


def venta_despacho_json_payload(venta: Venta) -> dict:
    """Respuesta JSON unificada al actualizar estado de despacho."""
    despachado_en = None
    if venta.despacho_despachado_en:
        despachado_en = timezone.localtime(venta.despacho_despachado_en).strftime(
            "%d/%m/%Y %H:%M"
        )
    return {
        "ok": True,
        "venta_id": venta.pk,
        "estado": venta.despacho_estado,
        "label": venta.despacho_estado_label,
        "despacho_armado": venta.despacho_armado,
        "despacho_despachado": venta.despacho_despachado,
        "despacho_despachado_en": despachado_en,
    }
