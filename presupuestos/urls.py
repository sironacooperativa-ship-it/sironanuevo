from django.urls import path

from . import views

urlpatterns = [
    path("", views.presupuesto_lista, name="presupuesto_lista"),
    path("catalogo-precios/", views.presupuesto_catalogo_precios, name="presupuesto_catalogo_precios"),
    path("nuevo/", views.presupuesto_nuevo, name="presupuesto_nuevo"),
    path(
        "c/<str:token>/",
        views.presupuesto_compartido,
        name="presupuesto_compartido",
    ),
    path("<int:pk>/", views.presupuesto_detalle, name="presupuesto_detalle"),
    path("<int:pk>/editar/", views.presupuesto_editar, name="presupuesto_editar"),
    path("<int:pk>/eliminar/", views.presupuesto_eliminar, name="presupuesto_eliminar"),
    path("<int:pk>/aprobar/", views.presupuesto_aprobar, name="presupuesto_aprobar"),
    path("<int:pk>/comparativa/", views.presupuesto_comparativa, name="presupuesto_comparativa"),
    path("<int:pk>/duplicar/", views.presupuesto_duplicar, name="presupuesto_duplicar"),
    path(
        "aprobar-masivo/",
        views.presupuestos_aprobar_masivo,
        name="presupuestos_aprobar_masivo",
    ),
]
