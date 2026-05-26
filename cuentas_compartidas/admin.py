from django.contrib import admin

from .models import CancelacionDeuda, DeudaCompartida, Negocio, OperacionCompartida


class DeudaInline(admin.TabularInline):
    model = DeudaCompartida
    extra = 0


@admin.register(Negocio)
class NegocioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo", "creado_en")
    list_filter = ("activo",)
    search_fields = ("nombre",)


@admin.register(OperacionCompartida)
class OperacionCompartidaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "concepto", "tipo", "pagador", "monto_total")
    list_filter = ("tipo", "pagador")
    search_fields = ("concepto", "observaciones")
    inlines = [DeudaInline]


@admin.register(DeudaCompartida)
class DeudaCompartidaAdmin(admin.ModelAdmin):
    list_display = ("operacion", "deudor", "monto", "vencimiento")
    list_filter = ("vencimiento", "deudor")


@admin.register(CancelacionDeuda)
class CancelacionDeudaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "deuda", "monto", "medio")
    list_filter = ("medio", "fecha")
