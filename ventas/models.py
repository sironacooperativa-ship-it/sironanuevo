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
    despacho_armado = models.BooleanField(
        default=False,
        help_text="Pedido preparado / armado para entrega.",
    )
    despacho_despachado = models.BooleanField(
        default=False,
        help_text="Pedido entregado o despachado al cliente.",
    )
    despacho_despachado_en = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Momento en que se marcó como despachado (para archivar al historial).",
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

    @property
    def despacho_estado(self) -> str:
        """no_armado | armado | despachado — para iconos y badges."""
        if self.despacho_despachado:
            return "despachado"
        if self.despacho_armado:
            return "armado"
        return "no_armado"

    @property
    def despacho_estado_label(self) -> str:
        if self.despacho_despachado:
            return "Pedido despachado"
        if self.despacho_armado:
            return "Pedido armado"
        return "No armado"

    def aplicar_estado_despacho(self, *, armado: bool, despachado: bool) -> None:
        from django.utils import timezone as tz

        if despachado:
            armado = True
        elif not armado:
            despachado = False
        era_despachado = bool(self.despacho_despachado)
        self.despacho_armado = armado
        self.despacho_despachado = despachado
        if despachado and not era_despachado:
            self.despacho_despachado_en = tz.now()
        elif not despachado:
            self.despacho_despachado_en = None

    @classmethod
    def parse_estado_despacho_clave(cls, clave: str) -> tuple[bool, bool] | None:
        clave = (clave or "").strip()
        if clave == "no_armado":
            return False, False
        if clave == "armado":
            return True, False
        if clave == "despachado":
            return True, True
        return None

    def set_estado_despacho_clave(self, clave: str) -> bool:
        parsed = self.parse_estado_despacho_clave(clave)
        if parsed is None:
            return False
        armado, despachado = parsed
        self.aplicar_estado_despacho(armado=armado, despachado=despachado)
        return True

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


class PuntoStockArmado(models.Model):
    """Depósito o punto de retiro para armado colectivo de pedidos."""

    nombre = models.CharField(max_length=80, unique=True)
    orden = models.PositiveIntegerField(default=0)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["orden", "nombre", "id"]
        verbose_name = "Punto de stock (armado)"
        verbose_name_plural = "Puntos de stock (armado)"

    def __str__(self) -> str:
        return self.nombre


class ArmadoColectivoGuardado(models.Model):
    """Configuración guardada de un armado colectivo (pedidos + asignación por punto de stock)."""

    nombre = models.CharField(max_length=500)
    ventas = models.ManyToManyField(Venta, related_name="armados_colectivos_guardados")
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="armados_colectivos_guardados",
    )
    requiere_revision = models.BooleanField(
        default=False,
        help_text="True si cambió la composición del armado (p. ej. se eliminó un pedido del historial).",
    )
    nota_revision = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-creado_en", "-id"]

    def __str__(self) -> str:
        return self.nombre


class ArmadoColectivoLineaGuardada(models.Model):
    armado = models.ForeignKey(
        ArmadoColectivoGuardado,
        on_delete=models.CASCADE,
        related_name="lineas",
    )
    producto = models.ForeignKey(
        "productos.Producto",
        on_delete=models.PROTECT,
        related_name="lineas_armado_colectivo",
    )
    codigo = models.CharField(max_length=32)
    descripcion = models.CharField(max_length=255)
    cantidad_total = models.PositiveIntegerField()
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    precio_venta = models.DecimalField(max_digits=12, decimal_places=2)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["orden", "id"]

    def __str__(self) -> str:
        return f"{self.codigo} x{self.cantidad_total}"


class ArmadoColectivoAsignacion(models.Model):
    linea = models.ForeignKey(
        ArmadoColectivoLineaGuardada,
        on_delete=models.CASCADE,
        related_name="asignaciones",
    )
    punto = models.ForeignKey(
        PuntoStockArmado,
        on_delete=models.PROTECT,
        related_name="asignaciones_armado",
    )
    cantidad = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["linea", "punto"],
                name="ventas_armado_asignacion_linea_punto_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.punto.nombre}: {self.cantidad}"

