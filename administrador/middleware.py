from __future__ import annotations

import os

from django.core.cache import cache
from django.utils.deprecation import MiddlewareMixin

from .models import RegistroActividad

# Evita un INSERT por cada GET mientras el usuario navega (mejora mucho la sensación de lentitud).
# Los POST (formularios, acciones) se siguen registrando siempre.
# Auditoría GET al detalle: REGISTRO_ACTIVIDAD_GET_INTERVAL=0
_REG_ACT_GET_BEAT = int(os.environ.get("REGISTRO_ACTIVIDAD_GET_INTERVAL", "45"))


def _omitir_ruta(path: str) -> bool:
    if path.startswith("/static/") or path.startswith("/media/"):
        return True
    if path.startswith("/health/") or path.startswith("/warmup/"):
        return True
    if "favicon" in path:
        return True
    return False


class RegistroActividadMiddleware(MiddlewareMixin):
    """Registra peticiones HTTP de usuarios autenticados (excepto estáticos)."""

    def process_response(self, request, response):
        if _omitir_ruta(request.path):
            return response
        if request.user.is_authenticated:
            if request.method == "GET" and _REG_ACT_GET_BEAT > 0:
                beat_key = f"reg_act:getbeat:{request.user.pk}"
                if cache.get(beat_key):
                    return response
                cache.set(beat_key, 1, _REG_ACT_GET_BEAT)
            try:
                RegistroActividad.registrar_http(request, response)
            except Exception:
                # No bloquear la respuesta si falla el registro (p. ej. BD en migración)
                pass
        return response
