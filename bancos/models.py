from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from collections import defaultdict


class CuentaBancaria(models.Model):
    banco = models.CharField(max_length=120)
    cuenta = models.CharField(
        max_length=120,
        help_text="Número de cuenta, CBU, alias u otro identificador.",
    )
    saldo_inicial = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    activa = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["banco", "cuenta"]
        verbose_name = "Cuenta bancaria"
        verbose_name_plural = "Cuentas bancarias"

    def __str__(self) -> str:
        return f"{self.banco} — {self.cuenta}"

    @classmethod
    def con_saldo_actual(cls):
        cuentas = list(cls.objects.filter(activa=True))
        if not cuentas:
            return cuentas
        ids = [c.pk for c in cuentas]
        acc = defaultdict(lambda: Decimal("0"))
        for m in MovimientoCuentaBancaria.objects.filter(cuenta_id__in=ids).iterator():
            acc[m.cuenta_id] += m.monto if m.credito else -m.monto
        for c in cuentas:
            c.saldo_actual = c.saldo_inicial + acc[c.pk]
        return cuentas


class MovimientoCuentaBancaria(models.Model):
    class Origen(models.TextChoices):
        CAJA = "CAJ", "Caja (transferencia / MP)"
        GASTO = "GAS", "Gasto"
        AJUSTE = "AJU", "Ajuste manual"

    cuenta = models.ForeignKey(
        CuentaBancaria, on_delete=models.CASCADE, related_name="movimientos"
    )
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    credito = models.BooleanField(
        help_text="Verdadero: ingreso a la cuenta. Falso: egreso."
    )
    origen = models.CharField(max_length=3, choices=Origen.choices)
    concepto = models.CharField(max_length=255)
    movimiento_caja = models.OneToOneField(
        "caja.MovimientoCaja",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="movimiento_bancario",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Movimiento de cuenta"
        verbose_name_plural = "Movimientos de cuenta"

    def clean(self):
        super().clean()
        if self.monto is not None and self.monto <= 0:
            raise ValidationError({"monto": "El monto debe ser mayor a cero."})


class Gasto(models.Model):
    fecha = models.DateField()
    descripcion = models.CharField(max_length=255)
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    cuenta_bancaria = models.ForeignKey(
        CuentaBancaria, on_delete=models.PROTECT, related_name="gastos"
    )
    movimiento_caja = models.OneToOneField(
        "caja.MovimientoCaja",
        on_delete=models.CASCADE,
        related_name="gasto_origen",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self) -> str:
        return f"{self.fecha} — {self.descripcion[:40]}"
