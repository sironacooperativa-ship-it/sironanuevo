"""Sesión: cierre por inactividad y política de cookies."""
from __future__ import annotations

import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.shortcuts import resolve_url

from personas.models import Vendedor

_SESSION_LAST_ACTIVITY = "_session_last_activity"


class IdleSessionTimeoutMiddleware:
    """
    Cierra la sesión si pasó más de SESSION_IDLE_TIMEOUT_SECONDS sin actividad
    (cualquier petición autenticada reinicia el reloj).
    Debe ir después de AuthenticationMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout = int(getattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 30 * 60))

    def __call__(self, request):
        if request.user.is_authenticated:
            now = time.time()
            last = request.session.get(_SESSION_LAST_ACTIVITY)
            if last is not None and (now - last) > self.timeout:
                next_path = request.get_full_path()
                logout(request)
                login_url = resolve_url(settings.LOGIN_URL)
                query = urlencode({"idle": "1", "next": next_path})
                return HttpResponseRedirect(f"{login_url}?{query}")
            request.session[_SESSION_LAST_ACTIVITY] = now

        return self.get_response(request)


class VendedorAccessMiddleware:
    """
    Enforce acceso de vendedor:
    - SOLO_VENDEDOR: siempre portal (bloquea sistema completo)
    - SOLO_COMPLETO: bloquea portal vendedor
    - AMBOS: permite ambos
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not getattr(request.user, "is_staff", False):
            v = getattr(request.user, "vendedor_perfil", None)
            if v is not None:
                path = request.path or "/"
                # Permitir siempre login/logout/static/admin (y assets)
                if (
                    path.startswith("/static/")
                    or path.startswith("/login/")
                    or path.startswith("/logout/")
                    or path.startswith("/admin/")
                ):
                    return self.get_response(request)

                acceso = getattr(v, "acceso", None)
                in_portal = path.startswith("/vendedor/")

                if acceso == Vendedor.Acceso.SOLO_VENDEDOR and not in_portal:
                    return HttpResponseRedirect(resolve_url("vendedor_home"))
                if acceso == Vendedor.Acceso.SOLO_COMPLETO and in_portal:
                    return HttpResponseRedirect(resolve_url("home"))

        return self.get_response(request)
