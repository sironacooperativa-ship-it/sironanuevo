"""Sesión: cierre por inactividad y política de cookies."""
from __future__ import annotations

import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.shortcuts import resolve_url

from core.models import PerfilAcceso

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
    Enforce acceso por usuario:
    - usuario.perfil_acceso.solo_vendedor=True: siempre portal (bloquea sistema completo)
    - caso contrario: acceso completo (y si entra al portal es por elección en login)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not getattr(request.user, "is_staff", False):
            path = request.path or "/"
            if (
                path.startswith("/static/")
                or path.startswith("/login/")
                or path.startswith("/logout/")
                or path.startswith("/admin/")
                or path.startswith("/health/")
                or path.startswith("/warmup/")
            ):
                return self.get_response(request)

            # Si no existe el perfil aún (usuarios viejos), lo creamos.
            perfil = getattr(request.user, "perfil_acceso", None)
            if perfil is None:
                PerfilAcceso.objects.get_or_create(
                    usuario=request.user,
                    defaults={"solo_vendedor": bool(getattr(request.user, "vendedor_perfil", None) is not None)},
                )
                perfil = getattr(request.user, "perfil_acceso", None)

            solo_vendedor = bool(getattr(perfil, "solo_vendedor", False))
            in_portal = path.startswith("/vendedor/")
            # Enlace firmado de presupuesto (cliente): no forzar portal
            presupuesto_compartido = path.startswith("/presupuestos/c/")
            if solo_vendedor and not in_portal and not presupuesto_compartido:
                request.session["modo_vendedor"] = True
                return HttpResponseRedirect(resolve_url("vendedor_home"))

        return self.get_response(request)
