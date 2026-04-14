from django.contrib import admin

from .models import Compra


@admin.register(Compra)
class CompraAdmin(admin.ModelAdmin):
    list_display = ("id", "producto", "proveedor", "fecha_compra", "monto", "creado_en")
    list_filter = ("fecha_compra",)
