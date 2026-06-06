"""Payloads JSON de catálogo (ventas, presupuestos, buscadores) con caché en memoria."""

from __future__ import annotations

import os

from django.core.cache import cache

from core.money_decimal import q2

from .models import ListaPrecioItem, ListaPrecios, Producto

_CATALOGO_CACHE_TTL = int(os.environ.get("SIRONA_CATALOGO_CACHE_SECONDS", "45"))
_PICKER_CACHE_TTL = int(os.environ.get("SIRONA_PICKER_CACHE_SECONDS", "45"))


def _rows_to_payload(rows) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "codigo": row["codigo"],
                "descripcion": row["descripcion"],
                "precio": str(q2(row["precio_venta"])),
                "stock": row["stock"],
            }
        )
    return out


def _cached(key: str, ttl: int, builder):
    if ttl <= 0:
        return builder()
    hit = cache.get(key)
    if hit is not None:
        return hit
    val = builder()
    cache.set(key, val, ttl)
    return val


def productos_payload_todos(*, use_cache: bool = True) -> list[dict]:
    def build():
        qs = Producto.objects.filter(habilitado=True).order_by("descripcion", "codigo")
        return _rows_to_payload(qs.values("id", "codigo", "descripcion", "precio_venta", "stock"))

    if not use_cache:
        return build()
    return _cached("sirona:cat:todos:v1", _CATALOGO_CACHE_TTL, build)


def productos_payload_desde_ids(ids: set[int] | list[int]) -> list[dict]:
    id_set = {int(x) for x in ids if x}
    if not id_set:
        return []
    qs = Producto.objects.filter(pk__in=id_set).order_by("descripcion", "codigo")
    return _rows_to_payload(qs.values("id", "codigo", "descripcion", "precio_venta", "stock"))


def productos_payload_para_lineas(lineas: list[dict]) -> list[dict]:
    """Catálogo mínimo para pintar líneas existentes mientras el resto carga por AJAX."""
    ids: set[int] = set()
    for ln in lineas:
        pid = ln.get("producto_id")
        if pid is not None and str(pid).strip().isdigit():
            ids.add(int(pid))
    by_id = {int(p["id"]): p for p in productos_payload_desde_ids(ids)}
    for ln in lineas:
        pid_raw = ln.get("producto_id")
        if pid_raw is None or not str(pid_raw).strip().isdigit():
            continue
        pid = int(pid_raw)
        if pid in by_id:
            continue
        by_id[pid] = {
            "id": pid,
            "codigo": str(ln.get("codigo") or pid),
            "descripcion": str(ln.get("descripcion") or "Producto"),
            "precio": str(ln.get("precio_unitario") or "0.00"),
            "stock": int(ln.get("stock") or 0),
        }
    return list(by_id.values())


def productos_payload_para_lista(lista: ListaPrecios, *, use_cache: bool = True) -> list[dict]:
    cache_key = f"sirona:cat:lista:{lista.pk}:v1"

    def build():
        if lista.es_farmacia:
            qs = Producto.objects.filter(habilitado=True, en_lista_precios=True).order_by(
                "descripcion", "codigo"
            )
            return _rows_to_payload(qs.values("id", "codigo", "descripcion", "precio_venta", "stock"))
        items = (
            ListaPrecioItem.objects.filter(lista=lista, producto__habilitado=True)
            .select_related("producto")
            .order_by("producto__descripcion", "producto__codigo")
        )
        return [
            {
                "id": item.producto_id,
                "codigo": item.producto.codigo,
                "descripcion": item.producto.descripcion,
                "precio": str(q2(item.precio_venta)),
                "stock": item.producto.stock,
            }
            for item in items
        ]

    if not use_cache:
        return build()
    return _cached(cache_key, _CATALOGO_CACHE_TTL, build)


def productos_picker_data(*, use_cache: bool = True) -> list[dict]:
    def build():
        return list(
            Producto.objects.order_by("descripcion", "codigo").values("codigo", "descripcion")[:3000]
        )

    if not use_cache:
        return build()
    return _cached("sirona:picker:productos:v1", _PICKER_CACHE_TTL, build)
