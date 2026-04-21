"""Utilidades de seguridad compartidas (redirecciones, cliente HTTP)."""


def safe_internal_path(path: str) -> str:
    """
    Evita redirecciones abiertas: solo rutas relativas internas.
    Rechaza '//' (scheme-relative), URLs absolutas en el path y valores vacíos.
    """
    if not path:
        return ""
    s = str(path).strip()
    if not s.startswith("/") or s.startswith("//"):
        return ""
    # Bloquea "/http://..." o "/https://..." que algunos clientes podrían malinterpretar
    low = s.split("?", 1)[0].lower()
    if "://" in low:
        return ""
    return s


def client_ip(request) -> str:
    """IP del cliente; primera de X-Forwarded-For si viene de proxy (p. ej. Render)."""
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    return (request.META.get("REMOTE_ADDR") or "").strip() or "unknown"
