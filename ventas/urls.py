from django.urls import path

from . import views

urlpatterns = [
    path("", views.venta_historial, name="ventas_historial"),
    path("nueva/", views.venta_nueva, name="venta_nueva"),
    path("<int:pk>/pago/", views.venta_registrar_pago, name="venta_registrar_pago"),
]
