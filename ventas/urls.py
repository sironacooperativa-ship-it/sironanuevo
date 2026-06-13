from django.urls import path

from . import despacho_views, views

urlpatterns = [
    path("", views.venta_historial, name="ventas_historial"),
    path("despachos/", views.despachos_lista, name="despachos_lista"),
    path("despachos/armado/", despacho_views.armado_pedidos_lista, name="armado_pedidos_lista"),
    path("despachos/armado/colectivo/", despacho_views.armado_colectivo, name="armado_colectivo"),
    path("despachos/armado/colectivo/guardar/", despacho_views.armado_colectivo_guardar, name="armado_colectivo_guardar"),
    path("despachos/armado/colectivo/pdf/", despacho_views.armado_colectivo_pdf, name="armado_colectivo_pdf"),
    path("despachos/armado/guardado/<int:pk>/", despacho_views.armado_colectivo_ver, name="armado_colectivo_ver"),
    path("despachos/armado/guardado/<int:pk>/editar/", despacho_views.armado_colectivo_editar, name="armado_colectivo_editar"),
    path("despachos/armado/guardado/<int:pk>/eliminar/", despacho_views.armado_colectivo_eliminar, name="armado_colectivo_eliminar"),
    path("despachos/armado/guardado/<int:pk>/pdf/", despacho_views.armado_colectivo_guardado_pdf, name="armado_colectivo_guardado_pdf"),
    path("despachos/puntos-stock/", despacho_views.puntos_stock_modal, name="puntos_stock_modal"),
    path("despachos/puntos-stock/guardar/", despacho_views.puntos_stock_guardar, name="puntos_stock_guardar"),
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
    path(
        "<int:pk>/despacho/",
        views.venta_actualizar_despacho,
        name="venta_actualizar_despacho",
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
