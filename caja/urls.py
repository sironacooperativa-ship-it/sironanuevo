from django.urls import path

from . import views


urlpatterns = [
    path("", views.caja_list, name="caja_list"),
    path("nuevo/", views.caja_create, name="caja_create"),
    path("<int:pk>/", views.caja_detail, name="caja_detail"),
    path("<int:pk>/eliminar/", views.caja_delete, name="caja_delete"),
]

