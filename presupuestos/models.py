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
    envio = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    comision_porcentaje = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("5.00")
    )
    aplica_comision = models.BooleanField(
        default=False,
        help_text="Si aplica, al generar el pedido se discrimina la comisión (se liquida por mes desde Comisiones).",
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
        n = self.subtotal_lineas - self.descuento_monto + (self.envio or Decimal("0.00"))
        return n if n > 0 else Decimal("0.00")

    @property
    def monto_comision(self) -> Decimal:
        if not self.aplica_comision:
            return Decimal("0.00")
        return _q2(self.neto * (self.comision_porcentaje / Decimal("100")))

    @property
    def monto_ingreso_caja(self) -> Decimal:
        """Ingreso en caja al cobrar el pedido generado: igual al neto (comisión aparte)."""
        return _q2(self.neto)

    def clean(self):
        super().clean()
        if self.descuento_monto is not None and self.descuento_monto < 0:
            raise ValidationError({"descuento_monto": "El descuento no puede ser negativo."})
        if self.envio is not None and self.envio < 0:
            raise ValidationError({"envio": "El envío no puede ser negativo."})
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
    codigo_snapshot = models.CharField(
        max_length=6,
        blank=True,
        default="",
        help_text="Código al guardar la línea (no cambia si editás el producto después).",
    )
    descripcion_snapshot = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Descripción al guardar la línea.",
    )
    producto_capturado_en = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Valor de producto.actualizado_en al último guardado/aceptación de esta línea (para detectar cambios en catálogo).",
    )
    precio_catalogo_capturado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Precio de venta del producto al guardar/aceptar la línea.",
    )

    class Meta:
        ordering = ["id"]

    def linea_superada_por_catalogo_producto(self) -> bool:
        """La línea quedó desactualizada sólo si cambió el precio de venta del producto."""
        precio_actual = _q2(self.producto.precio_venta or Decimal("0.00"))
        if _q2(self.precio_unitario or Decimal("0.00")) == precio_actual:
            return False
        if self.precio_catalogo_capturado is None:
            return True
        return _q2(self.precio_catalogo_capturado) != precio_actual

    @property
    def texto_codigo(self) -> str:
        return self.codigo_snapshot or self.producto.codigo

    @property
    def texto_descripcion(self) -> str:
        return self.descripcion_snapshot or self.producto.descripcion

    def __str__(self) -> str:
        return f"{self.texto_codigo} x{self.cantidad}"


def presupuesto_tiene_alerta_catalogo(presupuesto: Presupuesto) -> bool:
    """Presupuesto activo con al menos una línea cuyo precio difiere del catálogo."""
    if presupuesto.estado != Presupuesto.Estado.ACTIVO:
        return False
    for ln in presupuesto.lineas.select_related("producto"):
        if ln.linea_superada_por_catalogo_producto():
            return True
    return False
