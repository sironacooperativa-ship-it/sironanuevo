from django.urls import path

from . import views


urlpatterns = [
    path("", views.caja_list, name="caja_list"),
    path("cheques/", views.caja_cheques, name="caja_cheques"),
    path("nuevo/", views.caja_create, name="caja_create"),
    path("<int:pk>/editar/", views.caja_edit, name="caja_edit"),
    path("<int:pk>/", views.caja_detail, name="caja_detail"),
    path("<int:pk>/eliminar/", views.caja_delete, name="caja_delete"),
]

