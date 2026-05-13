from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("warmup/", views.warmup, name="warmup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("sesion/cerrar-al-cerrar-ventana/", views.sesion_cerrar_al_cerrar_ventana, name="sesion_cerrar_al_cerrar_ventana"),
    path("modo-vendedor/", views.switch_to_vendor_mode, name="switch_to_vendor_mode"),
    path("modo-completo/", views.switch_to_full_mode, name="switch_to_full_mode"),
    path("modo-admin/", views.switch_to_admin_mode, name="switch_to_admin_mode"),
    path("cuenta/contrasena/", views.cambiar_password, name="cambiar_password"),
    path("notas/enviar/", views.nota_admin_enviar, name="nota_admin_enviar"),
    path("notas/chat.json", views.notas_chat_json, name="notas_chat_json"),
    path("notas/marcar-leidas-usuario/", views.notas_marcar_leidas_usuario, name="notas_marcar_leidas_usuario"),
]

