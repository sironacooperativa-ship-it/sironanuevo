"""Mediciones agregadas sin SQL, usuarios, parámetros ni datos de pedidos."""
import logging
import os
from time import perf_counter
from django.conf import settings
from django.db import connection

logger = logging.getLogger("django.server")
PATHS = {"/", "/ventas/", "/presupuestos/", "/productos/", "/caja/"}


class PerformanceLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        enabled = os.environ.get("SIRONA_PERFORMANCE_LOG", "0" if settings.DEBUG else "1") == "1"
        if not enabled or request.method != "GET" or request.path not in PATHS:
            return self.get_response(request)
        stats = {"queries": 0, "db": 0.0}

        def measure(execute, sql, params, many, context):
            start = perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                stats["queries"] += 1
                stats["db"] += perf_counter() - start

        start = perf_counter()
        with connection.execute_wrapper(measure):
            response = self.get_response(request)
        logger.info("Sirona rendimiento: GET %s estado=%s total_ms=%.1f db_ms=%.1f consultas=%s",
                    request.path, response.status_code, (perf_counter()-start)*1000,
                    stats["db"]*1000, stats["queries"])
        return response
