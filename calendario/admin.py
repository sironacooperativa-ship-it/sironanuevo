from django.contrib import admin

from .models import Evento


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tipo", "titulo", "creado_en")
    list_filter = ("tipo", "fecha")
    search_fields = ("titulo", "descripcion")

