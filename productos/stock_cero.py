"""Decisión al quedar un producto sin stock: vigente vs deshabilitar manual."""

from __future__ import annotations

from django.db import transaction

from .models import Producto


def ids_que_quedaron_en_cero(prev_stock: dict[int, int], producto_ids: list[int]) -> list[int]:
    """Tras F()/save, devuelve IDs que pasaron de stock > 0 a stock <= 0."""
    if not producto_ids:
        return []
    out: list[int] = []
    rows = Producto.objects.filter(pk__in=producto_ids).values_list("pk", "stock")
    for pk, stock in rows:
        prev = int(prev_stock.get(int(pk), 0))
        if prev > 0 and int(stock or 0) <= 0:
            out.append(int(pk))
    return out


def snapshot_stock(producto_ids: list[int]) -> dict[int, int]:
    if not producto_ids:
        return {}
    return {
        int(pk): int(st or 0)
        for pk, st in Producto.objects.filter(pk__in=producto_ids).values_list("pk", "stock")
    }


def resolver_stock_cero(producto_id: int, accion: str) -> Producto | None:
    """
    accion: 'vigente' | 'deshabilitar'
    - vigente: sigue habilitado (si lo estaba) aunque stock sea 0
    - deshabilitar: igual que apagar el interruptor manual en productos
    """
    accion = (accion or "").strip().lower()
    if accion not in ("vigente", "deshabilitar"):
        return None
    with transaction.atomic():
        p = Producto.objects.select_for_update().filter(pk=producto_id).first()
        if p is None or int(p.stock or 0) > 0:
            return p
        if accion == "deshabilitar":
            Producto.deshabilitar_manual([p.pk])
            p.refresh_from_db()
        else:
            # Mantener vigente: asegurar habilitado para ventas/presupuestos.
            if not p.habilitado:
                p.habilitado = True
                p.deshabilitado_por_stock = False
                p.listas_stock_snapshot = None
                p.save(update_fields=["habilitado", "deshabilitado_por_stock", "listas_stock_snapshot"])
        return p


def encolar_prompt_stock_cero(request, producto_ids: list[int]) -> None:
    if not producto_ids or request is None:
        return
    key = "stock_cero_prompt"
    cur = list(request.session.get(key) or [])
    for pid in producto_ids:
        ip = int(pid)
        if ip not in cur:
            cur.append(ip)
    request.session[key] = cur
    request.session.modified = True


def consumir_prompt_stock_cero(request) -> list[dict]:
    key = "stock_cero_prompt"
    ids = request.session.pop(key, []) if request.method == "GET" else list(request.session.get(key) or [])
    if request.method == "GET":
        request.session.modified = True
    return payload_productos_stock_cero(ids)


def payload_productos_stock_cero(producto_ids: list[int]) -> list[dict]:
    qs = Producto.objects.filter(pk__in=producto_ids, stock__lte=0).order_by("descripcion", "codigo")
    return [
        {
            "id": p.pk,
            "codigo": p.codigo,
            "descripcion": p.descripcion,
            "stock": int(p.stock or 0),
            "habilitado": bool(p.habilitado),
        }
        for p in qs
    ]
