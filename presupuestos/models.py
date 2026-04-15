from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from core.money_decimal import q2 as _q2


class Presupuesto(models.Model):
    class Estado(models.TextChoices):
        ACTIVO = "ACT", "Pendiente de aprobar"
        APROBADO = "APR", "Aprobado (pedido generado)"

    vendedor = models.ForeignKey(
        "personas.Vendedor", on_delete=models.PROTECT, related_name="presupuestos"
    )
    comprador = models.ForeignKey(
        "personas.Comprador",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presupuestos",
    )
    estado = models.CharField(
        max_length=3, choices=Estado.choices, default=Estado.ACTIVO, db_index=True
    )
    fecha_vencimiento_pago = models.DateField(null=True, blank=True)
    subtotal_lineas = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    descuento_monto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    comision_porcentaje = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("4.00")
    )
    aplica_comision = models.BooleanField(
        default=True,
        help_text="Si aplica, al generar el pedido la comisión se discrimina y descuenta del ingreso en caja.",
    )
    creado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presupuestos_creados",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presupuestos_actualizados",
    )
    aprobado_en = models.DateTimeField(null=True, blank=True)
    aprobado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presupuestos_aprobados",
    )
    venta = models.OneToOneField(
        "ventas.Venta",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presupuesto_origen",
    )

    class Meta:
        ordering = ["-creado_en", "-id"]

    def __str__(self) -> str:
        return f"Presupuesto #{self.pk} — {self.vendedor}"

    @property
    def neto(self) -> Decimal:
        n = self.subtotal_lineas - self.descuento_monto
        return n if n > 0 else Decimal("0.00")

    @property
    def monto_comision(self) -> Decimal:
        if not self.aplica_comision:
            return Decimal("0.00")
        return _q2(self.neto * (self.comision_porcentaje / Decimal("100")))

    @property
    def monto_ingreso_caja(self) -> Decimal:
        return _q2(self.neto - self.monto_comision)

    def clean(self):
        super().clean()
        if self.descuento_monto is not None and self.descuento_monto < 0:
            raise ValidationError({"descuento_monto": "El descuento no puede ser negativo."})
        if self.comision_porcentaje is not None and self.comision_porcentaje < 0:
            raise ValidationError({"comision_porcentaje": "La comisión no puede ser negativa."})


class PresupuestoLinea(models.Model):
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name="lineas")
    producto = models.ForeignKey(
        "productos.Producto", on_delete=models.PROTECT, related_name="lineas_presupuesto"
    )
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.producto.codigo} x{self.cantidad}"
