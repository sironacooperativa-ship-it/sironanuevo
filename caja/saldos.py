from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import ArqueoCaja, MovimientoCaja


def actualizar_saldo_caja(*, saldo, usuario, observaciones=""):
    """El saldo real reemplaza el acumulado previo; no representa ingreso o gasto."""
    hoy = timezone.localdate()
    with transaction.atomic():
        movimiento = MovimientoCaja(
            fecha=hoy,
            operacion=f"Actualización de saldo al {hoy:%d/%m/%Y}",
            tipo=MovimientoCaja.Tipo.ARQUEO,
            medio_pago=MovimientoCaja.MedioPago.EFECTIVO,
            monto=saldo,
            es_arqueo=True,
            saldo_arqueo=saldo,
            creado_por=usuario,
        )
        movimiento.full_clean()
        movimiento.save()
        ArqueoCaja.objects.create(
            fecha=hoy, movimiento=movimiento, saldo_efectivo=saldo,
            saldo_transferencia=Decimal('0'), saldo_mercadopago=Decimal('0'),
            saldo_cheque=Decimal('0'), saldo_otro=Decimal('0'),
            observaciones=observaciones, creado_por=usuario,
        )
    return movimiento
