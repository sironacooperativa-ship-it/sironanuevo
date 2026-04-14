from django.contrib import admin

from .models import MovimientoCaja


@admin.register(MovimientoCaja)
class MovimientoCajaAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "tipo",
        "operacion",
        "monto",
        "medio_pago",
        "vendedor",
        "fecha_vencimiento_cheque",
    )
    list_filter = ("tipo", "medio_pago", "fecha")
    search_fields = ("operacion", "banco", "numero_cheque")

