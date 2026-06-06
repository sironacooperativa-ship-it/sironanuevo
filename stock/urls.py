from django.urls import path

from . import views


urlpatterns = [
    path("ajuste/", views.stock_ajuste_inline, name="stock_ajuste_inline"),
    path("quick-add/<int:pk>/", views.stock_quick_add, name="stock_quick_add"),
    path("", views.stock_home, name="stock_home"),
]

