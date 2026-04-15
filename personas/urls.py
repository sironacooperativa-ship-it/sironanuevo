from django.urls import path

from . import views


urlpatterns = [
    path("vendedores/", views.vendedores_list, name="vendedores_list"),
    path("vendedores/nuevo/", views.vendedor_create, name="vendedor_create"),
    path("vendedores/<int:pk>/", views.vendedor_detalle, name="vendedor_detalle"),
    path("vendedores/<int:pk>/editar/", views.vendedor_update, name="vendedor_update"),
    path("vendedores/<int:pk>/eliminar/", views.vendedor_delete, name="vendedor_delete"),
    path("vendedores/<int:pk>/toggle/", views.vendedor_toggle, name="vendedor_toggle"),
    path("proveedores/", views.proveedores_list, name="proveedores_list"),
    path("proveedores/nuevo/", views.proveedor_create, name="proveedor_create"),
    path("proveedores/<int:pk>/editar/", views.proveedor_update, name="proveedor_update"),
    path("proveedores/<int:pk>/eliminar/", views.proveedor_delete, name="proveedor_delete"),
    path("proveedores/<int:pk>/toggle/", views.proveedor_toggle, name="proveedor_toggle"),
    path("compradores/", views.compradores_list, name="compradores_list"),
    path("compradores/nuevo/", views.comprador_create, name="comprador_create"),
    path("compradores/<int:pk>/editar/", views.comprador_update, name="comprador_update"),
    path("compradores/<int:pk>/eliminar/", views.comprador_delete, name="comprador_delete"),
    path("compradores/<int:pk>/toggle/", views.comprador_toggle, name="comprador_toggle"),
]

