from django.contrib import admin

from .models import Venta, VentaLinea


class VentaLineaInline(admin.TabularInline):
    model = VentaLinea
    extra = 0


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
