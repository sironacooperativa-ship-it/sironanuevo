from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from personas.models import Vendedor


class MovimientoCaja(models.Model):
    class Tipo(models.TextChoices):
        INGRESO = "IN", "Ingreso"
        EGRESO = "OUT", "Egreso"

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

    class Meta:
        ordering = ["fecha", "id"]

    def clean(self):
        super().clean()
        if self.monto is not None and self.monto <= 0:
            raise ValidationError({"monto": "El monto debe ser mayor a 0."})

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
        return self.monto if self.tipo == self.Tipo.INGRESO else -self.monto

