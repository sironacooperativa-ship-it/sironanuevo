"""Agregación de líneas para armado colectivo de pedidos."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from core.money_decimal import q2

from .models import PuntoStockArmado, Venta, VentaLinea


@dataclass
class LineaArmadoColectivo:
    producto_id: int
    codigo: str
    descripcion: str
    marca: str
    cantidad_total: int
    costo_unitario: Decimal
    precio_venta: Decimal
    subtotal_precio: Decimal
    venta_ids: set[int] = field(default_factory=set)


def ventas_no_armadas_queryset():
    return (
        Venta.objects.filter(despacho_armado=False, despacho_despachado=False)
        .select_related("vendedor", "comprador")
        .order_by("-creado_en", "-id")
    )


def ventas_validas_para_armado_colectivo(venta_ids: list[int]) -> list[Venta]:
    if not venta_ids:
        return []
    qs = ventas_no_armadas_queryset().filter(pk__in=venta_ids)
    return list(qs)


def agregar_lineas_armado_colectivo(venta_ids: list[int]) -> list[LineaArmadoColectivo]:
    if not venta_ids:
        return []
    lineas = (
        VentaLinea.objects.filter(venta_id__in=venta_ids)
        .select_related("producto")
        .order_by("producto__descripcion", "producto__codigo", "id")
    )
    acc: dict[int, dict] = defaultdict(
        lambda: {
            "cantidad": 0,
            "subtotal_precio": Decimal("0.00"),
            "producto": None,
            "venta_ids": set(),
        }
    )
    for ln in lineas:
        pid = ln.producto_id
        row = acc[pid]
        row["producto"] = ln.producto
        row["cantidad"] += int(ln.cantidad or 0)
        row["subtotal_precio"] += q2(ln.precio_unitario) * int(ln.cantidad or 0)
        row["venta_ids"].add(ln.venta_id)

    out: list[LineaArmadoColectivo] = []
    for pid, row in sorted(acc.items(), key=lambda x: (x[1]["producto"].descripcion, x[1]["producto"].codigo)):
        prod = row["producto"]
        qty = int(row["cantidad"])
        sub = q2(row["subtotal_precio"])
        precio = q2(sub / qty) if qty else Decimal("0.00")
        out.append(
            LineaArmadoColectivo(
                producto_id=pid,
                codigo=str(prod.codigo),
                descripcion=str(prod.descripcion or ""),
                marca=(getattr(prod, "laboratorio", None) or "").strip(),
                cantidad_total=qty,
                costo_unitario=q2(prod.costo or Decimal("0.00")),
                precio_venta=precio,
                subtotal_precio=sub,
                venta_ids=set(row["venta_ids"]),
            )
        )
    return out


def puntos_stock_armado_lista() -> list[PuntoStockArmado]:
    return list(PuntoStockArmado.objects.all().order_by("orden", "nombre", "id"))


def parse_asignaciones_post(post, producto_ids: set[int], puntos: list[PuntoStockArmado]) -> dict[int, dict[int, int]]:
    """
    Lee asignaciones alloc_{producto_id}_{punto_id} del POST.
    Retorna {producto_id: {punto_id: cantidad}}.
    """
    punto_ids = {p.pk for p in puntos}
    out: dict[int, dict[int, int]] = {pid: {} for pid in producto_ids}
    for pid in producto_ids:
        for punto in puntos:
            key = f"alloc_{pid}_{punto.pk}"
            raw = (post.get(key) or "").strip()
            if not raw:
                continue
            try:
                qty = int(raw)
            except (ValueError, TypeError):
                qty = -1
            if qty < 0:
                raise ValueError(f"Cantidad inválida para producto #{pid} en {punto.nombre}.")
            if qty > 0:
                out[pid][punto.pk] = qty
    return out


def validar_asignaciones(
    lineas: list[LineaArmadoColectivo],
    asignaciones: dict[int, dict[int, int]],
) -> str | None:
    for ln in lineas:
        por_punto = asignaciones.get(ln.producto_id) or {}
        total_asig = sum(por_punto.values())
        if total_asig > ln.cantidad_total:
            return (
                f"La suma en puntos de stock ({total_asig}) supera la cantidad total "
                f"({ln.cantidad_total}) para {ln.codigo} — {ln.descripcion}."
            )
    return None


def lineas_con_celdas_alloc(
    lineas: list[LineaArmadoColectivo],
    puntos: list[PuntoStockArmado],
    post=None,
) -> list[LineaArmadoColectivo]:
    for ln in lineas:
        celdas = []
        for p in puntos:
            key = f"alloc_{ln.producto_id}_{p.pk}"
            val = (post.get(key) or "").strip() if post is not None else ""
            celdas.append({"punto": p, "value": val})
        ln.alloc_cells = celdas  # type: ignore[attr-defined]
    return lineas
