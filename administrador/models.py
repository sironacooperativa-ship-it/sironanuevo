from __future__ import annotations

from django.conf import settings
from django.db import models


def _client_ip(request) -> str | None:
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if xff:
        return xff.split(",")[0].strip()[:45] or None
    addr = (request.META.get("REMOTE_ADDR") or "").strip()
    return addr[:45] if addr else None


class RegistroActividad(models.Model):
    """
    Traza de uso de la aplicación por usuario (HTTP autenticado + cierre de sesión explícito).
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registros_actividad",
    )
    nombre_usuario = models.CharField(max_length=150, db_index=True)
    fecha_hora = models.DateTimeField(auto_now_add=True, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    metodo = models.CharField(max_length=10)
    ruta = models.CharField(max_length=512)
    consulta = models.CharField(max_length=512, blank=True, default="")
    codigo_estado = models.PositiveSmallIntegerField(default=0)
    descripcion = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-fecha_hora", "-id"]
        verbose_name = "Registro de actividad"
        verbose_name_plural = "Registros de actividad"
        indexes = [
            models.Index(fields=["usuario", "fecha_hora"], name="reg_act_usuario_fecha"),
        ]

    def __str__(self) -> str:
        return f"{self.nombre_usuario} {self.fecha_hora} {self.metodo} {self.ruta}"

    @classmethod
    def registrar_http(cls, request, response) -> None:
        """Registra una petición ya autenticada (llamar solo si request.user.is_authenticated)."""
        user = request.user
        descripcion = ""
        path = (request.path or "").rstrip("/")
        if request.method == "POST" and path.endswith("/login"):
            descripcion = "Inicio de sesión"
        cls.objects.create(
            usuario=user,
            nombre_usuario=user.get_username()[:150],
            ip=_client_ip(request),
            metodo=(request.method or "?")[:10],
            ruta=path[:512],
            consulta=(request.META.get("QUERY_STRING") or "")[:512],
            codigo_estado=getattr(response, "status_code", 0) or 0,
            descripcion=descripcion[:255],
        )

    @classmethod
    def registrar_cierre_sesion(cls, user, request) -> None:
        """Antes de llamar a logout(); el usuario sigue autenticado en request."""
        cls.objects.create(
            usuario=user,
            nombre_usuario=user.get_username()[:150],
            ip=_client_ip(request),
            metodo=(request.method or "?")[:10],
            ruta=(request.path or "")[:512],
            consulta=(request.META.get("QUERY_STRING") or "")[:512],
            codigo_estado=0,
            descripcion="Cierre de sesión",
        )
