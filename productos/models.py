import re
from collections.abc import Iterable
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils.text import slugify

from core.money_decimal import redondear_precio_mostrador_ars


class Producto(models.Model):
    class Tipo(models.TextChoices):
        MEDICAMENTOS = "MED", "Medicamentos"
        ACCESORIOS = "AC", "Accesorios"
        OTROS = "OT", "Otros"

    codigo = models.CharField(max_length=6, unique=True, db_index=True)
    descripcion = models.CharField(max_length=255)
    laboratorio = models.CharField(max_length=120, blank=True, db_index=True)
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
    en_lista_precios = models.BooleanField(default=False)
    deshabilitado_por_stock = models.BooleanField(default=False, db_index=True)
    listas_stock_snapshot = models.JSONField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-actualizado_en", "-id"]

    def __str__(self) -> str:
        return f"{self.codigo} - {self.descripcion}"

    def calcular_precio_venta(self) -> Decimal:
        costo = Decimal(self.costo or 0)
        pct = Decimal(self.porcentaje_ganancia or 0)
        raw = costo * (Decimal("1.0") + (pct / Decimal("100")))
        return redondear_precio_mostrador_ars(raw)

    @property
    def porcentaje_ganancia_calculado(self) -> Decimal | None:
        """
        % de ganancia implícito según costo y precio_venta actuales.
        Útil para ver el margen real cuando hay redondeos del precio.
        """
        costo = Decimal(self.costo or 0)
        if costo <= 0:
            return None
        precio = Decimal(self.precio_venta or 0)
        pct = (precio - costo) * (Decimal("100.0") / costo)
        return pct.quantize(Decimal("0.01"))

    def clean(self):
        super().clean()
        if self.costo is not None and self.costo < 0:
            raise ValidationError({"costo": "El costo no puede ser negativo."})
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

    def _snapshot_listas_stock_actual(self) -> dict:
        """Estado de listas antes de apagar por stock (Farmacia + rubros)."""
        if not self.pk:
            return {"en_lista_precios": bool(self.en_lista_precios), "lista_rubro_ids": []}
        ListaPrecioItem = apps.get_model("productos", "ListaPrecioItem")
        ids = list(
            ListaPrecioItem.objects.filter(producto_id=self.pk)
            .exclude(lista__es_farmacia=True)
            .values_list("lista_id", flat=True)
            .distinct()
        )
        return {"en_lista_precios": bool(self.en_lista_precios), "lista_rubro_ids": ids}

    def _restaurar_listas_desde_snapshot(self) -> None:
        """Vuelve a poner el producto en las mismas listas que tenía antes del apagado por stock."""
        snap = self.listas_stock_snapshot
        if not snap:
            return
        ListaPrecioItem = apps.get_model("productos", "ListaPrecioItem")
        ListaPrecios = apps.get_model("productos", "ListaPrecios")
        self.en_lista_precios = bool(snap.get("en_lista_precios"))
        for lid in snap.get("lista_rubro_ids") or []:
            if not ListaPrecios.objects.filter(pk=lid, es_farmacia=False).exists():
                continue
            ListaPrecioItem.objects.update_or_create(
                lista_id=lid,
                producto_id=self.pk,
                defaults={"precio_venta": self.precio_venta},
            )
        self.listas_stock_snapshot = None
        self.deshabilitado_por_stock = False

    def save(self, *args, **kwargs):
        if not self.codigo:
            with transaction.atomic():
                self.codigo = self._siguiente_codigo(self.tipo)
                while Producto.objects.filter(codigo=self.codigo).exists():
                    self.codigo = self._siguiente_codigo(self.tipo)

        if not self.precio_venta_editado:
            self.precio_venta = self.calcular_precio_venta()

        # Ya no se deshabilita solo al quedar en stock 0: el usuario elige (vigente o deshabilitar).
        if self.stock is not None and self.stock < 0:
            # Stock negativo (p. ej. mercadería externa): no forzar habilitado/listas desde acá.
            pass
        elif self.stock is not None and self.stock > 0:
            # Al pasar de sin stock a con stock, queda habilitado para venta (lista Farmacia/PDF es aparte).
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
                uf = kwargs.get("update_fields")
                if uf is not None:
                    kwargs["update_fields"] = sorted(set(uf) | {"habilitado"})

        if self.habilitado and self.listas_stock_snapshot:
            self._restaurar_listas_desde_snapshot()
            uf = kwargs.get("update_fields")
            if uf is not None:
                kwargs["update_fields"] = sorted(
                    set(uf)
                    | {
                        "en_lista_precios",
                        "listas_stock_snapshot",
                        "deshabilitado_por_stock",
                    }
                )

        super().save(*args, **kwargs)

    @classmethod
    def deshabilitar_manual(cls, producto_ids: Iterable[int]) -> None:
        """Igual que desactivar el interruptor «Producto habilitado» en la ficha."""
        seen: list[int] = []
        for x in producto_ids:
            try:
                ix = int(x)
            except (TypeError, ValueError):
                continue
            if ix not in seen:
                seen.append(ix)
        if not seen:
            return
        cls.objects.filter(pk__in=seen).update(
            habilitado=False,
            en_lista_precios=False,
            deshabilitado_por_stock=False,
            listas_stock_snapshot=None,
        )

    @classmethod
    def registrar_deshabilitacion_por_stock(cls, producto_ids: Iterable[int]) -> None:
        """Legacy: conserva snapshot de listas (rehabilitación automática al reponer stock)."""
        ListaPrecioItem = apps.get_model("productos", "ListaPrecioItem")
        seen: list[int] = []
        for x in producto_ids:
            try:
                ix = int(x)
            except (TypeError, ValueError):
                continue
            if ix not in seen:
                seen.append(ix)
        for pk in seen:
            with transaction.atomic():
                row = (
                    cls.objects.select_for_update()
                    .filter(pk=pk, stock=0, habilitado=True)
                    .values("pk", "en_lista_precios")
                    .first()
                )
                if row is None:
                    continue
                ids = list(
                    ListaPrecioItem.objects.filter(producto_id=pk)
                    .exclude(lista__es_farmacia=True)
                    .values_list("lista_id", flat=True)
                    .distinct()
                )
                snap = {"en_lista_precios": bool(row["en_lista_precios"]), "lista_rubro_ids": ids}
                cls.objects.filter(pk=pk).update(
                    habilitado=False,
                    en_lista_precios=False,
                    deshabilitado_por_stock=True,
                    listas_stock_snapshot=snap,
                )

    @classmethod
    def aplicar_deshabilitado_si_queda_en_cero(
        cls, opciones_por_producto: dict[int, tuple[bool, bool]]
    ) -> None:
        """
        Tras descontar stock con F(), aplica la decisión del usuario por producto.
        opciones_por_producto: producto_id -> (permitir_negativo, deshabilitar_si_queda_en_cero).
        """
        ids_desh: list[int] = []
        for pid, (_neg, desh) in opciones_por_producto.items():
            if desh:
                ids_desh.append(int(pid))
        if not ids_desh:
            return
        en_cero = list(
            cls.objects.filter(pk__in=ids_desh, stock__lte=0).values_list("pk", flat=True)
        )
        cls.deshabilitar_manual(en_cero)

    @classmethod
    def deshabilitar_sin_stock(cls, producto_ids: list[int] | None = None) -> None:
        """Deprecated: no usar en flujos nuevos; preferir deshabilitar_manual desde la UI."""
        qs = cls.objects.filter(stock__lte=0, habilitado=True)
        if producto_ids is not None:
            qs = qs.filter(pk__in=producto_ids)
        cls.deshabilitar_manual(list(qs.values_list("pk", flat=True)))


class ListaPrecios(models.Model):
    """Rubro / canal de venta. La lista marcada como Farmacia usa los precios del modelo Producto."""

    nombre = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, blank=True, default="", db_index=True)
    es_farmacia = models.BooleanField(default=False, db_index=True)
    productos = models.ManyToManyField(
        Producto,
        through="ListaPrecioItem",
        related_name="listas_precios",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-es_farmacia", "-creado_en", "-id"]
        unique_together = [("nombre",)]

    def __str__(self) -> str:
        return self.nombre

    def save(self, *args, **kwargs):
        if not (self.slug or "").strip():
            base = slugify(self.nombre)[:120] or "lista"
            slug = base
            n = 1
            qs = ListaPrecios.objects.filter(slug=slug)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            while qs.exists():
                slug = f"{base}-{n}"
                n += 1
                qs = ListaPrecios.objects.filter(slug=slug)
                if self.pk:
                    qs = qs.exclude(pk=self.pk)
            self.slug = slug
        super().save(*args, **kwargs)

    def precio_para(self, producto: Producto) -> Decimal | None:
        """Precio de venta en esta lista (Farmacia = `Producto.precio_venta`)."""
        if self.es_farmacia:
            return producto.precio_venta
        item = self.items.filter(producto_id=producto.pk).first()
        return item.precio_venta if item else None


class ListaPrecioItem(models.Model):
    """Precio por rubro distinto de Farmacia. La lista Farmacia no usa filas (precio en Producto)."""

    lista = models.ForeignKey(ListaPrecios, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="items_lista_precio")
    precio_venta = models.DecimalField(max_digits=12, decimal_places=2)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["producto__descripcion", "producto__codigo"]
        unique_together = [("lista", "producto")]

    def __str__(self) -> str:
        return f"{self.lista} · {self.producto.codigo}"

