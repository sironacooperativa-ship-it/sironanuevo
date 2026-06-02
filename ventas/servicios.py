"""Lógica compartida para confirmar un pedido (venta) con stock y calendario."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from calendario.models import Evento
from caja.models import MovimientoCaja
from core.money_decimal import format_monto_ars, q2
from productos.models import ListaPrecioItem, ListaPrecios, Producto

from presupuestos.models import Presupuesto

from .models import Venta, VentaLinea


def venta_costo_mercaderia_actual(venta: Venta) -> Decimal:
    """Suma cantidad × costo vigente del producto por línea (requiere líneas con producto cargado)."""
    total = Decimal("0.00")
    for ln in venta.lineas.all():
        cu = q2(ln.producto.costo or Decimal("0.00"))
        total += q2(Decimal(ln.cantidad) * cu)
    return q2(total)


def venta_aplicar_snapshot_ganancia_cobro(venta: Venta) -> None:
    """Congela neto, costo de mercadería y ganancia en el objeto (guardar con save)."""
    net = q2(venta.neto)
    cm = venta_costo_mercaderia_actual(venta)
    venta.neto_cobro = net
    venta.costo_mercaderia_cobro = cm
    venta.ganancia_cobro = q2(net - cm)


def sync_evento_pedido_pendiente(venta: Venta) -> None:
    """Crea, actualiza o elimina el evento de calendario según la fecha de vencimiento del pedido."""
    titulo = f"Pago pendiente — Pedido #{venta.pk}"
    qs = Evento.objects.filter(tipo=Evento.Tipo.PEDIDO, titulo=titulo)
    extra = f" Comprador: {venta.comprador}." if venta.comprador_id else ""
    com_txt = (
        f"Comisión ({venta.comision_porcentaje}%): {format_monto_ars(venta.monto_comision)} (se liquida mensualmente)."
        if venta.aplica_comision
        else "Sin comisión al vendedor."
    )
    ingreso_txt = (
        f"Ingreso en caja al cobrar: {format_monto_ars(venta.monto_ingreso_caja)} (neto menos comisión en el pedido)."
        if venta.aplica_comision and venta.comision_descontada_en_pedido
        else f"Ingreso en caja al cobrar: {format_monto_ars(venta.monto_ingreso_caja)} (neto del pedido)."
    )
    desc = (
        f"Vendedor: {venta.vendedor}. "
        f"Monto neto pedido: {format_monto_ars(venta.neto)}. {com_txt} "
        f"{ingreso_txt}{extra}"
    )
    if venta.fecha_vencimiento_pago is None:
        qs.delete()
        return
    if qs.exists():
        qs.update(fecha=venta.fecha_vencimiento_pago, descripcion=desc)
    else:
        Evento.objects.create(
            fecha=venta.fecha_vencimiento_pago,
            titulo=titulo,
            tipo=Evento.Tipo.PEDIDO,
            descripcion=desc,
        )


def revertir_cobro_pedido_desde_movimiento_caja(mov: MovimientoCaja, user) -> bool:
    """
    Si `mov` es el ingreso de caja del cobro de un pedido pagado, pasa el pedido a pendiente,
    sincroniza calendario y elimina el movimiento. Devuelve True si aplicó.

    Si el pedido ya entró en una liquidación de comisión pagada, levanta ValidationError.
    """
    if mov.tipo != MovimientoCaja.Tipo.INGRESO or not mov.venta_id:
        return False
    vid = int(mov.venta_id)
    qs = Venta.objects
    try:
        qs = qs.select_for_update(of=("self",))
    except TypeError:
        qs = qs.select_for_update()
    venta = qs.filter(pk=vid).first()
    if venta is None:
        return False
    if venta.estado != Venta.Estado.PAGADA or venta.pago_movimiento_id != mov.pk:
        return False
    if venta.comision_liquidacion_pago_id:
        raise ValidationError(
            "Este pedido ya figura en una liquidación de comisión pagada. "
            "No se puede anular el cobro desde caja sin corregir esa liquidación."
        )
    venta.estado = Venta.Estado.PENDIENTE
    venta.pago_movimiento = None
    venta.neto_cobro = None
    venta.costo_mercaderia_cobro = None
    venta.ganancia_cobro = None
    venta.actualizado_por = user
    venta.save(
        update_fields=[
            "estado",
            "pago_movimiento",
            "actualizado_por",
            "neto_cobro",
            "costo_mercaderia_cobro",
            "ganancia_cobro",
        ]
    )
    sync_evento_pedido_pendiente(venta)
    mov.delete()
    return True


def parse_stock_venta_json_from_post(post) -> dict[int, tuple[bool, bool]] | None:
    """
    Lee `stock_venta_json` del POST: { "producto_id": { "neg": bool, "desh": bool } }.
    neg = permitir vender por encima del stock (saldo negativo). desh = si queda en 0, deshabilitar producto.
    """
    raw = (post.get("stock_venta_json") or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("El formato de confirmación de stock no es válido.") from exc
    if not isinstance(data, dict):
        raise ValidationError("El formato de confirmación de stock no es válido.")
    out: dict[int, tuple[bool, bool]] = {}
    for k, v in data.items():
        try:
            pid = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            out[pid] = (bool(v.get("neg")), bool(v.get("desh", True)))
        elif isinstance(v, (list, tuple)) and len(v) >= 2:
            out[pid] = (bool(v[0]), bool(v[1]))
    return out or None


def demanda_por_producto_desde_specs(line_specs: list[tuple]) -> dict[int, int]:
    d: defaultdict[int, int] = defaultdict(int)
    for spec in line_specs:
        prod, qty, *_ = unpack_linea_spec(spec)
        d[int(prod.pk)] += int(qty)
    return dict(d)


def merge_stock_confirmacion_venta_locked(
    line_specs: list[tuple],
    stock_confirmacion: dict[int, tuple[bool, bool]] | None,
) -> dict[int, tuple[bool, bool]]:
    """
    Bloquea productos involucrados, valida saldos y devuelve la tabla definitiva
    producto_id -> (permitir_negativo, deshabilitar_si_queda_en_cero).
    """
    demanda = demanda_por_producto_desde_specs(line_specs)
    if not demanda:
        return {}
    pids = sorted(demanda.keys())
    productos = list(Producto.objects.select_for_update().filter(pk__in=pids).order_by("pk"))
    if len(productos) != len(pids):
        raise ValidationError("Uno o más productos de la venta ya no existen.")
    stock_map = {int(p.pk): int(p.stock) for p in productos}
    merged: dict[int, tuple[bool, bool]] = {}
    for pid, qsum in demanda.items():
        avail = int(stock_map.get(pid, 0))
        permitir_neg = False
        desh_cero = True
        if stock_confirmacion is not None and pid in stock_confirmacion:
            permitir_neg, desh_cero = stock_confirmacion[pid]
        if qsum > avail and not permitir_neg:
            codigo = (
                Producto.objects.filter(pk=pid).values_list("codigo", flat=True).first() or str(pid)
            )
            raise ValidationError(
                f"Stock insuficiente para {codigo} (pedido: {qsum}, disponible: {avail}). "
                "Confirmá en el cartel si permitís saldo negativo o ajustá las cantidades."
            )
        merged[pid] = (permitir_neg, desh_cero)
    return merged


def unpack_linea_spec(spec: tuple) -> tuple:
    """
    Línea de pedido/presupuesto: (prod, qty, pu, st) o
    (prod, qty, pu, st, codigo_snap, descripcion_snap).
    """
    prod, qty, pu, st = spec[:4]
    if len(spec) >= 6:
        cod, desc = str(spec[4] or ""), str(spec[5] or "")
    else:
        cod, desc = prod.codigo, prod.descripcion
    return prod, qty, pu, st, cod, desc


def sincronizar_productos_lista_elegida_en_venta(
    lista: ListaPrecios | None,
    line_specs: list[tuple],
) -> None:
    """
    Después de armar un pedido con un rubro de lista elegido, refleja eso en catálogo/listas:
    - Lista Farmacia: marca `en_lista_precios` en los productos vendidos (salen en PDF de Farmacia).
    - Lista de rubro: agrega/actualiza `ListaPrecioItem` con el precio unitario usado en el pedido.
    """
    if lista is None or not line_specs:
        return
    por_producto: dict[int, tuple[Producto, Decimal]] = {}
    for spec in line_specs:
        prod, qty, pu, st, cod, desc = unpack_linea_spec(spec)
        por_producto[prod.pk] = (prod, q2(pu))

    with transaction.atomic():
        if lista.es_farmacia:
            pids = list(por_producto.keys())
            if pids:
                Producto.objects.filter(pk__in=pids).update(en_lista_precios=True)
        else:
            for pid, (_prod, pu) in por_producto.items():
                ListaPrecioItem.objects.update_or_create(
                    lista=lista,
                    producto_id=pid,
                    defaults={"precio_venta": pu},
                )


def crear_venta_confirmada(
    vendedor_id: int,
    fecha_vencimiento_pago: Optional[date],
    descuento_monto: Decimal,
    comision_porcentaje: Decimal,
    line_specs: list[tuple],
    comprador_id: int | None = None,
    creado_por_id: int | None = None,
    *,
    aplica_comision: bool = False,
    envio: Decimal = Decimal("0.00"),
    stock_confirmacion: dict[int, tuple[bool, bool]] | None = None,
) -> Venta:
    """
    Crea Venta + líneas, descuenta stock y genera evento en calendario.
    line_specs: tuplas (Producto, cantidad, precio_unitario, subtotal)
    o con texto congelado: (..., codigo_snapshot, descripcion_snapshot).

    stock_confirmacion: por producto_id, (permitir_negativo, deshabilitar_si_queda_en_cero).
    Si es None, no se permite vender por encima del stock y, si queda en 0, se deshabilita (comportamiento previo).
    """
    subtotal = sum((t[3] for t in line_specs), Decimal("0.00"))
    with transaction.atomic():
        merged = merge_stock_confirmacion_venta_locked(line_specs, stock_confirmacion)
        venta = Venta.objects.create(
            vendedor_id=vendedor_id,
            comprador_id=comprador_id,
            fecha_vencimiento_pago=fecha_vencimiento_pago,
            subtotal_lineas=subtotal,
            descuento_monto=descuento_monto,
            envio=envio,
            comision_porcentaje=comision_porcentaje,
            aplica_comision=aplica_comision,
            creado_por_id=creado_por_id,
            actualizado_por_id=creado_por_id,
        )
        for spec in line_specs:
            prod, qty, pu, st, cod_snap, desc_snap = unpack_linea_spec(spec)
            VentaLinea.objects.create(
                venta=venta,
                producto=prod,
                cantidad=qty,
                precio_unitario=pu,
                subtotal=st,
                codigo_snapshot=cod_snap[:6] if cod_snap else "",
                descripcion_snapshot=(desc_snap or "")[:255],
            )
            Producto.objects.filter(pk=prod.pk).update(stock=F("stock") - qty)

        Producto.aplicar_deshabilitado_si_queda_en_cero(merged)

        sync_evento_pedido_pendiente(venta)
    return venta


def eliminar_venta_admin(venta: Venta) -> None:
    """
    Elimina un pedido y revierte efectos: stock, evento de calendario, movimiento de caja si estaba pagado.
    Uso administrativo (corrección de datos).
    """
    vid = venta.pk
    with transaction.atomic():
        # En Postgres, `FOR UPDATE` no puede aplicarse sobre el lado nullable de un OUTER JOIN.
        # Como `pago_movimiento` es nullable, evitamos `select_related()` al lockear.
        qs = Venta.objects
        try:
            qs = qs.select_for_update(of=("self",))
        except TypeError:
            qs = qs.select_for_update()
        v = qs.prefetch_related("lineas").get(pk=vid)
        pm_id = v.pago_movimiento_id
        for ln in v.lineas.all():
            Producto.objects.filter(pk=ln.producto_id).update(stock=F("stock") + ln.cantidad)
        Evento.objects.filter(
            tipo=Evento.Tipo.PEDIDO,
            titulo=f"Pago pendiente — Pedido #{v.pk}",
        ).delete()
        # Si el pedido vino de un presupuesto, lo “desaprueba” para que no quede inconsistente.
        try:
            pr = v.presupuesto_origen
        except Presupuesto.DoesNotExist:
            pr = None
        if pr is not None:
            pr.estado = Presupuesto.Estado.ACTIVO
            pr.venta = None
            pr.aprobado_en = None
            pr.aprobado_por = None
            pr.save(update_fields=["estado", "venta", "aprobado_en", "aprobado_por"])

        # Borra cualquier movimiento de caja asociado a la venta (incluye el pago si estaba vinculado).
        MovimientoCaja.objects.filter(venta_id=vid).delete()
        if pm_id:
            MovimientoCaja.objects.filter(pk=pm_id).delete()
        v.delete()
