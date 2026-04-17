from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("warmup/", views.warmup, name="warmup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("cuenta/contrasena/", views.cambiar_password, name="cambiar_password"),
]

