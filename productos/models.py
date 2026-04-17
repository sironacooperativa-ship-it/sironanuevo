import re
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import models, transaction


class Producto(models.Model):
    class Tipo(models.TextChoices):
        MEDICAMENTOS = "MED", "Medicamentos"
        ACCESORIOS = "AC", "Accesorios"
        OTROS = "OT", "Otros"

    codigo = models.CharField(max_length=6, unique=True, db_index=True)
    descripcion = models.CharField(max_length=255)
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    costo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock = models.IntegerField(default=0)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    porcentaje_ganancia = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("30.00")
    )
    precio_venta = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    precio_venta_editado = models.BooleanField(default=False)
    habilitado = models.BooleanField(default=True)
    en_lista_precios = models.BooleanField(default=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-actualizado_en", "-id"]

    def __str__(self) -> str:
        return f"{self.codigo} - {self.descripcion}"

    @staticmethod
    def _redondear_2(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calcular_precio_venta(self) -> Decimal:
        costo = Decimal(self.costo or 0)
        pct = Decimal(self.porcentaje_ganancia or 0)
        return self._redondear_2(costo * (Decimal("1.0") + (pct / Decimal("100"))))

    def clean(self):
        super().clean()
        if self.costo is not None and self.costo < 0:
            raise ValidationError({"costo": "El costo no puede ser negativo."})
        if self.stock is not None and self.stock < 0:
            raise ValidationError({"stock": "El stock no puede ser negativo."})
        if self.porcentaje_ganancia is not None and self.porcentaje_ganancia < 0:
            raise ValidationError(
                {"porcentaje_ganancia": "El porcentaje no puede ser negativo."}
            )

    @classmethod
    def _prefijo_codigo(cls, tipo: str) -> str:
        if tipo == cls.Tipo.MEDICAMENTOS:
            return "ME"
        if tipo == cls.Tipo.ACCESORIOS:
            return "AC"
        return "OT"

    @classmethod
    def _siguiente_codigo(cls, tipo: str) -> str:
        prefijo = cls._prefijo_codigo(tipo)
        ult = (
            cls.objects.filter(codigo__startswith=prefijo)
            .order_by("-codigo")
            .values_list("codigo", flat=True)
            .first()
        )
        if not ult:
            return f"{prefijo}0001"
        m = re.match(rf"^{re.escape(prefijo)}(\d{{4}})$", ult)
        if not m:
            return f"{prefijo}0001"
        n = int(m.group(1)) + 1
        return f"{prefijo}{n:04d}"

    def save(self, *args, **kwargs):
        if not self.codigo:
            with transaction.atomic():
                self.codigo = self._siguiente_codigo(self.tipo)
                while Producto.objects.filter(codigo=self.codigo).exists():
                    self.codigo = self._siguiente_codigo(self.tipo)

        if not self.precio_venta_editado:
            self.precio_venta = self.calcular_precio_venta()

        if self.stock is not None and self.stock == 0:
            self.habilitado = False
            self.en_lista_precios = False
            uf = kwargs.get("update_fields")
            if uf is not None:
                kwargs["update_fields"] = sorted(set(uf) | {"habilitado", "en_lista_precios"})
        elif self.stock is not None and self.stock > 0:
            # Al pasar de sin stock a con stock, queda habilitado para venta (y en lista de precios).
            paso_a_positivo = False
            if self._state.adding:
                paso_a_positivo = True
            elif self.pk is not None:
                prev = (
                    type(self).objects.filter(pk=self.pk).values_list("stock", flat=True).first()
                )
                if prev is not None and prev <= 0:
                    paso_a_positivo = True
            if paso_a_positivo:
                self.habilitado = True
                self.en_lista_precios = True
                uf = kwargs.get("update_fields")
                if uf is not None:
                    kwargs["update_fields"] = sorted(set(uf) | {"habilitado", "en_lista_precios"})

        super().save(*args, **kwargs)

    @classmethod
    def deshabilitar_sin_stock(cls, producto_ids: list[int] | None = None) -> None:
        """Tras actualizar stock con F() u otro SQL, pone habilitado=False donde stock = 0."""
        qs = cls.objects.filter(stock=0)
        if producto_ids is not None:
            qs = qs.filter(pk__in=producto_ids)
        qs.update(habilitado=False, en_lista_precios=False)


class ListaPrecios(models.Model):
    nombre = models.CharField(max_length=100)
    productos = models.ManyToManyField(Producto, related_name="listas_precios")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en", "-id"]
        unique_together = [("nombre",)]

    def __str__(self) -> str:
        return self.nombre

