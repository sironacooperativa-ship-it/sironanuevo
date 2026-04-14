from django.urls import path

from . import views


urlpatterns = [
    path("", views.calendario_home, name="calendario_home"),
]

