from django.urls import path

from . import views

urlpatterns = [
    path("", views.compra_historial, name="compra_historial"),
    path("nueva/", views.compra_registrar, name="compra_registrar"),
    path("admin/<int:pk>/eliminar/", views.compra_admin_eliminar, name="compra_admin_eliminar"),
    path("admin/<int:pk>/anular/", views.compra_admin_anular, name="compra_admin_anular"),
]
