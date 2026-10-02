from django.db import models


class ActivosManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(eliminado_en__isnull=True)


class CajaActivaManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            venta__eliminado_en__isnull=True,
            venta_pago__eliminado_en__isnull=True,
        )


class BancoActivoManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            movimiento_caja__venta__eliminado_en__isnull=True,
            movimiento_caja__venta_pago__eliminado_en__isnull=True,
        )
