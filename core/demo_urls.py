from django.urls import path

from . import demo_views


urlpatterns = [
    path("", demo_views.demo_home, name="demo_home"),
    path("inicio/", demo_views.demo_home, name="demo_inicio"),
    path("vendedor/", demo_views.demo_vendedor_home, name="demo_vendedor_home"),
    path("vendedor/reportes/", demo_views.demo_vendedor_reportes, name="demo_vendedor_reportes"),
    path("presupuestos/", demo_views.demo_presupuestos, name="demo_presupuestos"),
    path("pedidos/", demo_views.demo_pedidos, name="demo_pedidos"),
    path("productos/", demo_views.demo_productos, name="demo_productos"),
    path("productos/nuevo/", demo_views.demo_producto_nuevo, name="demo_producto_nuevo"),
    path("listas-precios/", demo_views.demo_listas_precios, name="demo_listas_precios"),
    path("stock/", demo_views.demo_stock, name="demo_stock"),
    path("ventas/", demo_views.demo_ventas, name="demo_ventas"),
    path("caja/", demo_views.demo_caja, name="demo_caja"),
    path("reportes/", demo_views.demo_reportes, name="demo_reportes"),
    path("calendario/", demo_views.demo_calendario, name="demo_calendario"),
]

