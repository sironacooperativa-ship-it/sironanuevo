from django.urls import path

from . import views

urlpatterns = [
    path("actividad/", views.actividad_list, name="admin_actividad_list"),
    path("notas/", views.notas_list, name="admin_notas_list"),
    path("", views.usuarios_list, name="admin_usuarios_list"),
    path("usuarios/nuevo/", views.usuario_create, name="admin_usuario_create"),
    path("usuarios/<int:pk>/editar/", views.usuario_update, name="admin_usuario_update"),
    path(
        "usuarios/<int:pk>/password/",
        views.usuario_password,
        name="admin_usuario_password",
    ),
    path("backup/descargar/", views.backup_descargar, name="admin_backup_descargar"),
    path("backup/restaurar/", views.backup_restaurar, name="admin_backup_restaurar"),
    path("reset/", views.reset_datos, name="admin_reset_datos"),
]

