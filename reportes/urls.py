from django.urls import path

from . import views

urlpatterns = [
    path("", views.reportes_dashboard, name="reportes_dashboard"),
    path(
        "productos-vendidos/export/",
        views.export_productos_vendidos,
        name="reportes_export_productos_vendidos",
    ),
]

