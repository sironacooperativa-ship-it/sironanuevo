from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum


class Negocio(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Negocio"
        verbose_name_plural = "Negocios"
        permissions = [
            ("access_cuentas_compartidas", "Puede acceder a Gastos compartidos"),
        ]

    def __str__(self) -> str:
        return self.nombre


class OperacionCompartida(models.Model):
    class Tipo(models.TextChoices):
        COMPRA = "COMPRA", "Compra"
        DINERO = "DINERO", "Dinero"
        MERCADERIA = "MERCADERIA", "Mercadería"

    fecha = models.DateField()
    concepto = models.CharField(max_length=255)
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.COMPRA)
    pagador = models.ForeignKey(Negocio, on_delete=models.PROTECT, related_name="operaciones_pagadas")
    monto_total = models.DecimalField(max_digits=14, decimal_places=2)
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="gastos_compartidos_creados",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Operación compartida"
        verbose_name_plural = "Operaciones compartidas"

    def __str__(self) -> str:
        return f"{self.fecha} — {self.concepto}"

    def clean(self):
        super().clean()
        if self.monto_total is not None and self.monto_total <= 0:
            raise ValidationError({"monto_total": "El monto total debe ser mayor a cero."})

    @property
    def monto_asignado(self) -> Decimal:
        return self.deudas.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")


class DeudaCompartida(models.Model):
    operacion = models.ForeignKey(OperacionCompartida, on_delete=models.CASCADE, related_name="deudas")
    deudor = models.ForeignKey(Negocio, on_delete=models.PROTECT, related_name="deudas_compartidas")
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    vencimiento = models.DateField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["vencimiento", "id"]
        verbose_name = "Deuda compartida"
        verbose_name_plural = "Deudas compartidas"
        constraints = [
            models.UniqueConstraint(fields=["operacion", "deudor"], name="uniq_deuda_por_operacion_deudor"),
        ]

    def __str__(self) -> str:
        return f"{self.deudor} debe {self.monto} a {self.operacion.pagador}"

    def clean(self):
        super().clean()
        if self.monto is not None and self.monto <= 0:
            raise ValidationError({"monto": "El monto debe ser mayor a cero."})
        if self.operacion_id and self.deudor_id == self.operacion.pagador_id:
            raise ValidationError({"deudor": "El pagador no puede deberse a sí mismo en la misma operación."})

    @property
    def pagado(self) -> Decimal:
        if not self.pk:
            return Decimal("0.00")
        return self.cancelaciones.aggregate(total=Sum("monto"))["total"] or Decimal("0.00")

    @property
    def pendiente(self) -> Decimal:
        saldo = self.monto - self.pagado
        return max(saldo, Decimal("0.00"))

    @property
    def esta_pagada(self) -> bool:
        return self.pendiente <= 0


class CancelacionDeuda(models.Model):
    class Medio(models.TextChoices):
        DINERO = "DINERO", "Dinero"
        COMPRA = "COMPRA", "Compra"
        MERCADERIA = "MERCADERIA", "Mercadería"

    deuda = models.ForeignKey(DeudaCompartida, on_delete=models.CASCADE, related_name="cancelaciones")
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    medio = models.CharField(max_length=12, choices=Medio.choices, default=Medio.DINERO)
    detalle = models.CharField(max_length=255, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Cancelación de deuda"
        verbose_name_plural = "Cancelaciones de deuda"

    def clean(self):
        super().clean()
        if self.monto is not None and self.monto <= 0:
            raise ValidationError({"monto": "El monto debe ser mayor a cero."})
        if self.deuda_id:
            pendiente = self.deuda.pendiente
            if self.pk:
                anterior = CancelacionDeuda.objects.filter(pk=self.pk).values_list("monto", flat=True).first()
                if anterior:
                    pendiente += anterior
            if self.monto and self.monto > pendiente:
                raise ValidationError({"monto": "La cancelación no puede superar el saldo pendiente."})


class MovimientoCCMarcacion(models.Model):
    """Oculta un movimiento de la vista de pendientes en cuenta corriente (archivado)."""

    class MovTipo(models.TextChoices):
        OPERACION = "operacion", "Operación"
        CANCELACION = "cancelacion", "Cancelación"

    mov_tipo = models.CharField(max_length=12, choices=MovTipo.choices)
    objeto_id = models.PositiveIntegerField()
    marcado = models.BooleanField(default=True, db_index=True)
    marcado_en = models.DateTimeField(auto_now=True)
    marcado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cc_marcaciones",
    )

    class Meta:
        verbose_name = "Marcación cuenta corriente"
        verbose_name_plural = "Marcaciones cuenta corriente"
        constraints = [
            models.UniqueConstraint(
                fields=["mov_tipo", "objeto_id"],
                name="uniq_cc_marcacion_mov",
            ),
        ]

    def __str__(self) -> str:
        estado = "archivado" if self.marcado else "pendiente"
        return f"{self.mov_tipo} #{self.objeto_id} ({estado})"
