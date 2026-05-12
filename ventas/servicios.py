"""Lógica compartida para confirmar un pedido (venta) con stock y calendario."""
from __future__ import annotations

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
    desc = (
        f"Vendedor: {venta.vendedor}. "
        f"Monto neto pedido: {format_monto_ars(venta.neto)}. {com_txt} "
        f"Ingreso en caja al cobrar: {format_monto_ars(venta.monto_ingreso_caja)} (importe íntegro al neto).{extra}"
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
    venta.actualizado_por = user
    venta.save(update_fields=["estado", "pago_movimiento", "actualizado_por"])
    sync_evento_pedido_pendiente(venta)
    mov.delete()
    return True


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
) -> Venta:
    """
    Crea Venta + líneas, descuenta stock y genera evento en calendario.
    line_specs: tuplas (Producto, cantidad, precio_unitario, subtotal)
    o con texto congelado: (..., codigo_snapshot, descripcion_snapshot).
    """
    subtotal = sum((t[3] for t in line_specs), Decimal("0.00"))
    with transaction.atomic():
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
        pids_afectados: list[int] = []
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
            pids_afectados.append(prod.pk)

        Producto.deshabilitar_sin_stock(pids_afectados)

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
