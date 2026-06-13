"""Agregación de líneas para armado colectivo de pedidos."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from core.money_decimal import q2

from .models import (
    ArmadoColectivoAsignacion,
    ArmadoColectivoGuardado,
    ArmadoColectivoLineaGuardada,
    PuntoStockArmado,
    Venta,
    VentaLinea,
)


def construir_nombre_armado_colectivo(venta_ids: list[int]) -> str:
    ids = sorted({int(x) for x in venta_ids})
    return ", ".join(f"Pedido #{i}" for i in ids)


def venta_ids_en_armado_guardado() -> set[int]:
    return set(
        Venta.objects.filter(armados_colectivos_guardados__isnull=False)
        .values_list("pk", flat=True)
        .distinct()
    )


def venta_ids_armado(armado_id: int) -> set[int]:
    return set(
        Venta.objects.filter(armados_colectivos_guardados__pk=armado_id)
        .values_list("pk", flat=True)
        .distinct()
    )


def venta_ids_reservados_para_lista(armado_edit_id: int | None = None) -> set[int]:
    """Pedidos reservados en armados guardados, excepto los del armado en edición."""
    reservados = venta_ids_en_armado_guardado()
    if armado_edit_id:
        reservados -= venta_ids_armado(armado_edit_id)
    return reservados


def armados_colectivos_guardados_lista(limit: int = 50):
    return (
        ArmadoColectivoGuardado.objects.prefetch_related("ventas")
        .order_by("-creado_en", "-id")[:limit]
    )


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


def ventas_validas_para_armado_colectivo(
    venta_ids: list[int],
    *,
    armado_edit_id: int | None = None,
) -> list[Venta]:
    if not venta_ids:
        return []
    reservados = venta_ids_en_armado_guardado()
    if armado_edit_id:
        reservados -= venta_ids_armado(armado_edit_id)
    if reservados.intersection(venta_ids):
        return []
    qs = ventas_no_armadas_queryset().filter(pk__in=venta_ids).exclude(pk__in=reservados)
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
            if post is None:
                val = ""
            elif hasattr(post, "get"):
                val = (post.get(key) or "").strip()
            elif isinstance(post, dict):
                val = str(post.get(key) or "").strip()
            else:
                val = ""
            celdas.append({"punto": p, "value": val})
        ln.alloc_cells = celdas  # type: ignore[attr-defined]
    return lineas


def _persistir_lineas_y_asignaciones(
    armado: ArmadoColectivoGuardado,
    lineas: list[LineaArmadoColectivo],
    asignaciones: dict[int, dict[int, int]],
    puntos: list[PuntoStockArmado],
) -> None:
    armado.lineas.all().delete()
    punto_by_id = {p.pk: p for p in puntos}
    for orden, ln in enumerate(lineas):
        linea_db = ArmadoColectivoLineaGuardada.objects.create(
            armado=armado,
            producto_id=ln.producto_id,
            codigo=ln.codigo,
            descripcion=ln.descripcion,
            cantidad_total=ln.cantidad_total,
            costo_unitario=ln.costo_unitario,
            precio_venta=ln.precio_venta,
            orden=orden,
        )
        for punto_id, qty in (asignaciones.get(ln.producto_id) or {}).items():
            if qty <= 0:
                continue
            punto = punto_by_id.get(punto_id)
            if punto is None:
                continue
            ArmadoColectivoAsignacion.objects.create(
                linea=linea_db,
                punto=punto,
                cantidad=int(qty),
            )


def guardar_armado_colectivo(
    *,
    venta_ids: list[int],
    lineas: list[LineaArmadoColectivo],
    asignaciones: dict[int, dict[int, int]],
    puntos: list[PuntoStockArmado],
    usuario,
) -> ArmadoColectivoGuardado:
    from django.db import transaction

    with transaction.atomic():
        armado = ArmadoColectivoGuardado.objects.create(
            nombre=construir_nombre_armado_colectivo(venta_ids),
            creado_por=usuario if getattr(usuario, "is_authenticated", False) else None,
        )
        armado.ventas.set(venta_ids)
        _persistir_lineas_y_asignaciones(armado, lineas, asignaciones, puntos)
        return armado


def actualizar_armado_colectivo(
    armado_id: int,
    *,
    venta_ids: list[int],
    lineas: list[LineaArmadoColectivo],
    asignaciones: dict[int, dict[int, int]],
    puntos: list[PuntoStockArmado],
) -> ArmadoColectivoGuardado:
    from django.db import transaction

    with transaction.atomic():
        armado = ArmadoColectivoGuardado.objects.select_for_update().get(pk=armado_id)
        armado.nombre = construir_nombre_armado_colectivo(venta_ids)
        armado.requiere_revision = False
        armado.nota_revision = ""
        armado.save(update_fields=["nombre", "requiere_revision", "nota_revision"])
        armado.ventas.set(venta_ids)
        _persistir_lineas_y_asignaciones(armado, lineas, asignaciones, puntos)
        return armado


def lineas_desde_armado_guardado(armado: ArmadoColectivoGuardado, puntos: list[PuntoStockArmado]):
    """Construye filas de visualización desde un armado guardado."""
    filas = []
    for linea_db in armado.lineas.select_related("producto").prefetch_related("asignaciones__punto"):
        asig_map = {a.punto_id: a.cantidad for a in linea_db.asignaciones.all()}
        celdas = []
        for p in puntos:
            qty = asig_map.get(p.pk, 0)
            celdas.append({"punto": p, "value": str(qty) if qty else ""})
        filas.append(
            {
                "producto_id": linea_db.producto_id,
                "codigo": linea_db.codigo,
                "descripcion": linea_db.descripcion,
                "cantidad_total": linea_db.cantidad_total,
                "costo_unitario": linea_db.costo_unitario,
                "precio_venta": linea_db.precio_venta,
                "alloc_cells": celdas,
                "asignado_sum": sum(asig_map.values()),
            }
        )
    return filas


def lineas_armado_colectivo_desde_guardado(armado: ArmadoColectivoGuardado) -> list[LineaArmadoColectivo]:
    out: list[LineaArmadoColectivo] = []
    for linea_db in armado.lineas.select_related("producto"):
        sub = q2(linea_db.precio_venta) * int(linea_db.cantidad_total)
        out.append(
            LineaArmadoColectivo(
                producto_id=linea_db.producto_id,
                codigo=linea_db.codigo,
                descripcion=linea_db.descripcion,
                marca=(getattr(linea_db.producto, "laboratorio", None) or "").strip(),
                cantidad_total=int(linea_db.cantidad_total),
                costo_unitario=q2(linea_db.costo_unitario),
                precio_venta=q2(linea_db.precio_venta),
                subtotal_precio=sub,
            )
        )
    return out


def asignaciones_desde_armado_guardado(armado: ArmadoColectivoGuardado) -> dict[int, dict[int, int]]:
    out: dict[int, dict[int, int]] = {}
    for linea_db in armado.lineas.prefetch_related("asignaciones"):
        por_punto: dict[int, int] = {}
        for a in linea_db.asignaciones.all():
            por_punto[a.punto_id] = int(a.cantidad)
        out[linea_db.producto_id] = por_punto
    return out


SESSION_ARMADO_PRESELECT = "armado_colectivo_preselect_ids"
SESSION_ARMADO_PREFILL = "armado_colectivo_prefill"
SESSION_ARMADO_EDIT_ID = "armado_colectivo_edit_id"


def normalizar_ids_sesion(raw) -> list[int]:
    """Convierte valores de sesión (lista, int suelto, etc.) a IDs de pedido."""
    if raw is None:
        return []
    if isinstance(raw, int):
        candidatos = [raw]
    elif isinstance(raw, (list, tuple, set)):
        candidatos = list(raw)
    else:
        try:
            candidatos = list(raw)
        except TypeError:
            return []
    out: list[int] = []
    for x in candidatos:
        xs = str(x).strip()
        if xs.isdigit():
            out.append(int(xs))
    return out


def tomar_preselect_ids(request) -> list[int]:
    """Lee y limpia IDs preseleccionados guardados en sesión."""
    raw = request.session.pop(SESSION_ARMADO_PRESELECT, None)
    ids = normalizar_ids_sesion(raw)
    if raw is not None:
        request.session.modified = True
    return ids


def armado_edit_id_desde_sesion(session) -> int | None:
    raw = session.get(SESSION_ARMADO_EDIT_ID)
    if raw is None:
        return None
    if isinstance(raw, int):
        pk = raw
    elif str(raw).strip().isdigit():
        pk = int(str(raw).strip())
    else:
        session.pop(SESSION_ARMADO_EDIT_ID, None)
        return None
    if not ArmadoColectivoGuardado.objects.filter(pk=pk).exists():
        session.pop(SESSION_ARMADO_EDIT_ID, None)
        return None
    return pk


def reconstruir_lineas_armado_guardado(armado: ArmadoColectivoGuardado, venta_ids: list[int]) -> None:
    """Recalcula líneas del armado guardado sin asignaciones de stock."""
    armado.lineas.all().delete()
    lineas = agregar_lineas_armado_colectivo(venta_ids)
    for orden, ln in enumerate(lineas):
        ArmadoColectivoLineaGuardada.objects.create(
            armado=armado,
            producto_id=ln.producto_id,
            codigo=ln.codigo,
            descripcion=ln.descripcion,
            cantidad_total=ln.cantidad_total,
            costo_unitario=ln.costo_unitario,
            precio_venta=ln.precio_venta,
            orden=orden,
        )


def sincronizar_armados_al_eliminar_venta(venta_id: int) -> None:
    """
    Quita la venta de armados guardados y recalcula cantidades.
    Marca el armado para revisión si quedan pedidos; lo borra si no queda ninguno.
    """
    from django.db import transaction

    armados = list(
        ArmadoColectivoGuardado.objects.filter(ventas__pk=venta_id).distinct()
    )
    if not armados:
        return

    with transaction.atomic():
        for armado in armados:
            armado.ventas.remove(venta_id)
            restantes = list(armado.ventas.values_list("pk", flat=True))
            if not restantes:
                armado.delete()
                continue
            reconstruir_lineas_armado_guardado(armado, restantes)
            armado.nombre = construir_nombre_armado_colectivo(restantes)
            armado.requiere_revision = True
            armado.nota_revision = (
                f"Se eliminó el pedido #{venta_id} del historial de ventas. "
                "Revise las cantidades y vuelva a asignar el stock por punto."
            )
            armado.save(
                update_fields=["nombre", "requiere_revision", "nota_revision"]
            )


def preparar_edicion_armado(armado: ArmadoColectivoGuardado) -> tuple[list[int], dict[str, str]]:
    """Datos para reabrir un armado: pedidos y asignaciones previas (si no requiere revisión)."""
    venta_ids = list(armado.ventas.values_list("pk", flat=True))
    prefill: dict[str, str] = {}
    if not armado.requiere_revision:
        asig = asignaciones_desde_armado_guardado(armado)
        for pid, por_punto in asig.items():
            for punto_id, qty in por_punto.items():
                if qty > 0:
                    prefill[f"alloc_{pid}_{punto_id}"] = str(qty)
    return venta_ids, prefill
