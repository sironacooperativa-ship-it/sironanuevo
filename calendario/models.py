from django.db import models


class Evento(models.Model):
    class Tipo(models.TextChoices):
        MANUAL = "MAN", "Manual"
        PEDIDO = "PED", "Pedido"
        COMPRA = "COM", "Compra"
        VENCIMIENTO = "VEN", "Vencimiento"
        COBRO = "COB", "Cobro"
        PAGO = "PAG", "Pago"
        ENTREGA = "ENT", "Entrega"

    fecha = models.DateField()
    hora = models.TimeField(null=True, blank=True)
    titulo = models.CharField(max_length=255)
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.MANUAL)
    descripcion = models.TextField(blank=True, default="")
    realizado = models.BooleanField(default=False, db_index=True)

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha", "id"]

    def __str__(self) -> str:
        return f"{self.fecha} - {self.titulo}"

