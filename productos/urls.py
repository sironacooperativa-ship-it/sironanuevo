from django.urls import path

from . import listas_precios_views, views


urlpatterns = [
    path("stock-cero-resolver/", views.producto_stock_cero_resolver, name="producto_stock_cero_resolver"),
    path("picker.json", views.productos_picker_json, name="productos_picker_json"),
    path("", views.productos_list, name="productos_list"),
    path("aumento/", views.productos_aumento, name="productos_aumento"),
    path("vencimientos/", views.productos_vencimientos, name="productos_vencimientos"),
    path("nuevo/", views.producto_create, name="producto_create"),
    path("<int:pk>/inline/", views.producto_inline_update, name="producto_inline_update"),
    path("<int:pk>/editar/", views.producto_update, name="producto_update"),
    path(
        "<int:pk>/listas-comparativa.json",
        views.producto_listas_comparativa_json,
        name="producto_listas_comparativa_json",
    ),
    path("<int:pk>/eliminar/", views.producto_delete, name="producto_delete"),
    path("<int:pk>/toggle-habilitado/", views.producto_toggle_habilitado, name="producto_toggle_habilitado"),
    path("<int:pk>/toggle-lista/", views.producto_toggle_lista, name="producto_toggle_lista"),
    path("acciones-masa/", views.productos_acciones_masa, name="productos_acciones_masa"),
    path("importar-excel/", views.productos_import_excel, name="productos_import_excel"),
    path(
        "importar-excel/resumen/",
        views.productos_import_excel_resumen,
        name="productos_import_excel_resumen",
    ),
    path(
        "importar-excel/modelo.xlsx",
        views.productos_import_excel_modelo,
        name="productos_import_excel_modelo",
    ),
    path("lista-precios.pdf", views.productos_export_pdf, name="productos_export_pdf"),
    path("export/costos.xlsx", views.productos_export_costos_excel, name="productos_export_costos_excel"),
    path("listas/guardar/", views.lista_precios_guardar, name="lista_precios_guardar"),
    path("listas/aplicar/", views.lista_precios_aplicar, name="lista_precios_aplicar"),
    path("listas-precio/", listas_precios_views.listas_precios_menu, name="productos_listas_precios"),
    path("listas-precio/nueva/", listas_precios_views.lista_precios_nueva, name="lista_precios_nueva"),
    path(
        "listas-precio/nueva/confirmar/",
        listas_precios_views.lista_precios_nueva_confirmar,
        name="lista_precios_nueva_confirmar",
    ),
    path("listas-precio/<int:pk>/ver/", listas_precios_views.lista_precios_ver, name="lista_precios_ver"),
    path(
        "listas-precio/<int:pk>/export/pdf/",
        listas_precios_views.lista_precios_export_pdf,
        name="lista_precios_export_pdf",
    ),
    path(
        "listas-precio/<int:pk>/export/excel/",
        listas_precios_views.lista_precios_export_excel,
        name="lista_precios_export_excel",
    ),
    path(
        "listas-precio/<int:pk>/export/png/",
        listas_precios_views.lista_precios_export_png,
        name="lista_precios_export_png",
    ),
    path(
        "listas-precio/public/farmacia/png/",
        listas_precios_views.lista_precios_public_farmacia_png,
        name="lista_precios_public_farmacia_png",
    ),
    path(
        "listas-precio/public/<slug:slug>/cliente/",
        listas_precios_views.lista_precios_public_cliente,
        name="lista_precios_public_cliente",
    ),
    path("listas-precio/<int:pk>/", listas_precios_views.lista_precios_trabajar, name="lista_precios_trabajar"),
    path("listas-precio/<int:pk>/renombrar/", listas_precios_views.lista_precios_renombrar, name="lista_precios_renombrar"),
    path("listas-precio/<int:pk>/eliminar/", listas_precios_views.lista_precios_eliminar, name="lista_precios_eliminar"),
]

