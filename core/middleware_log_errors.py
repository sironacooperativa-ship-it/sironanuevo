"""Registra excepciones no capturadas antes del 500 (útil en Render/consola)."""
from __future__ import annotations

import logging

from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger("sirona.errors")


class LogUnhandledExceptionMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        user = getattr(request, "user", None)
        username = user.get_username() if user and user.is_authenticated else "anon"
        logger.exception(
            "Unhandled %s on %s %s (user=%s)",
            type(exception).__name__,
            request.method,
            request.path,
            username,
        )
        return None
