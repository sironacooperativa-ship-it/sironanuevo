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

