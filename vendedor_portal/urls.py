from django.urls import path

from . import views


urlpatterns = [
    path("", views.vendedor_home, name="vendedor_home"),
    path("clientes/", views.vendedor_clientes_list, name="vendedor_clientes_list"),
    path("clientes/nuevo/", views.vendedor_cliente_create, name="vendedor_cliente_create"),
    path("clientes/<int:pk>/editar/", views.vendedor_cliente_update, name="vendedor_cliente_update"),
    path("listas/", views.vendedor_listas, name="vendedor_listas"),
    path("listas/<slug:slug>/pdf/", views.vendedor_lista_pdf, name="vendedor_lista_pdf"),
    path("listas/<slug:slug>/png/", views.vendedor_lista_png, name="vendedor_lista_png"),
    path("cuenta-corriente/", views.vendedor_cuenta_corriente, name="vendedor_cuenta_corriente"),
]

