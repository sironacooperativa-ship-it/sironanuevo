from django.urls import path

from . import views


urlpatterns = [
    path("actualizar-saldo/", views.caja_actualizar_saldo, name="caja_actualizar_saldo"),
    path("", views.caja_list, name="caja_list"),
    path("historico/", views.caja_historico, name="caja_historico"),
    path("cheques/", views.caja_cheques, name="caja_cheques"),
    path("nuevo/", views.caja_create, name="caja_create"),
    path("<int:pk>/editar/", views.caja_edit, name="caja_edit"),
    path("<int:pk>/", views.caja_detail, name="caja_detail"),
    path("<int:pk>/eliminar/", views.caja_delete, name="caja_delete"),
]

