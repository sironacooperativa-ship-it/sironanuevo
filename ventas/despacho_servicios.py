"""Consultas y reglas de negocio para el módulo Despachos."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import Venta, VentaLinea

DESPACHO_HISTORIAL_DIAS = 7


def archivar_lineas_pedido_despachado(venta: Venta) -> int:
    """
    Al marcar despachado: congela código/descripción/marca en la línea y suelta el vínculo con Producto.
    El pedido queda como archivo plano (precios ya están en precio_unitario/subtotal).
    """
    if not venta.despacho_despachado:
        return 0
    n = 0
    for ln in VentaLinea.objects.filter(venta_id=venta.pk).select_related("producto"):
        updates: dict = {}
        prod = ln.producto
        if prod:
            if not (ln.codigo_snapshot or "").strip():
                updates["codigo_snapshot"] = (prod.codigo or "")[:6]
            if not (ln.descripcion_snapshot or "").strip():
                updates["descripcion_snapshot"] = (prod.descripcion or "")[:255]
            if not (ln.marca_snapshot or "").strip():
                updates["marca_snapshot"] = (getattr(prod, "laboratorio", None) or "")[:120]
            updates["producto_id"] = None
        elif prod is None and not (ln.codigo_snapshot or "").strip():
            continue
        if updates:
            VentaLinea.objects.filter(pk=ln.pk).update(**updates)
            n += 1
    return n


def marcar_pedidos_armados(venta_ids: list[int]) -> list[dict]:
    """
    Marca pedidos como armados sin tocar el flag de despachado (p. ej. al imprimir armado colectivo).
    """
    ids = [int(x) for x in venta_ids if x]
    if not ids:
        return []
    Venta.objects.filter(pk__in=ids, despacho_armado=False).update(despacho_armado=True)
    return [venta_despacho_json_payload(v) for v in Venta.objects.filter(pk__in=ids)]


def marcar_pedidos_despachados(venta_ids: list[int], *, usuario=None) -> list[dict]:
    """
    Marca pedidos como despachados, archiva líneas y devuelve payloads para sincronizar la UI.
    """
    ids = [int(x) for x in venta_ids if x]
    if not ids:
        return []
    payloads: list[dict] = []
    update_fields = [
        "despacho_armado",
        "despacho_despachado",
        "despacho_despachado_en",
        "actualizado_en",
    ]
    if usuario is not None:
        update_fields.append("actualizado_por")

    for venta in Venta.objects.filter(pk__in=ids):
        if not venta.despacho_despachado:
            venta.aplicar_estado_despacho(armado=True, despachado=True)
            if usuario is not None:
                venta.actualizado_por = usuario
            venta.save(update_fields=update_fields)
        archivar_lineas_pedido_despachado(venta)
        payloads.append(venta_despacho_json_payload(venta))
    return payloads


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
