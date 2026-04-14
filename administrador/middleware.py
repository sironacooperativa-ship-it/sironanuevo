from __future__ import annotations

from django.utils.deprecation import MiddlewareMixin

from .models import RegistroActividad


def _omitir_ruta(path: str) -> bool:
    if path.startswith("/static/") or path.startswith("/media/"):
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
            try:
                RegistroActividad.registrar_http(request, response)
            except Exception:
                # No bloquear la respuesta si falla el registro (p. ej. BD en migración)
                pass
        return response
