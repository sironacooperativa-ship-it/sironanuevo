from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.money_decimal import q2 as _q2


class ComisionLiquidacionPago(models.Model):
    """Pago de comisiones al vendedor (egreso de caja). Agrupa pedidos ya cobrados incluidos en esa liquidación."""

    vendedor = models.ForeignKey(
        "personas.Vendedor",
        on_delete=models.PROTECT,
        related_name="liquidaciones_comision_pago",
    )
    anio = models.PositiveIntegerField(null=True, blank=True)
    mes = models.PositiveSmallIntegerField(null=True, blank=True)
    fecha_liquidacion = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha en que se registró el pago al vendedor (egreso en caja).",
    )
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    movimiento_caja = models.OneToOneField(
        "caja.MovimientoCaja",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liquidacion_comision_pago",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liquidaciones_comision_creadas",
    )

    class Meta:
        ordering = ["-creado_en", "-id"]

    def __str__(self) -> str:
        if self.anio and self.mes:
            return f"Liq. com. {self.vendedor_id} {self.anio}-{self.mes:02d} ${self.total}"
        return f"Liq. com. #{self.pk} v{self.vendedor_id} ${self.total}"


class Venta(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PEN", "Pendiente de pago"
        PAGADA = "PAG", "Pagada"

    vendedor = models.ForeignKey(
        "personas.Vendedor", on_delete=models.PROTECT, related_name="ventas"
    )
    comprador = models.ForeignKey(
        "personas.Comprador",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ventas",
    )
    estado = models.CharField(
        max_length=3, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True
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
        help_text="Si aplica, la comisión se calcula sobre el neto y se liquida desde Comisiones al pagar al vendedor (egreso de caja).",
    )
    comision_descontada_en_pedido = models.BooleanField(
        default=False,
        help_text="Si aplica comisión y está activo, el ingreso en caja al cobrar es neto menos comisión.",
    )
    creado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ventas_creadas",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ventas_actualizadas",
    )
    pago_movimiento = models.OneToOneField(
        "caja.MovimientoCaja",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="venta_pago",
    )
    comision_liquidacion_pago = models.ForeignKey(
        ComisionLiquidacionPago,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ventas",
        help_text="Liquidación de comisión en la que se incluyó este pedido (si ya se pagó al vendedor).",
    )
    neto_cobro = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Neto del pedido al momento del cobro (congelado).",
    )
    costo_mercaderia_cobro = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Costo de mercadería (Σ cantidad × costo producto) al momento del cobro (congelado).",
    )
    ganancia_cobro = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Ganancia al cobrar: neto − costo de mercadería (congelada; no se recalcula si cambian costos).",
    )

    class Meta:
        ordering = ["-creado_en", "-id"]

    def __str__(self) -> str:
        return f"Pedido #{self.pk} — {self.vendedor}"

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
        """Importe en caja al cobrar: neto, o neto − comisión si está marcado «aplicar a pedido»."""
        neto = self.neto
        if self.aplica_comision and self.comision_descontada_en_pedido:
            return _q2(max(neto - self.monto_comision, Decimal("0.00")))
        return _q2(neto)

    def clean(self):
        super().clean()
        if self.descuento_monto is not None and self.descuento_monto < 0:
            raise ValidationError({"descuento_monto": "El descuento no puede ser negativo."})
        if self.envio is not None and self.envio < 0:
            raise ValidationError({"envio": "El envío no puede ser negativo."})
        if self.comision_porcentaje is not None and self.comision_porcentaje < 0:
            raise ValidationError({"comision_porcentaje": "La comisión no puede ser negativa."})


class VentaLinea(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="lineas")
    producto = models.ForeignKey(
        "productos.Producto", on_delete=models.PROTECT, related_name="lineas_venta"
    )
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    codigo_snapshot = models.CharField(
        max_length=6,
        blank=True,
        default="",
        help_text="Código tal como figuraba al confirmar el pedido (no cambia si editás el producto).",
    )
    descripcion_snapshot = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Descripción tal como figuraba al confirmar el pedido.",
    )

    class Meta:
        ordering = ["id"]

    @property
    def texto_codigo(self) -> str:
        return self.codigo_snapshot or self.producto.codigo

    @property
    def texto_descripcion(self) -> str:
        return self.descripcion_snapshot or self.producto.descripcion

    @property
    def texto_marca(self) -> str:
        return (getattr(self.producto, "laboratorio", None) or "").strip()

    def __str__(self) -> str:
        return f"{self.texto_codigo} x{self.cantidad}"
