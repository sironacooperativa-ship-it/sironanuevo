"""Propagación de precio de catálogo a listas donde está el producto."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction

from core.money_decimal import q2, redondear_precio_mostrador_ars

from .models import ListaPrecioItem, ListaPrecios, Producto


def _farmacia_lista() -> ListaPrecios | None:
    return ListaPrecios.objects.filter(es_farmacia=True).order_by("id").first()


def listas_del_producto(producto: Producto) -> list[dict]:
    """Listas en las que el producto está incluido hoy."""
    filas: list[dict] = []
    farmacia = _farmacia_lista()
    if farmacia and producto.en_lista_precios:
        filas.append(
            {
                "lista_id": farmacia.pk,
                "nombre": farmacia.nombre,
                "es_farmacia": True,
                "precio_actual": q2(producto.precio_venta),
            }
        )
    for item in (
        ListaPrecioItem.objects.filter(producto=producto)
        .select_related("lista")
        .order_by("lista__nombre")
    ):
        if item.lista.es_farmacia:
            continue
        filas.append(
            {
                "lista_id": item.lista_id,
                "nombre": item.lista.nombre,
                "es_farmacia": False,
                "precio_actual": q2(item.precio_venta),
            }
        )
    return filas


def precio_propuesto_desde_post(post) -> Decimal:
    raw = (post.get("precio_venta") or "").strip().replace(",", ".")
    if raw:
        try:
            return q2(Decimal(raw))
        except (InvalidOperation, ValueError):
            pass
    costo_raw = (post.get("costo") or "").strip().replace(",", ".")
    pct_raw = (post.get("porcentaje_ganancia") or "").strip().replace(",", ".")
    try:
        costo = Decimal(costo_raw) if costo_raw else Decimal("0")
        pct = Decimal(pct_raw) if pct_raw else Decimal("0")
    except (InvalidOperation, ValueError):
        costo = Decimal("0")
        pct = Decimal("0")
    return redondear_precio_mostrador_ars(costo * (Decimal("1.0") + (pct / Decimal("100"))))


def comparativa_listas_producto(producto: Producto, precio_propuesto: Decimal) -> list[dict]:
    out = []
    prop = q2(precio_propuesto)
    for row in listas_del_producto(producto):
        actual = row["precio_actual"]
        diff = q2(prop - actual)
        out.append(
            {
                **row,
                "precio_propuesto": prop,
                "impacta": actual != prop,
                "diferencia": diff,
            }
        )
    return out


def aplicar_precio_a_listas(producto: Producto, lista_ids: set[int], precio: Decimal) -> int:
    """Actualiza precio en listas rubro marcadas. Farmacia usa Producto.precio_venta (ya guardado)."""
    precio_q = q2(precio)
    actualizados = 0
    if not lista_ids:
        return 0
    rubro_ids = set(
        ListaPrecios.objects.filter(pk__in=lista_ids, es_farmacia=False).values_list("pk", flat=True)
    )
    if not rubro_ids:
        return 0
    with transaction.atomic():
        actualizados = ListaPrecioItem.objects.filter(
            producto=producto, lista_id__in=rubro_ids
        ).update(precio_venta=precio_q)
    return actualizados


def parse_aplicar_precio_listas_post(post) -> set[int]:
    return {int(x) for x in post.getlist("aplicar_precio_listas") if str(x).isdigit()}
