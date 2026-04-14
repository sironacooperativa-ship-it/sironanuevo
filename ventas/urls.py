from django.urls import path

from . import views

urlpatterns = [
    path("", views.venta_historial, name="ventas_historial"),
    path("nueva/", views.venta_nueva, name="venta_nueva"),
    path("<int:pk>/editar/", views.venta_editar, name="venta_editar"),
    path("<int:pk>/pago/", views.venta_registrar_pago, name="venta_registrar_pago"),
    path("<int:pk>/", views.venta_detalle, name="venta_detalle"),
]
