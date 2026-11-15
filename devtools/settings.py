"""Nunca usar conexiones ni archivos de producción."""
import os
import tempfile
from pathlib import Path

# Limpiar antes de importar: settings original decide DB y caché con DATABASE_URL.
os.environ.pop("DATABASE_URL", None)
os.environ["DEBUG"] = "1"
os.environ["SECRET_KEY"] = "sirona-isolated-development-only-never-use-in-production"

from coop_manager.settings import *  # noqa: F401,F403,E402

DEV_ROOT = Path(tempfile.gettempdir()) / f"sirona-dev-{os.getuid()}"
DEV_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": DEV_ROOT / "db.sqlite3",
    "TEST": {"NAME": ":memory:"},
}}
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
CACHES = {
    alias: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    for alias in ("default", "ui")
}
MEDIA_ROOT = DEV_ROOT / "media"
STATIC_ROOT = DEV_ROOT / "staticfiles"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
