from django.contrib import admin

from .models import Producto


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "descripcion",
        "tipo",
        "costo",
        "stock",
        "porcentaje_ganancia",
        "precio_venta",
        "habilitado",
        "en_lista_precios",
        "actualizado_en",
    )
    list_filter = ("tipo", "habilitado", "en_lista_precios")
    search_fields = ("codigo", "descripcion")

