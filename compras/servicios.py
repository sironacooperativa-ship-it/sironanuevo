from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from calendario.models import Evento
from caja.models import MovimientoCaja

from .models import Compra


def _borrar_eventos_compra(compra: Compra) -> None:
    Evento.objects.filter(
        tipo=Evento.Tipo.COMPRA,
        descripcion__contains=f"Pedido/compra #{compra.pk}.",
    ).delete()


def compra_anular_por_admin(compra: Compra, user: AbstractUser) -> None:
    """Marca la compra como anulada y, si hubo egreso en caja, registra ingreso (nota de crédito)."""
    with transaction.atomic():
        locked = Compra.objects.select_for_update().select_related("movimiento_caja").get(pk=compra.pk)
        if locked.anulada:
            raise ValidationError("La compra ya está anulada.")

        if not locked.movimiento_caja_id:
            locked.anulada = True
            locked.actualizado_por = user
            locked.save(update_fields=["anulada", "actualizado_por", "actualizado_en"])
            _borrar_eventos_compra(locked)
            return

        orig = locked.movimiento_caja
        nc = MovimientoCaja(
            fecha=timezone.localdate(),
            operacion=(
                f"Nota de crédito — Compra #{locked.pk} ({locked.proveedor}) — "
                f"factura / registro anulado"
            ),
            tipo=MovimientoCaja.Tipo.INGRESO,
            monto=locked.monto,
            medio_pago=orig.medio_pago,
            banco=orig.banco,
            numero_cheque=orig.numero_cheque,
            fecha_vencimiento_cheque=orig.fecha_vencimiento_cheque,
            cuenta_bancaria_id=orig.cuenta_bancaria_id,
            creado_por=user,
            actualizado_por=user,
        )
        nc.full_clean()
        nc.save()
        locked.anulada = True
        locked.movimiento_credito = nc
        locked.actualizado_por = user
        locked.save(update_fields=["anulada", "movimiento_credito", "actualizado_por", "actualizado_en"])


def compra_eliminar_por_admin(compra: Compra, _user: AbstractUser) -> None:
    """
    Elimina la compra y sus movimientos de caja asociados (egreso y, si existía, nota de crédito).
    Descuenta la cantidad del stock del producto cuando la compra llevaba detalle de producto.
    """
    with transaction.atomic():
        locked = Compra.objects.select_for_update().select_related("producto").get(pk=compra.pk)
        producto = locked.producto
        cant = locked.cantidad

        if producto is not None:
            if producto.stock < cant:
                raise ValidationError(
                    "No se puede eliminar: el stock actual es menor que la cantidad de la compra "
                    "(probablemente ya se vendió parte del lote)."
                )

        _borrar_eventos_compra(locked)

        if locked.movimiento_credito_id:
            nc_id = locked.movimiento_credito_id
            Compra.objects.filter(pk=locked.pk).update(movimiento_credito_id=None)
            MovimientoCaja.objects.filter(pk=nc_id).delete()

        if locked.movimiento_caja_id:
            eg_id = locked.movimiento_caja_id
            Compra.objects.filter(pk=locked.pk).update(movimiento_caja_id=None)
            MovimientoCaja.objects.filter(pk=eg_id).delete()

        if producto is not None:
            producto.stock -= cant
            producto.actualizado_en = timezone.now()
            producto.save(update_fields=["stock", "actualizado_en"])

        locked.delete()
