from django.conf import settings
from django.db import models

from productos.models import Producto


class MovimientoStock(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = "IN", "Entrada"
        SALIDA = "OUT", "Salida"

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="movimientos_stock")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    cantidad = models.IntegerField()

    # Entrada
    numero_boleta = models.CharField(max_length=50, blank=True, default="")
    proveedor = models.CharField(max_length=255, blank=True, default="")

    # Salida
    numero_factura = models.CharField(max_length=50, blank=True, default="")
    destinatario = models.CharField(max_length=255, blank=True, default="")

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en", "-id"]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} {self.producto.codigo} x{self.cantidad}"

