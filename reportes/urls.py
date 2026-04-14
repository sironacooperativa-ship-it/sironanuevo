from django.urls import path

from . import views

urlpatterns = [
    path("", views.reportes_dashboard, name="reportes_dashboard"),
]

