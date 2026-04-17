"""Uso: desde la carpeta del proyecto, con DATABASE_URL vacía (ej. run_local.bat / cmd)."""
import os

os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "coop_manager.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model

db = settings.DATABASES["default"]
print("Motor:", db.get("ENGINE"))
print("Base: ", db.get("NAME"))
print()
U = get_user_model()
qs = list(U.objects.order_by("username"))
if not qs:
    print("No hay usuarios en esta base. Ejecutá crear_usuario_local.bat")
else:
    for u in qs:
        print(f"  - {u.username!r}  activo={u.is_active}")
