from django.urls import path

from . import views

urlpatterns = [
    path("", views.compra_historial, name="compra_historial"),
    path("nueva/", views.compra_registrar, name="compra_registrar"),
]
