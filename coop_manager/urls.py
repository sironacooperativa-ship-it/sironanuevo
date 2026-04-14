from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("productos/", include("productos.urls")),
    path("compras/", include("compras.urls")),
    path("bancos/", include("bancos.urls")),
    path("stock/", include("stock.urls")),
    path("personas/", include("personas.urls")),
    path("caja/", include("caja.urls")),
    path("calendario/", include("calendario.urls")),
    path("ventas/", include("ventas.urls")),
    path("presupuestos/", include("presupuestos.urls")),
    path("reportes/", include("reportes.urls")),
    path("administrador/", include("administrador.urls")),
]

