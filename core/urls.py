from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("warmup/", views.warmup, name="warmup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("modo-vendedor/", views.switch_to_vendor_mode, name="switch_to_vendor_mode"),
    path("modo-completo/", views.switch_to_full_mode, name="switch_to_full_mode"),
    path("cuenta/contrasena/", views.cambiar_password, name="cambiar_password"),
]

