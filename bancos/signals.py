from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from caja.models import MovimientoCaja

from .models import Gasto, MovimientoCuentaBancaria


def _debe_sincronizar(mov: MovimientoCaja) -> bool:
    return mov.medio_pago in (
        MovimientoCaja.MedioPago.TRANSFERENCIA,
        MovimientoCaja.MedioPago.MERCADOPAGO,
    ) and bool(mov.cuenta_bancaria_id)


@receiver(post_save, sender=MovimientoCaja)
def sincronizar_movimiento_caja_a_banco(sender, instance: MovimientoCaja, **kwargs):
    if kwargs.get("raw"):
        return
    MovimientoCuentaBancaria.objects.filter(movimiento_caja=instance).delete()
    if not _debe_sincronizar(instance):
        return
    MovimientoCuentaBancaria.objects.create(
        cuenta_id=instance.cuenta_bancaria_id,
        fecha=instance.fecha,
        monto=instance.monto,
        credito=(instance.tipo == MovimientoCaja.Tipo.INGRESO),
        origen=MovimientoCuentaBancaria.Origen.CAJA,
        concepto=(instance.operacion or "")[:255],
        movimiento_caja=instance,
    )


@receiver(post_delete, sender=MovimientoCaja)
def eliminar_movimiento_bancario_por_caja(sender, instance: MovimientoCaja, **kwargs):
    if kwargs.get("raw"):
        return
    MovimientoCuentaBancaria.objects.filter(movimiento_caja_id=instance.pk).delete()


@receiver(post_save, sender=Gasto)
def marcar_movimiento_como_gasto(sender, instance: Gasto, **kwargs):
    MovimientoCuentaBancaria.objects.filter(movimiento_caja=instance.movimiento_caja).update(
        origen=MovimientoCuentaBancaria.Origen.GASTO
    )
