"""Sesión: cierre por inactividad y política de cookies."""
from __future__ import annotations

import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.shortcuts import resolve_url

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
