from django.contrib import admin

from .models import ComisionLiquidacionPago, Venta, VentaLinea


class VentaLineaInline(admin.TabularInline):
    model = VentaLinea
    extra = 0


@admin.register(ComisionLiquidacionPago)
class ComisionLiquidacionPagoAdmin(admin.ModelAdmin):
    list_display = ("id", "vendedor", "anio", "mes", "total", "movimiento_caja_id", "creado_en")
    list_filter = ("anio", "mes")
    raw_id_fields = ("vendedor", "movimiento_caja", "creado_por")


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "vendedor",
        "comprador",
        "estado",
        "fecha_vencimiento_pago",
        "subtotal_lineas",
        "creado_en",
    )
    list_filter = ("estado",)
    inlines = [VentaLineaInline]
