from django.urls import path

from . import views


urlpatterns = [
    path("ajuste/", views.stock_ajuste_inline, name="stock_ajuste_inline"),
    path("", views.stock_home, name="stock_home"),
]

