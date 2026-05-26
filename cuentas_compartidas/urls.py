from django.urls import path

from . import views


urlpatterns = [
    path("", views.cuentas_dashboard, name="cuentas_dashboard"),
    path("operaciones/nueva/", views.operacion_nueva, name="cuentas_operacion_nueva"),
    path("operaciones/<int:pk>/", views.operacion_detalle, name="cuentas_operacion_detalle"),
    path("deudas/<int:pk>/cancelar/", views.cancelar_deuda, name="cuentas_cancelar_deuda"),
    path("negocios/", views.negocios, name="cuentas_negocios"),
]
