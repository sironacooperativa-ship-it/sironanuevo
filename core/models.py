from __future__ import annotations

from django.conf import settings
from django.db import models


class PerfilAcceso(models.Model):
    """
    Flags de acceso por usuario (no por rol staff).

    - solo_vendedor=True: solo puede usar el portal reducido (/vendedor/)
    - solo_vendedor=False: acceso completo (y opcionalmente puede entrar al portal si tiene perfil vendedor)
    """

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil_acceso",
    )
    solo_vendedor = models.BooleanField(default=False, db_index=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"PerfilAcceso({self.usuario_id})"


class NotaAdmin(models.Model):
    """Mensaje del usuario a administración o respuesta en el mismo hilo (estilo chat)."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notas_admin",
    )
    vendedor = models.ForeignKey(
        "personas.Vendedor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notas_admin",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="respuestas",
    )
    es_staff = models.BooleanField(default=False, db_index=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notas_admin_enviadas_staff",
    )
    texto = models.TextField(max_length=2000)
    pagina = models.CharField(max_length=255, blank=True, default="")
    leida = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Si es mensaje del usuario: lo leyó administración. Si es staff: siempre True al crear.",
    )
    leida_usuario = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Si es respuesta de staff: el usuario ya abrió/vio el mensaje.",
    )
    resuelto = models.BooleanField(
        default=False,
        db_index=True,
        help_text="En el mensaje raíz del hilo: administración marcó la consulta como resuelta.",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en", "-id"]

    def __str__(self) -> str:
        return f"NotaAdmin({self.pk}) de {self.usuario_id}"

    @property
    def raiz(self) -> "NotaAdmin":
        return self if self.parent_id is None else self.parent

