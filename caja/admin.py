from django.contrib import admin

from .models import ArqueoCaja, MovimientoCaja


@admin.register(MovimientoCaja)
class MovimientoCajaAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "tipo",
        "operacion",
        "monto",
        "medio_pago",
        "vendedor",
        "es_arqueo",
        "fecha_vencimiento_cheque",
    )
    list_filter = ("tipo", "medio_pago", "es_arqueo", "fecha")
    search_fields = ("operacion", "banco", "numero_cheque")


@admin.register(ArqueoCaja)
class ArqueoCajaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "movimiento", "saldo_efectivo", "saldo_transferencia", "creado_en")
    list_filter = ("fecha",)

