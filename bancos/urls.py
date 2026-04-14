from django.urls import path

from . import views

urlpatterns = [
    path("", views.bancos_cuentas, name="bancos_cuentas"),
    path("cuentas/nueva/", views.banco_cuenta_nueva, name="banco_cuenta_nueva"),
    path("cuentas/<int:pk>/", views.banco_cuenta_detalle, name="banco_cuenta_detalle"),
    path("cuentas/<int:pk>/ajuste/", views.banco_cuenta_ajuste, name="banco_cuenta_ajuste"),
    path("gastos/", views.bancos_gastos, name="bancos_gastos"),
    path("gastos/nuevo/", views.banco_gasto_nuevo, name="banco_gasto_nuevo"),
    path("gastos/<int:pk>/eliminar/", views.banco_gasto_eliminar, name="banco_gasto_eliminar"),
]
