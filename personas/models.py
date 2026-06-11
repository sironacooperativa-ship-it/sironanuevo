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
    class Acceso(models.TextChoices):
        AMBOS = "BOTH", "Completo y vendedor"
        SOLO_VENDEDOR = "VEND", "Solo vendedor (reducido)"
        SOLO_COMPLETO = "FULL", "Solo completo"

    usuario = models.OneToOneField(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendedor_perfil",
    )
    acceso = models.CharField(
        max_length=4,
        choices=Acceso.choices,
        default=Acceso.AMBOS,
        db_index=True,
    )
    comision_porcentaje = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00")
    )
    aplica_comision_por_defecto = models.BooleanField(
        default=True,
        verbose_name="Aplicar comisión por defecto",
        help_text="Si está activo, al armar presupuestos o ventas con este vendedor la opción «Aplicar comisión» viene marcada.",
    )
    es_jefe_grupo = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Vendedor a cargo de grupo",
    )
    comision_grupo_porcentaje = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Comisión por ventas del grupo (%)",
    )
    vendedores_a_cargo = models.ManyToManyField(
        "self",
        blank=True,
        symmetrical=False,
        related_name="jefes_de_grupo",
        verbose_name="Vendedores a cargo",
    )
    listas_precios_bloqueadas = models.ManyToManyField(
        "productos.ListaPrecios",
        blank=True,
        related_name="vendedores_bloqueados",
        help_text="Listas que este vendedor NO puede ver/descargar en el portal vendedor.",
    )

    class Meta(PersonaBase.Meta):
        verbose_name = "Vendedor"
        verbose_name_plural = "Vendedores"

    @classmethod
    def _prefijo_codigo(cls) -> str:
        return "VE"

    @classmethod
    def aplica_comision_por_defecto_para(cls, vendedor_id: int | None) -> bool:
        if not vendedor_id:
            return True
        val = cls.objects.filter(pk=vendedor_id).values_list("aplica_comision_por_defecto", flat=True).first()
        return True if val is None else bool(val)

    def clean(self):
        super().clean()
        if self.comision_porcentaje is not None and self.comision_porcentaje < 0:
            raise ValidationError(
                {"comision_porcentaje": "La comisión no puede ser negativa."}
            )
        if self.comision_grupo_porcentaje is not None and self.comision_grupo_porcentaje < 0:
            raise ValidationError(
                {"comision_grupo_porcentaje": "La comisión de grupo no puede ser negativa."}
            )


class Proveedor(PersonaBase):
    class Meta(PersonaBase.Meta):
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"

    @classmethod
    def _prefijo_codigo(cls) -> str:
        return "PR"


class Comprador(PersonaBase):
    vendedor_asignado = models.ForeignKey(
        Vendedor,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clientes_asignados",
    )

    class Meta(PersonaBase.Meta):
        verbose_name = "Comprador"
        verbose_name_plural = "Compradores"

    @classmethod
    def _prefijo_codigo(cls) -> str:
        return "CO"

