from django.urls import path

from . import views


urlpatterns = [
    path("", views.calendario_home, name="calendario_home"),
    path("exportar-pdf/", views.calendario_export_pdf, name="calendario_export_pdf"),
    path("dia/<slug:iso>/", views.calendario_agenda_dia, name="calendario_agenda_dia"),
]

