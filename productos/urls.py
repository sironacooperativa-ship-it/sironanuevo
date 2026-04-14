from django.urls import path

from . import views


urlpatterns = [
    path("", views.productos_list, name="productos_list"),
    path("nuevo/", views.producto_create, name="producto_create"),
    path("<int:pk>/editar/", views.producto_update, name="producto_update"),
    path("<int:pk>/eliminar/", views.producto_delete, name="producto_delete"),
    path("<int:pk>/toggle-habilitado/", views.producto_toggle_habilitado, name="producto_toggle_habilitado"),
    path("<int:pk>/toggle-lista/", views.producto_toggle_lista, name="producto_toggle_lista"),
    path("importar-excel/", views.productos_import_excel, name="productos_import_excel"),
    path(
        "importar-excel/modelo.xlsx",
        views.productos_import_excel_modelo,
        name="productos_import_excel_modelo",
    ),
    path("lista-precios.pdf", views.productos_export_pdf, name="productos_export_pdf"),
    path("listas/guardar/", views.lista_precios_guardar, name="lista_precios_guardar"),
    path("listas/aplicar/", views.lista_precios_aplicar, name="lista_precios_aplicar"),
]

