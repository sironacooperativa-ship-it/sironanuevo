from django.contrib import admin

from .models import Presupuesto, PresupuestoLinea


class PresupuestoLineaInline(admin.TabularInline):
    model = PresupuestoLinea
    extra = 0


@admin.register(Presupuesto)
class PresupuestoAdmin(admin.ModelAdmin):
    list_display = ("id", "vendedor", "comprador", "estado", "fecha_vencimiento_pago", "subtotal_lineas", "venta_id")
    list_filter = ("estado",)
    inlines = [PresupuestoLineaInline]
