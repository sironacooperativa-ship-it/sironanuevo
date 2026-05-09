from django.urls import path

from . import views


urlpatterns = [
    path("", views.vendedor_home, name="vendedor_home"),
    path("presupuesto/<int:pk>/", views.vendedor_presupuesto_ver, name="vendedor_presupuesto_ver"),
    path("presupuestos/", views.vendedor_presupuestos_list, name="vendedor_presupuestos_list"),
    path("clientes/", views.vendedor_clientes_list, name="vendedor_clientes_list"),
    path("clientes/nuevo/", views.vendedor_cliente_create, name="vendedor_cliente_create"),
    path("clientes/<int:pk>/editar/", views.vendedor_cliente_update, name="vendedor_cliente_update"),
    path("stock/", views.vendedor_stock, name="vendedor_stock"),
    path("listas/", views.vendedor_listas, name="vendedor_listas"),
    path("listas/<slug:slug>/pdf/", views.vendedor_lista_pdf, name="vendedor_lista_pdf"),
    path("listas/<slug:slug>/excel/", views.vendedor_lista_excel, name="vendedor_lista_excel"),
    path("listas/<slug:slug>/png/", views.vendedor_lista_png, name="vendedor_lista_png"),
    path("ventas/", views.vendedor_ventas_list, name="vendedor_ventas_list"),
    path("ventas/<int:pk>/", views.vendedor_venta_ver, name="vendedor_venta_ver"),
    path("cuenta-corriente/", views.vendedor_cuenta_corriente, name="vendedor_cuenta_corriente"),
    path("reportes/", views.vendedor_reportes, name="vendedor_reportes"),
]

