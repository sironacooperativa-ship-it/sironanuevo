from django.contrib import admin

from .models import Comprador, Proveedor, Vendedor


@admin.register(Vendedor)
class VendedorAdmin(admin.ModelAdmin):
    list_display = ("codigo", "apellido", "nombre", "dni", "telefono", "mail", "comision_porcentaje", "actualizado_en")
    search_fields = ("codigo", "apellido", "nombre", "dni", "mail")
    filter_horizontal = ("listas_precios_bloqueadas",)


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("codigo", "apellido", "nombre", "dni", "telefono", "mail", "actualizado_en")
    search_fields = ("codigo", "apellido", "nombre", "dni", "mail")


@admin.register(Comprador)
class CompradorAdmin(admin.ModelAdmin):
    list_display = ("codigo", "apellido", "nombre", "dni", "telefono", "mail", "actualizado_en")
    search_fields = ("codigo", "apellido", "nombre", "dni", "mail")

