import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction


class PersonaBase(models.Model):
    codigo = models.CharField(max_length=6, unique=True, db_index=True)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    dni = models.CharField(max_length=20, blank=True, default="")
    telefono = models.CharField(max_length=50, blank=True, default="")
    mail = models.EmailField(blank=True, default="")
    direccion = models.CharField(max_length=255, blank=True, default="")
    habilitado = models.BooleanField(default=True, db_index=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["apellido", "nombre", "codigo"]

    def __str__(self) -> str:
        return f"{self.codigo} - {self.apellido}, {self.nombre}"

    @classmethod
    def _prefijo_codigo(cls) -> str:
        raise NotImplementedError

    @classmethod
    def _siguiente_codigo(cls) -> str:
        prefijo = cls._prefijo_codigo()
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
                self.codigo = self._siguiente_codigo()
                while self.__class__.objects.filter(codigo=self.codigo).exists():
                    self.codigo = self._siguiente_codigo()
        super().save(*args, **kwargs)


class Vendedor(PersonaBase):
    comision_porcentaje = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00")
    )

    class Meta(PersonaBase.Meta):
        verbose_name = "Vendedor"
        verbose_name_plural = "Vendedores"

    @classmethod
    def _prefijo_codigo(cls) -> str:
        return "VE"

    def clean(self):
        super().clean()
        if self.comision_porcentaje is not None and self.comision_porcentaje < 0:
            raise ValidationError(
                {"comision_porcentaje": "La comisión no puede ser negativa."}
            )


class Proveedor(PersonaBase):
    class Meta(PersonaBase.Meta):
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"

    @classmethod
    def _prefijo_codigo(cls) -> str:
        return "PR"


class Comprador(PersonaBase):
    class Meta(PersonaBase.Meta):
        verbose_name = "Comprador"
        verbose_name_plural = "Compradores"

    @classmethod
    def _prefijo_codigo(cls) -> str:
        return "CO"

