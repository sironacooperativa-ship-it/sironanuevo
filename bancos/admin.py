from django.contrib import admin

from .models import CuentaBancaria, Gasto, MovimientoCuentaBancaria


@admin.register(CuentaBancaria)
class CuentaBancariaAdmin(admin.ModelAdmin):
    list_display = ("banco", "cuenta", "saldo_inicial", "activa")


@admin.register(MovimientoCuentaBancaria)
class MovimientoCuentaBancariaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "cuenta", "monto", "credito", "origen", "concepto")


@admin.register(Gasto)
class GastoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "descripcion", "monto", "cuenta_bancaria")
