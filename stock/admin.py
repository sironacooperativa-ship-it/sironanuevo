from django.contrib import admin

from .models import MovimientoStock


@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = (
        "creado_en",
        "tipo",
        "producto",
        "cantidad",
        "numero_boleta",
        "proveedor",
        "numero_factura",
        "destinatario",
        "usuario",
    )
    list_filter = ("tipo", "creado_en")
    search_fields = (
        "producto__codigo",
        "producto__descripcion",
        "numero_boleta",
        "proveedor",
        "numero_factura",
        "destinatario",
    )

