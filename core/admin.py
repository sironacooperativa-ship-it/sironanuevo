from django.contrib import admin

from .models import NotaAdmin, PerfilAcceso


@admin.register(PerfilAcceso)
class PerfilAccesoAdmin(admin.ModelAdmin):
    list_display = ("usuario", "solo_vendedor", "actualizado_en")
    search_fields = ("usuario__username", "usuario__email")
    list_filter = ("solo_vendedor",)


@admin.register(NotaAdmin)
class NotaAdminAdmin(admin.ModelAdmin):
    list_display = ("creado_en", "usuario", "vendedor", "es_staff", "leida", "leida_usuario", "resuelto", "pagina", "texto")
    list_filter = ("leida", "es_staff", "leida_usuario", "resuelto", "creado_en")
    search_fields = ("usuario__username", "usuario__email", "vendedor__codigo", "vendedor__apellido", "texto")
    ordering = ("-creado_en", "-id")
