"""Lógica compartida para confirmar un pedido (venta) con stock y calendario."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import F

from calendario.models import Evento
from core.money_decimal import format_monto_ars
from productos.models import Producto

from .models import Venta, VentaLinea


def crear_venta_confirmada(
    vendedor_id: int,
    fecha_vencimiento_pago: Optional[date],
    descuento_monto: Decimal,
    comision_porcentaje: Decimal,
    line_specs: list[tuple],
    comprador_id: int | None = None,
    creado_por_id: int | None = None,
    *,
    aplica_comision: bool = True,
) -> Venta:
    """
    Crea Venta + líneas, descuenta stock y genera evento en calendario.
    line_specs: tuplas (Producto, cantidad, precio_unitario, subtotal).
    """
    subtotal = sum((t[3] for t in line_specs), Decimal("0.00"))
    with transaction.atomic():
        venta = Venta.objects.create(
            vendedor_id=vendedor_id,
            comprador_id=comprador_id,
            fecha_vencimiento_pago=fecha_vencimiento_pago,
            subtotal_lineas=subtotal,
            descuento_monto=descuento_monto,
            comision_porcentaje=comision_porcentaje,
            aplica_comision=aplica_comision,
            creado_por_id=creado_por_id,
            actualizado_por_id=creado_por_id,
        )
        pids_afectados: list[int] = []
        for prod, qty, pu, st in line_specs:
            VentaLinea.objects.create(
                venta=venta,
                producto=prod,
                cantidad=qty,
                precio_unitario=pu,
                subtotal=st,
            )
            Producto.objects.filter(pk=prod.pk).update(stock=F("stock") - qty)
            pids_afectados.append(prod.pk)

        Producto.deshabilitar_sin_stock(pids_afectados)

        extra_comprador = (
            f" Comprador: {venta.comprador}." if getattr(venta, "comprador_id", None) else ""
        )
        if venta.fecha_vencimiento_pago is not None:
            Evento.objects.create(
                fecha=venta.fecha_vencimiento_pago,
                titulo=f"Pago pendiente — Pedido #{venta.pk}",
                tipo=Evento.Tipo.PEDIDO,
                descripcion=(
                    f"Vendedor: {venta.vendedor}. "
                    f"Monto neto pedido: {format_monto_ars(venta.neto)}. "
                    + (
                        f"Comisión ({venta.comision_porcentaje}%): {format_monto_ars(venta.monto_comision)}. "
                        if venta.aplica_comision
                        else "Sin comisión al vendedor. "
                    )
                    + f"Ingreso en caja al cobrar: {format_monto_ars(venta.monto_ingreso_caja)}.{extra_comprador}"
                ),
            )
    return venta
