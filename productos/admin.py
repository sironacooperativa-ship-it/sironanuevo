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
        "oferta",
        "habilitado",
        "en_lista_precios",
        "precio_actualizado_en",
        "actualizado_en",
    )
    list_filter = ("tipo", "habilitado", "en_lista_precios", "oferta")
    search_fields = ("codigo", "descripcion")

