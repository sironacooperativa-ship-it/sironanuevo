from django.urls import path

from . import views

urlpatterns = [
    path("", views.venta_historial, name="ventas_historial"),
    path("comisiones/", views.venta_comisiones, name="ventas_comisiones"),
    path("comisiones/historial/", views.venta_comisiones_historial, name="ventas_comisiones_historial"),
    path(
        "comisiones/constancia/<int:pk>/",
        views.comision_constancia_pdf,
        name="ventas_comision_constancia_pdf",
    ),
    path("comisiones/liquidacion-pagar/", views.comision_liquidacion_pagar, name="ventas_comision_liquidacion_pagar"),
    path("nueva/", views.venta_nueva, name="venta_nueva"),
    path("catalogo-precios/", views.venta_catalogo_precios, name="venta_catalogo_precios"),
    path("catalogo-completo/", views.venta_catalogo_completo, name="venta_catalogo_completo"),
    path("<int:pk>/editar/", views.venta_editar, name="venta_editar"),
    path(
        "<int:pk>/comision/",
        views.venta_actualizar_comision,
        name="venta_actualizar_comision",
    ),
    path("<int:pk>/pago/", views.venta_registrar_pago, name="venta_registrar_pago"),
    path("<int:pk>/eliminar/", views.venta_eliminar, name="venta_eliminar"),
    path(
        "<int:pk>/producto/<int:producto_pk>/listas/",
        views.venta_producto_listas_precio,
        name="venta_producto_listas_precio",
    ),
    path("<int:pk>/", views.venta_detalle, name="venta_detalle"),
]
