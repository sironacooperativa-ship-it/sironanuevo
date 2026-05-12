from django.db import models

from caja.models import MovimientoCaja


class Compra(models.Model):
    class Modo(models.TextChoices):
        PRODUCTOS = "PRO", "Productos (detalle)"
        FACTURA = "FAC", "Factura sin detalle"

    modo = models.CharField(
        max_length=3,
        choices=Modo.choices,
        default=Modo.PRODUCTOS,
        db_index=True,
        help_text="PRO: alta con producto y stock. FAC: factura / deuda sin detallar ítems ni egreso en caja.",
    )
    proveedor = models.ForeignKey(
        "personas.Proveedor", on_delete=models.PROTECT, related_name="compras"
    )
    producto = models.ForeignKey(
        "productos.Producto",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="compras_origen",
    )
    fecha_compra = models.DateField()
    fecha_vencimiento_pedido = models.DateField(null=True, blank=True)
    cantidad = models.PositiveIntegerField()
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    medio_pago = models.CharField(
        max_length=10, choices=MovimientoCaja.MedioPago.choices, default=MovimientoCaja.MedioPago.EFECTIVO
    )
    banco = models.CharField(max_length=100, blank=True, default="")
    numero_cheque = models.CharField(max_length=50, blank=True, default="")
    fecha_vencimiento_cheque = models.DateField(null=True, blank=True)
    movimiento_caja = models.OneToOneField(
        MovimientoCaja,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="compra_registro",
    )
    anulada = models.BooleanField(default=False, db_index=True)
    movimiento_credito = models.OneToOneField(
        MovimientoCaja,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="compra_nota_credito",
    )
    creado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="compras_creadas",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="compras_actualizadas",
    )

    class Meta:
        ordering = ["-creado_en", "-id"]

    def __str__(self) -> str:
        if self.producto_id:
            return f"Compra #{self.pk} — {self.producto.codigo}"
        return f"Compra #{self.pk} — Factura (sin detalle)"
