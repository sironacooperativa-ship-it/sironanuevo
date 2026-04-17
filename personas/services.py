"""Operaciones administrativas sobre personas (vendedores, etc.)."""

from __future__ import annotations

from django.db import transaction

from caja.models import MovimientoCaja
from presupuestos.models import Presupuesto
from ventas.models import Venta
from ventas.servicios import eliminar_venta_admin

from .models import Vendedor


def resumen_historial_vendedor(v: Vendedor) -> dict:
    return {
        "n_ventas": v.ventas.count(),
        "n_presupuestos": v.presupuestos.count(),
        "n_movimientos_caja": MovimientoCaja.objects.filter(vendedor=v).count(),
    }


def eliminar_vendedor_y_historial_admin(v: Vendedor) -> str:
    """
    Elimina el vendedor y todo lo asociado: pedidos (revirtiendo stock/caja/calendario),
    presupuestos y movimientos de caja vinculados al vendedor.
    """
    codigo = v.codigo
    pk = v.pk
    with transaction.atomic():
        v_lock = Vendedor.objects.select_for_update().get(pk=pk)
        venta_pks = list(Venta.objects.filter(vendedor=v_lock).values_list("pk", flat=True))
        for vid in venta_pks:
            eliminar_venta_admin(Venta.objects.get(pk=vid))
        Presupuesto.objects.filter(vendedor_id=pk).delete()
        MovimientoCaja.objects.filter(vendedor_id=pk).delete()
        v_lock.delete()
    return codigo
