from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from personas.models import Vendedor


from core.papelera import CajaActivaManager


class MovimientoCaja(models.Model):
    objects = CajaActivaManager()
    all_objects = models.Manager()

    class Tipo(models.TextChoices):
        INGRESO = "IN", "Ingreso"
        EGRESO = "OUT", "Egreso"
        ARQUEO = "ARQ", "Arqueo"

    class MedioPago(models.TextChoices):
        EFECTIVO = "CASH", "Efectivo"
        TRANSFERENCIA = "TRF", "Transferencia"
        MERCADOPAGO = "MP", "MercadoPago"
        CHEQUE = "CHQ", "Cheque"
        OTRO = "OTH", "Otro"

    fecha = models.DateField()
    operacion = models.CharField(max_length=255)
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    monto = models.DecimalField(max_digits=14, decimal_places=2)

    medio_pago = models.CharField(max_length=10, choices=MedioPago.choices, default=MedioPago.EFECTIVO)

    # Transferencia / MP
    banco = models.CharField(max_length=100, blank=True, default="")

    # Cheque
    numero_cheque = models.CharField(max_length=50, blank=True, default="")
    fecha_vencimiento_cheque = models.DateField(null=True, blank=True)

    # Venta (para vincular vendedor cuando venga de una venta)
    vendedor = models.ForeignKey(Vendedor, null=True, blank=True, on_delete=models.SET_NULL)

    venta = models.ForeignKey(
        "ventas.Venta", null=True, blank=True, on_delete=models.SET_NULL, related_name="movimientos_caja"
    )

    cuenta_bancaria = models.ForeignKey(
        "bancos.CuentaBancaria",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="movimientos_caja",
    )

    creado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="movimientos_caja_creados",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="movimientos_caja_actualizados",
    )
    es_arqueo = models.BooleanField(default=False, db_index=True)
    saldo_arqueo = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["fecha", "id"]

    def clean(self):
        super().clean()
        es_corte = bool(self.es_arqueo) or self.tipo == self.Tipo.ARQUEO
        if self.monto is not None and self.monto < 0:
            raise ValidationError({"monto": "El monto no puede ser negativo."})
        if self.monto is not None and self.monto <= 0 and not es_corte:
            raise ValidationError({"monto": "El monto debe ser mayor a 0."})
        if es_corte:
            return

        if self.medio_pago in (self.MedioPago.TRANSFERENCIA, self.MedioPago.MERCADOPAGO):
            if not self.banco.strip():
                raise ValidationError({"banco": "Indicá el banco o si es MercadoPago."})
            if not self.cuenta_bancaria_id:
                raise ValidationError(
                    {"cuenta_bancaria": "Elegí la cuenta bancaria donde impacta el movimiento."}
                )

        if self.medio_pago == self.MedioPago.CHEQUE:
            if not self.numero_cheque.strip():
                raise ValidationError({"numero_cheque": "Indicá el número de cheque."})
            if not self.fecha_vencimiento_cheque:
                raise ValidationError({"fecha_vencimiento_cheque": "Indicá el vencimiento del cheque."})

    @property
    def delta(self) -> Decimal:
        if self.es_arqueo or self.tipo == self.Tipo.ARQUEO:
            return Decimal("0.00")
        return self.monto if self.tipo == self.Tipo.INGRESO else -self.monto


class ArqueoCaja(models.Model):
    """Cierre parcial: saldos declarados desde los que sigue el libro diario."""

    fecha = models.DateField()
    movimiento = models.OneToOneField(
        MovimientoCaja,
        on_delete=models.CASCADE,
        related_name="arqueo",
    )
    saldo_efectivo = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    saldo_transferencia = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    saldo_mercadopago = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    saldo_cheque = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    saldo_otro = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    observaciones = models.CharField(max_length=255, blank=True, default="")
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="arqueos_caja_creados",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Arqueo de caja"
        verbose_name_plural = "Arqueos de caja"

    @property
    def saldo_total(self) -> Decimal:
        return (
            self.saldo_efectivo
            + self.saldo_transferencia
            + self.saldo_mercadopago
            + self.saldo_cheque
            + self.saldo_otro
        )

