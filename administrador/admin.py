from django.contrib import admin

from .models import RegistroActividad


@admin.register(RegistroActividad)
class RegistroActividadAdmin(admin.ModelAdmin):
    list_display = ("fecha_hora", "nombre_usuario", "metodo", "ruta", "codigo_estado", "descripcion")
    list_filter = ("metodo", "codigo_estado")
    search_fields = ("nombre_usuario", "ruta", "descripcion", "ip")
    readonly_fields = (
        "usuario",
        "nombre_usuario",
        "fecha_hora",
        "ip",
        "metodo",
        "ruta",
        "consulta",
        "codigo_estado",
        "descripcion",
    )
    date_hierarchy = "fecha_hora"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
